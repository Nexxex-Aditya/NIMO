"""One place that composes the pipeline — shared by the CLI and the UI.

`run/__main__.py` used to build the classifier, the registry index, the
search client, the fetcher, the model clients and the stages inline. The UI
(P16) needs exactly the same composition, and two copies of it would drift
— the "measurement logic differs from pipeline logic" failure this project
has logged three times. So the composition lives here, once, and both
entry points call it.

Nothing here decides anything about a row; it wires the stages `runner.py`
drives. Batch-level setup failures (a missing workbook, a bad config) raise
here and are deliberately NOT caught (`04` §4).
"""

import base64
from dataclasses import dataclass, field, replace
from pathlib import Path

import structlog

from nimo.calibrate import CURVE_PATH, IsotonicCurve, load_calibration_config, read_curve
from nimo.characteristics import (
    CharacteristicExtractor,
    ImageFetchFn,
    guideline_index,
    load_characteristics_config,
)
from nimo.classify import load_classify_config
from nimo.classify.model import ModuleClassifier
from nimo.contracts import CharacteristicRule, RawRow, RunSummary
from nimo.fetch import (
    Fetcher,
    ImageCache,
    default_image_cache,
    default_page_cache,
    fetch_image,
    load_fetch_config,
    resolve_image_url,
)
from nimo.llm import (
    LlmBudgetExceeded,
    LlmClient,
    LlmCounter,
    LlmImage,
    load_llm_config,
    load_prompt,
)
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
from nimo.run.runner import CacheCounter, RunPaths, Stages, offline_stages, run
from nimo.settings import settings

log = structlog.get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK = REPO_ROOT / "data" / "raw" / "product_truth_agent_dataset.xlsx"
CONFIG_DIR = REPO_ROOT / "config"
RETAILERS = CONFIG_DIR / "retailers.yaml"
REGISTRY_DIR = REPO_ROOT / "data" / "registry"
CACHE_DIR = REPO_ROOT / "data" / "cache"
OUT_DIR = REPO_ROOT / "data" / "out"


class PipelineConfigError(Exception):
    """A mode was requested that the environment cannot honour."""


