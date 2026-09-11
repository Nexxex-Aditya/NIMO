"""The CIS Azure AI Inference adapter — the only network code in `llm/`.

**Not exercised by any test, and not yet verified live** (`specs/adjudicate.md`
§0): the endpoint resolves to an RFC1918 address and is reachable only on the
NIQ network. Everything that decides is elsewhere and tested; this file turns
an `LlmCall` into one `ChatCompletionsClient.complete(...)` call and reads the
answer back, following `config/models.yaml`'s recorded auth pattern verbatim.

What was verified against the installed SDK (1.0.0b9, ships `py.typed`)
rather than written from memory: `api_version`, `headers`,
`connection_timeout` and `read_timeout` are accepted constructor keywords;
`complete()` returns `ChatCompletions | Iterable[StreamingChatCompletionsUpdate]`
and must be narrowed; the SDK's own patch already sends an
`AzureKeyCredential` as `Authorization: Bearer <key>`, which makes the
notebook's explicit header redundant — kept anyway, per the note in
`config/models.yaml`, until a live call proves the simpler form works.
"""

from collections.abc import Mapping
from typing import Any

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import (
    ChatCompletions,
    CompletionsFinishReason,
    SystemMessage,
    UserMessage,
)
from azure.core.credentials import AzureKeyCredential

from nimo.llm.client import CompleteFn, LlmCall, LlmError, LlmResponse, LlmTruncated
from nimo.llm.config import LlmConfig


def azure_complete_fn(config: LlmConfig, api_key: str) -> CompleteFn:
    """Build the `CompleteFn` for the pinned CIS model.

    The key is used here and nowhere else: never logged, never cached, never
    in a prompt (`05` §3). `05` §2's SSRF guard is deliberately NOT applied
    to this configured, trusted endpoint (decision log 2026-09-10).
    """
    if not api_key.strip():
        raise LlmError("CIS_LLM_API_KEY is empty — set it in `.env` (`04` §9)")
    client = ChatCompletionsClient(
        endpoint=config.endpoint,
        credential=AzureKeyCredential(api_key),
        # The onboarding notebook passes the key both ways; see the module
        # docstring and `config/models.yaml` before simplifying.
        headers={"Authorization": f"Bearer {api_key}"},
        api_version=config.api_version,
        connection_timeout=config.request_timeout_s,
        read_timeout=config.request_timeout_s,
    )

    def complete(call: LlmCall) -> LlmResponse:
        # `temperature` is sent only when configured (the pinned model rejects
        # 0 — measured); the output cap goes under whichever field the
        # gateway accepts (`config/models.yaml`).
        extras: dict[str, Any] = {}
        model_extras: dict[str, Any] = {}
        if call.temperature is not None:
            extras["temperature"] = call.temperature
        if config.max_tokens_param == "max_tokens":
            extras["max_tokens"] = call.max_tokens
        else:
            model_extras["max_completion_tokens"] = call.max_tokens
        if config.reasoning_effort is not None:
            model_extras["reasoning_effort"] = config.reasoning_effort
        if model_extras:
            extras["model_extras"] = model_extras
        response = client.complete(
            messages=[SystemMessage(call.system), UserMessage(call.user)],
            model=call.model,
            response_format="json_object",
            **extras,
        )
        if not isinstance(response, ChatCompletions):
            raise LlmError("streaming response received; the client never asks for one")
        return read_response(response, call)

    return complete


def read_response(response: ChatCompletions, call: LlmCall) -> LlmResponse:
    """Turn the SDK's answer into an `LlmResponse`, or a typed error.

    Pure, so it is tested against constructed `ChatCompletions` objects
    (`04` §6) even though the network call around it is not. Measured
    2026-09-12: the pinned model's reasoning tokens count against
    `max_tokens`, so a cap hit is not "an answer that did not validate" — it
    is an incomplete answer, and retrying it identically is a wasted call.
    """
    if not response.choices:
        raise LlmError("the model returned no choices")
    choice = response.choices[0]
    usage = response.usage
    reasoning = _reasoning_tokens(usage)
    spent = int(usage.completion_tokens)
    if choice.finish_reason == CompletionsFinishReason.TOKEN_LIMIT_REACHED:
        hidden = f", {reasoning} of them hidden reasoning" if reasoning is not None else ""
        raise LlmTruncated(
            f"output cap of {call.max_tokens} tokens reached before the answer was complete "
            f"({spent} completion tokens spent{hidden}). The pinned model reasons before it "
            f"writes and the reasoning counts against the cap: raise `llm_max_output_tokens` "
            f"or set `llm_reasoning_effort` in `config/models.yaml`."
        )
    if choice.finish_reason == CompletionsFinishReason.CONTENT_FILTERED:
        raise LlmError(
            "the gateway's content filter withheld the answer (finish_reason=content_filter)"
        )
    content = choice.message.content
    return LlmResponse(
        text=content if isinstance(content, str) else "",
        prompt_tokens=int(usage.prompt_tokens),
        completion_tokens=spent,
        from_cache=False,
        reasoning_tokens=reasoning,
    )


def _reasoning_tokens(usage: Mapping[str, Any]) -> int | None:
    """`completion_tokens_details.reasoning_tokens` when the gateway reports
    it. The SDK's `CompletionsUsage` types only the three standard counts but
    keeps every key it was sent (verified against 1.0.0b9)."""
    details = usage.get("completion_tokens_details")
    if not isinstance(details, Mapping):
        return None
    value = details.get("reasoning_tokens")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
