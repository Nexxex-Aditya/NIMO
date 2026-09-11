"""The LLM client — `04` §7, `05` §3, `specs/adjudicate.md` §6.

**The network lives behind an injected `CompleteFn`**, the same seam
`retrieval/` uses for search: every rule here — cache-first, the per-run
budget, JSON validation with one retry — is exercised in tests against frozen
responses, with the Azure adapter (`llm/azure.py`) never constructed.

`04` §5 asks for `temperature=0` and a cache keyed by
`sha256(model + prompt + params)`. The pinned CIS model rejects temperature 0
(measured 2026-09-12: HTTP 400, "only the default (1) value is supported"),
so the parameter is omitted for it and determinism rests on the cache: a
re-run against a warm cache issues no call and returns byte-identical text.

`05` §3: a hard per-run budget. On breach the client raises **before** the
call is made — abort, never throttle-and-continue, because an overrun usually
means pathological retries or runaway re-processing, which is a bug to
surface rather than paper over.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from nimo.llm.config import LlmConfig
from nimo.llm.prompts import PromptTemplate, render

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class LlmError(Exception):
    """The model could not be called, or its answer could not be used."""


class LlmBudgetExceeded(LlmError):
    """`05` §3: the per-run call or token budget is spent. The run aborts."""


class LlmValidationError(LlmError):
    """The answer did not validate against the schema, twice (`04` §7)."""


class LlmTruncated(LlmError):
    """The output cap was hit before the answer was complete. Measured
    2026-09-12: the pinned model reasons before it writes, and its reasoning
    tokens count against `max_tokens`, so a tight cap yields EMPTY content
    with `finish_reason="length"`. Raised, never retried — a second identical
    call truncates identically. The fix is `llm_max_output_tokens` or
    `llm_reasoning_effort` in `config/models.yaml`."""


@dataclass(frozen=True)
class LlmImage:
    """One image attached to a call, already base64 — a pack shot fetched
    through `nimo.fetch.images`. `sha256` is what the cache key and the
    artifacts carry; the data itself is never written to the cache entry."""

    media_type: str  # image/jpeg, image/png, ... (`config/fetch.yaml` image_types)
    sha256: str
    base64: str

    @property
    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.base64}"


@dataclass(frozen=True)
class LlmCall:
    """Everything that determines an answer — and therefore the cache key."""

    model: str
    system: str
    user: str
    temperature: float | None  # None == not sent (the pinned model rejects 0; measured)
    max_tokens: int
    prompt_hash: str  # `05` §5 — the prompt file's version, recorded with the answer
    images: tuple[LlmImage, ...] = ()  # `03` §4 stage 6 step 5; `05` §3 image inputs


@dataclass(frozen=True)
class LlmResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int  # INCLUDES hidden reasoning tokens on a reasoning model
    from_cache: bool
    reasoning_tokens: int | None = None  # the hidden share, when the gateway reports it


# The injected network seam. `llm/azure.py` provides the real one.
CompleteFn = Callable[[LlmCall], LlmResponse]


@dataclass
class LlmCounter:
    """Per-run tally for `RunSummary.llm_calls` / `llm_tokens` (`04` §10)."""

    calls: int = 0  # calls actually made — cache hits are not calls
    cache_hits: int = 0
    prompt_tokens: int = 0  # includes cached answers' tokens, for transparency
    completion_tokens: int = 0
    rejected_verdicts: int = 0  # answers the schema or range check refused

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def cache_key(call: LlmCall) -> str:
    """`04` §5: `sha256(model + prompt + params)`. The prompt hash is not part
    of the key — the rendered prompt already is, byte for byte."""
    material = json.dumps(
        {
            "model": call.model,
            "system": call.system,
            "user": call.user,
            "temperature": call.temperature,
            "max_tokens": call.max_tokens,
            "images": [image.sha256 for image in call.images],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class LlmClient:
    config: LlmConfig
    complete: CompleteFn
    cache_dir: Path | None
    counter: LlmCounter = field(default_factory=LlmCounter)
    retry_prompt: PromptTemplate | None = None

    def call(self, call: LlmCall) -> LlmResponse:
        """Cache-first; budget-checked before the network; counted."""
        key = cache_key(call)
        cached = self._read_cache(key)
        if cached is not None:
            self.counter.cache_hits += 1
            self.counter.prompt_tokens += cached.prompt_tokens
            self.counter.completion_tokens += cached.completion_tokens
            return cached

        self._assert_budget()
        response = self.complete(call)
        self.counter.calls += 1
        self.counter.prompt_tokens += response.prompt_tokens
        self.counter.completion_tokens += response.completion_tokens
        self._write_cache(key, call, response)
        log.info(
            "llm_call",
            model=call.model,
            prompt_hash=call.prompt_hash[:12],
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            reasoning_tokens=response.reasoning_tokens,
        )
        return response

    def complete_json(self, call: LlmCall, model_type: type[T]) -> T:
        """`04` §7: schema-validated, one retry with the error appended, then
        a typed failure. Never free text into a data field."""
        first = self.call(call)
        try:
            return model_type.model_validate_json(_strip_fences(first.text))
        except ValidationError as error:
            if self.retry_prompt is None:
                raise LlmValidationError(
                    f"answer did not validate and no retry prompt is configured: {error}"
                ) from error
            log.warning("llm_answer_invalid_retrying", model=call.model, error=str(error)[:300])
            retry = LlmCall(
                model=call.model,
                system=call.system,
                user=call.user
                + "\n\n"
                + render(self.retry_prompt.user_template, validation_error=str(error)),
                temperature=call.temperature,
                max_tokens=call.max_tokens,
                prompt_hash=call.prompt_hash,
                images=call.images,
            )
            second = self.call(retry)
            try:
                return model_type.model_validate_json(_strip_fences(second.text))
            except ValidationError as second_error:
                raise LlmValidationError(
                    f"answer did not validate after one retry (`04` §7): {second_error}"
                ) from second_error

    # --- budget -------------------------------------------------------------

    def _assert_budget(self) -> None:
        if self.counter.calls >= self.config.max_calls_per_run:
            raise LlmBudgetExceeded(
                f"{self.counter.calls} calls made; `llm_max_calls_per_run` is "
                f"{self.config.max_calls_per_run}. Aborting (`05` §3): an overrun usually "
                f"means pathological retries or runaway re-processing."
            )
        if self.counter.tokens >= self.config.max_tokens_per_run:
            raise LlmBudgetExceeded(
                f"{self.counter.tokens} tokens used; `llm_max_tokens_per_run` is "
                f"{self.config.max_tokens_per_run}. Aborting (`05` §3)."
            )

    # --- cache --------------------------------------------------------------

    def _path(self, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / key[:2] / f"{key}.json"

    def _read_cache(self, key: str) -> LlmResponse | None:
        path = self._path(key)
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise LlmError(
                f"{path} is not readable as an LLM cache entry: {error}. Delete it to re-ask; "
                f"a cache that quietly drops entries looks identical to one that works (`04` §4)."
            ) from error
        reasoning = payload.get("reasoning_tokens")
        return LlmResponse(
            text=str(payload["text"]),
            prompt_tokens=int(payload["prompt_tokens"]),
            completion_tokens=int(payload["completion_tokens"]),
            from_cache=True,
            reasoning_tokens=None if reasoning is None else int(reasoning),
        )

    def _write_cache(self, key: str, call: LlmCall, response: LlmResponse) -> None:
        path = self._path(key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        # Inspectable (`04` §6): the prompt sits beside the answer so a
        # surprising verdict can be read back. No secret is ever in a prompt
        # (`05` §3), so nothing here needs redacting.
        path.write_text(
            json.dumps(
                {
                    "model": call.model,
                    "prompt_hash": call.prompt_hash,
                    "temperature": call.temperature,
                    "max_tokens": call.max_tokens,
                    "images": [
                        {"media_type": image.media_type, "sha256": image.sha256}
                        for image in call.images
                    ],
                    "system": call.system,
                    "user": call.user,
                    "text": response.text,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "reasoning_tokens": response.reasoning_tokens,
                },
                indent=1,
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def _strip_fences(text: str) -> str:
    """A model asked for JSON sometimes wraps it in a ```json fence. Strip
    exactly that; anything else still has to validate."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        stripped = stripped[first_newline + 1 :] if first_newline >= 0 else ""
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()