@dataclass
class Pipeline:
    """The composed pipeline for one process: shared setup, per-sheet paths."""

    live: bool
    adjudicate: bool
    characteristics: bool
    out_dir: Path
    rules: list[CharacteristicRule]
    stages: Stages
    cache_counter: CacheCounter
    llm_counter: LlmCounter
    curve: IsotonicCurve | None
    tau_abstain: float
    searx: SearxngClient | None = None
    fetcher: Fetcher | None = None
    writer: RegistryWriter | None = None
    _closed: bool = field(default=False, repr=False)

    # --- construction ---------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        live: bool,
        adjudicate: bool = False,
        characteristics: bool = False,
        out_dir: Path = OUT_DIR,
    ) -> "Pipeline":
        if adjudicate and not live:
            raise PipelineConfigError("adjudication needs live mode: Tier 3 reads fetched pages")
        if (adjudicate or characteristics) and not settings.cis_llm_api_key:
            # `04` §9: validated present at startup, not at the first call.
            raise PipelineConfigError(
                "the model needs CIS_LLM_API_KEY in `.env` (see .env.example, config/models.yaml)"
            )

        # The classifier always fits on `dev` — the only sheet with MODULE
        # ground truth (`01` §6). Running over `qa` classifies with a
        # dev-fitted model, which is the intended direction.
        rules = load_characteristic_rules(WORKBOOK)
        dev_queries = normalize_rows(load_rows(WORKBOOK, "dev", RETAILERS))
        classifier = ModuleClassifier.fit(
            dev_queries, load_module_labels(WORKBOOK, "dev", rules), load_classify_config()
        )
        entities = read_entities(REGISTRY_DIR / "entities.jsonl")
        index = build_index(entities, fit_identity_idf(dev_queries))
        thresholds = load_thresholds()
        calibration = load_calibration_config()
        curve = read_curve(CURVE_PATH)
        cache_counter = CacheCounter()
        llm_counter = LlmCounter()

        llm: LlmClient | None = None
        if adjudicate or characteristics:
            # Imported here and only here: the SDK is the network
            # (`specs/adjudicate.md` §6).
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
        extractor = (
            CharacteristicExtractor(
                llm=llm,
                prompt=load_prompt("characteristics"),
                retry_prompt=load_prompt("characteristics_retry"),
                rules=rules,
                guidelines=guideline_index(load_characteristic_guidelines(WORKBOOK)),
                config=load_characteristics_config(),
            )
            if characteristics and llm is not None
            else None
        )

        if not live:
            stages = offline_stages(index, thresholds, classifier, rules, load_reason_config())
            if extractor is not None:
                record_only = extractor
                stages = replace(
                    stages,
                    characteristics=lambda query, module, evidence: record_only.extract(
                        query, module, None
                    ),
                    extracts_values=True,
                )
            return cls(
                live=False,
                adjudicate=False,
                characteristics=characteristics,
                out_dir=out_dir,
                rules=rules,
                stages=stages,
                cache_counter=cache_counter,
                llm_counter=llm_counter,
                curve=curve,
                tau_abstain=calibration.tau_abstain,
            )

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
        image_cache = default_image_cache(
            CACHE_DIR / "images",
            fcfg.cache_ttl_days,
            fcfg.failure_cache_ttl_hours,
            fcfg.cache_enabled,
        )
        if extractor is not None:
            extractor = replace(extractor, fetch_image=pack_shot_fetcher(fetcher, image_cache))
        writer = RegistryWriter(
            entities_path=REGISTRY_DIR / "entities.jsonl",
            audit_path=REGISTRY_DIR / "audit.jsonl",
            run_id="",  # set per run
            entities={entity.entity_id: entity for entity in entities},
        )
        adjudicator = (
            Adjudicator(llm=llm, prompt=load_prompt("adjudicate"), config=load_match_config())
            if adjudicate and llm is not None
            else None
        )
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
            cache_counter=cache_counter,
            rules=rules,
            reason_config=load_reason_config(),
            adjudicator=adjudicator,
            extractor=extractor,
            curve=curve,
            tau_abstain=calibration.tau_abstain,
        )
        return cls(
            live=True,
            adjudicate=adjudicate,
            characteristics=characteristics,
            out_dir=out_dir,
            rules=rules,
            stages=stages,
            cache_counter=cache_counter,
            llm_counter=llm_counter,
            curve=curve,
            tau_abstain=calibration.tau_abstain,
            searx=searx,
            fetcher=fetcher,
            writer=writer,
        )

    # --- running ------------------------------------------------------------------

    def paths_for(self, sheet: str) -> RunPaths:
        return RunPaths(
            artifacts=self.out_dir / "artifacts" / sheet,
            trace=self.out_dir / "trace.jsonl",
            failures=self.out_dir / "failures.jsonl",
            config_dir=CONFIG_DIR,
        )

    def run_rows(self, rows: list[RawRow], sheet: str, run_id: str) -> RunSummary:
        """Drive rows through the runner (resumable). A spent model budget
        aborts the run (`05` §3) rather than failing every remaining row."""
        if self.writer is not None:
            self.writer.run_id = run_id
        return run(
            rows,
            self.stages,
            self.paths_for(sheet),
            run_id,
            cache_counter=self.cache_counter,
            llm_counter=self.llm_counter,
            abort_on=(LlmBudgetExceeded,),
            rules=self.rules,
        )

    @property
    def registry_size(self) -> int:
        if self.writer is not None:
            return len(self.writer.entities)
        return len(read_entities(REGISTRY_DIR / "entities.jsonl"))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.searx is not None:
            self.searx.close()
        if self.fetcher is not None:
            self.fetcher.close()


def pack_shot_fetcher(fetcher: Fetcher, cache: ImageCache) -> ImageFetchFn:
    """The `ImageFetchFn` over `nimo.fetch.images`: the first candidate that
    fetches as an allowed image type, base64-encoded for the call. A page's
    `<img src>` may be relative; it is resolved against the page URL."""

    def first_usable(page_url: str, image_urls: list[str]) -> LlmImage | None:
        for raw in image_urls:
            outcome = fetch_image(fetcher, resolve_image_url(page_url, raw), cache)
            if outcome.status == "ok" and outcome.media_type is not None:
                digest = outcome.sha256
                assert digest is not None  # ok => bytes present
                return LlmImage(
                    media_type=outcome.media_type,
                    sha256=digest,
                    base64=base64.b64encode(outcome.data).decode("ascii"),
                )
            log.info(
                "pack_shot_unavailable",
                url=outcome.url,
                status=outcome.status,
                detail=outcome.detail,
            )
        return None

    return first_usable
