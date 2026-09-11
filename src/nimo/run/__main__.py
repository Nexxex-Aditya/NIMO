"""`uv run python -m nimo.run --sheet dev [--live] [--limit N] [--adjudicate]
[--characteristics] [--out-dir D]` — the batch runner CLI.

`print` here is the CLI's user-facing output, which `04` §10 permits; nothing
in the library prints.

Two modes:

- **default (offline):** normalize -> registry -> classify, with empty
  retrieval/fetch/match. No network. This is the resumability and
  failure-attribution path P6a proved, and it runs 412 rows in seconds.
- **`--live`:** the full pipeline through SearxNG, the fetcher and the
  matcher. Needs a running SearxNG (`docker compose up -d searxng`) and spends
  real search and fetch budget — `--limit N` caps the rows for a trial run.
  Resumable: a killed run skips completed rows on restart, and every registry
  merge is persisted the moment it happens.
- **`--characteristics`** (with `--live`): P12 extraction through the model;
  without it the stage runs gate-only (the null pattern, no values).
- **`--adjudicate`** (with `--live`): Tier 3 LLM adjudication on rows where
  Layer A could not separate the top candidates. Needs `CIS_LLM_API_KEY` in
  `.env` and the NIQ network (`config/models.yaml`). `--out-dir` writes the
  artifacts beside a baseline run instead of over it, which is how the P11
  gate is measured (`specs/adjudicate.md` §8).

Batch-level setup (workbook, config, classifier fit, registry index) happens
once, before any row is touched, and is deliberately **not** wrapped in the
runner's failure handling: a missing workbook is not a per-row condition and
retrying it 412 times would print the same error 412 times.
"""

import sys
from dataclasses import replace
from pathlib import Path

from nimo.calibrate import CURVE_PATH, load_calibration_config, read_curve
from nimo.characteristics import (
    CharacteristicExtractor,
    guideline_index,
    load_characteristics_config,
)
from nimo.classify import load_classify_config
from nimo.classify.model import ModuleClassifier
from nimo.fetch import Fetcher, default_page_cache, load_fetch_config
from nimo.llm import LlmBudgetExceeded, LlmClient, LlmCounter, load_llm_config, load_prompt
from nimo.loader import (
    load_characteristic_guidelines,
    load_characteristic_rules,
    load_module_labels,
    load_rows,
)
from nimo.match import Adjudicator, load_match_config
from nimo.normalize import normalize_rows
from nimo.reason import load_reason_config
from nimo.registry import build_index, fit_identity_idf, load_thresholds, read_entities
from nimo.retrieval import SearxngClient, default_cache, load_retrieval_config
from nimo.run.live import RegistryWriter, live_stages
from nimo.run.runner import CacheCounter, RunPaths, format_summary, offline_stages, run
from nimo.settings import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
CONFIG_DIR = REPO_ROOT / "config"
RETAILERS = CONFIG_DIR / "retailers.yaml"
REGISTRY_DIR = REPO_ROOT / "data" / "registry"
CACHE_DIR = REPO_ROOT / "data" / "cache"
OUT_DIR = REPO_ROOT / "data" / "out"


