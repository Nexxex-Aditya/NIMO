"""`uv run python -m nimo.run --sheet dev [--live] [--limit N]` — the batch runner CLI.

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

Batch-level setup (workbook, config, classifier fit, registry index) happens
once, before any row is touched, and is deliberately **not** wrapped in the
runner's failure handling: a missing workbook is not a per-row condition and
retrying it 412 times would print the same error 412 times.
"""

import sys
from pathlib import Path

from nimo.classify import load_classify_config
from nimo.classify.model import ModuleClassifier
from nimo.fetch import Fetcher, default_page_cache, load_fetch_config
from nimo.loader import load_characteristic_rules, load_module_labels, load_rows
from nimo.match import load_match_config
from nimo.normalize import normalize_rows
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
        artifacts=OUT_DIR / "artifacts" / sheet,
        trace=OUT_DIR / "trace.jsonl",
        failures=OUT_DIR / "failures.jsonl",
        config_dir=CONFIG_DIR,
    )
    counter = CacheCounter()

    if not live:
        stages = offline_stages(index, thresholds, classifier)
        summary = run(rows, stages, paths, run_id, cache_counter=counter)
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
            )
            summary = run(rows, stages, paths, run_id, cache_counter=counter)
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
