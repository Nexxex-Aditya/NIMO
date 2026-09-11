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

from typing import Any

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import ChatCompletions, SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from nimo.llm.client import CompleteFn, LlmCall, LlmError, LlmResponse
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
        if call.temperature is not None:
            extras["temperature"] = call.temperature
        if config.max_tokens_param == "max_tokens":
            extras["max_tokens"] = call.max_tokens
        else:
            extras["model_extras"] = {"max_completion_tokens": call.max_tokens}
        response = client.complete(
            messages=[SystemMessage(call.system), UserMessage(call.user)],
            model=call.model,
            response_format="json_object",
            **extras,
        )
        if not isinstance(response, ChatCompletions):
            raise LlmError("streaming response received; the client never asks for one")
        if not response.choices:
            raise LlmError("the model returned no choices")
        content = response.choices[0].message.content
        usage = response.usage
        return LlmResponse(
            text=content if isinstance(content, str) else "",
            prompt_tokens=int(usage.prompt_tokens),
            completion_tokens=int(usage.completion_tokens),
            from_cache=False,
        )

    return complete