def main(argv: list[str]) -> int:
    sheet = "dev"
    if "--sheet" in argv:
        sheet = argv[argv.index("--sheet") + 1]
    run_id = argv[argv.index("--run-id") + 1] if "--run-id" in argv else f"run-{sheet}"
    live = "--live" in argv
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    adjudicate = "--adjudicate" in argv
    characteristics = "--characteristics" in argv
    out_dir = Path(argv[argv.index("--out-dir") + 1]) if "--out-dir" in argv else OUT_DIR
    if adjudicate and not live:
        print("--adjudicate needs --live: Tier 3 adjudicates fetched candidates.")
        return 2
    if (adjudicate or characteristics) and not settings.cis_llm_api_key:
        # `04` §9: validated present at startup, not at the first call.
        print("the model needs CIS_LLM_API_KEY in `.env` (see .env.example, config/models.yaml).")
        return 2
    if characteristics and not live:
        # Allowed: the extractor codes from the product record alone (`01` §6's
        # fallback). A lower bound for the P12 gate when no page evidence is
        # available — said out loud so it is not mistaken for the gate number.
        print(
            "NOTE: --characteristics without --live extracts from the RECORD ALONE (no page "
            "evidence). This is the description-only baseline, not the P12 gate."
        )

    rows = load_rows(WORKBOOK, sheet, RETAILERS)
    if limit is not None:
        rows = rows[:limit]

    # The classifier always fits on `dev` — it is the only sheet with MODULE
    # ground truth (`01` §6). Running over `qa` classifies with a dev-fitted
    # model, which is the intended direction.
    rules = load_characteristic_rules(WORKBOOK)
    dev_rows = load_rows(WORKBOOK, "dev", RETAILERS)
    dev_queries = normalize_rows(dev_rows)
    classifier = ModuleClassifier.fit(
        dev_queries, load_module_labels(WORKBOOK, "dev", rules), load_classify_config()
    )

    entities = read_entities(REGISTRY_DIR / "entities.jsonl")
    index = build_index(entities, fit_identity_idf(dev_queries))
    thresholds = load_thresholds()

    paths = RunPaths(
        artifacts=out_dir / "artifacts" / sheet,
        trace=out_dir / "trace.jsonl",
        failures=out_dir / "failures.jsonl",
        config_dir=CONFIG_DIR,
    )
    counter = CacheCounter()
    llm_counter = LlmCounter()

    if not live:
        stages = offline_stages(index, thresholds, classifier, rules, load_reason_config())
        if characteristics:
            from nimo.llm.azure import azure_complete_fn

            llm_config = load_llm_config()
            assert settings.cis_llm_api_key is not None  # checked above
            record_only = CharacteristicExtractor(
                llm=LlmClient(
                    config=llm_config,
                    complete=azure_complete_fn(llm_config, settings.cis_llm_api_key),
                    cache_dir=CACHE_DIR / "llm",
                    counter=llm_counter,
                    retry_prompt=load_prompt("json_retry"),
                ),
                prompt=load_prompt("characteristics"),
                retry_prompt=load_prompt("characteristics_retry"),
                rules=rules,
                guidelines=guideline_index(load_characteristic_guidelines(WORKBOOK)),
                config=load_characteristics_config(),
            )
            stages = replace(
                stages,
                characteristics=lambda query, module, evidence: record_only.extract(
                    query, module, None
                ),
            )
        summary = run(
            rows,
            stages,
            paths,
            run_id,
            cache_counter=counter,
            llm_counter=llm_counter,
            abort_on=(LlmBudgetExceeded,),
            rules=rules,
        )
    else:
        rcfg = load_retrieval_config()
        fcfg = load_fetch_config()
        searx = SearxngClient.create(
            settings.searxng_base_url,
            rcfg,
            cache=default_cache(CACHE_DIR / "search", rcfg.cache_ttl_days, rcfg.cache_enabled),
        )
        fetcher = Fetcher.create(
            fcfg,
            cache=default_page_cache(
                CACHE_DIR / "pages",
                fcfg.cache_ttl_days,
                fcfg.failure_cache_ttl_hours,
                fcfg.cache_enabled,
            ),
        )
        writer = RegistryWriter(
            entities_path=REGISTRY_DIR / "entities.jsonl",
            audit_path=REGISTRY_DIR / "audit.jsonl",
            run_id=run_id,
            entities={entity.entity_id: entity for entity in entities},
        )
        adjudicator: Adjudicator | None = None
        extractor: CharacteristicExtractor | None = None
        calibration = load_calibration_config()
        curve = read_curve(CURVE_PATH)
        if curve is None:
            print(
                "calibration: NO CURVE at data/calibration/curve.json — calibrated_prob mirrors "
                "raw_score; run `uv run python -m nimo.calibrate` after a harvest."
            )
        else:
            print(
                f"calibration: curve loaded ({curve.n_pairs} pairs, {curve.n_positive} positive); "
                f"tau_abstain={calibration.tau_abstain}"
                + (" (OFF)" if calibration.tau_abstain == 0.0 else "")
            )
        if adjudicate or characteristics:
            # Imported here and only here: the SDK is the network, and no other
            # path needs it (`specs/adjudicate.md` §6).
            from nimo.llm.azure import azure_complete_fn

            llm_config = load_llm_config()
            assert settings.cis_llm_api_key is not None  # checked above
            llm = LlmClient(
                config=llm_config,
                complete=azure_complete_fn(llm_config, settings.cis_llm_api_key),
                cache_dir=CACHE_DIR / "llm",
                counter=llm_counter,
                retry_prompt=load_prompt("json_retry"),
            )
            if adjudicate:
                adjudicator = Adjudicator(
                    llm=llm, prompt=load_prompt("adjudicate"), config=load_match_config()
                )
            if characteristics:
                extractor = CharacteristicExtractor(
                    llm=llm,
                    prompt=load_prompt("characteristics"),
                    retry_prompt=load_prompt("characteristics_retry"),
                    rules=rules,
                    guidelines=guideline_index(load_characteristic_guidelines(WORKBOOK)),
                    config=load_characteristics_config(),
                )
        try:
            stages = live_stages(
                searx=searx,
                fetcher=fetcher,
                retrieval_config=rcfg,
                match_config=load_match_config(),
                retailers_path=RETAILERS,
                index=index,
                thresholds=thresholds,
                classifier=classifier,
                writer=writer,
                cache_counter=counter,
                rules=rules,
                reason_config=load_reason_config(),
                adjudicator=adjudicator,
                extractor=extractor,
                curve=curve,
                tau_abstain=calibration.tau_abstain,
            )
            summary = run(
                rows,
                stages,
                paths,
                run_id,
                cache_counter=counter,
                llm_counter=llm_counter,
                abort_on=(LlmBudgetExceeded,),
                rules=rules,
            )
        finally:
            searx.close()
            fetcher.close()
        print(f"engines circuit-broken: {searx.breaker.blocked_engines or 'none'}")
        blocked_hosts = sorted(
            host for host, counts in fetcher.domain_outcomes.items() if counts.get("blocked")
        )
        if blocked_hosts:
            print(f"hosts that blocked us ({len(blocked_hosts)}): {', '.join(blocked_hosts[:12])}")
        print(f"registry: {len(writer.entities)} entities after this run")
        if adjudicate or characteristics:
            print(
                f"model: {llm_counter.calls} calls, {llm_counter.cache_hits} cache hits, "
                f"{llm_counter.rejected_verdicts} verdicts rejected by validation"
            )
        if not characteristics:
            print(
                "characteristics: GATE-ONLY (null pattern applied, no values) — pass "
                "--characteristics on the NIQ network to extract values."
            )

    print(format_summary(summary))
    if not live:
        print(
            "mode: OFFLINE — retrieval/fetch/match were empty by construction. "
            "Pass --live for the full pipeline (needs SearxNG up)."
        )
    if not entities and not live:
        print(
            "registry: cold (0 entities) — every row reads tier2_retrieval, which is the "
            "honest cold-start number. Tier 0 fires 412/412 on a re-run against a warm "
            "registry (`specs/registry.md` §3)."
        )
    return 1 if summary.rows_failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
