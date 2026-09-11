"""`uv run python -m nimo.llm --ping` — one live call to the pinned CIS model.

The first thing to run on the NIQ network (`specs/adjudicate.md` §0): the
Azure adapter is the only code in the repo that has never executed against
its endpoint. This asks the model for a two-field JSON object, validates it
through the same `complete_json` path the pipeline uses, and prints what came
back with token counts. No cache, so it always makes the call.

`print` is the CLI's user-facing output (`04` §10). The key is read from
`.env` and never printed.
"""

import socket
import sys
from urllib.parse import urlsplit

from pydantic import BaseModel

from nimo.llm.client import LlmCall, LlmClient, LlmError
from nimo.llm.config import load_llm_config
from nimo.settings import settings


class _Pong(BaseModel):
    ok: bool
    model_seen: str


def main(argv: list[str]) -> int:
    if "--ping" not in argv:
        print("usage: uv run python -m nimo.llm --ping")
        return 2
    config = load_llm_config()
    host = urlsplit(config.endpoint).hostname or config.endpoint
    print(f"model    : {config.model}")
    print(f"endpoint : {config.endpoint}")
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, 443)})
        print(f"resolves : {addresses}")
    except OSError as error:
        print(f"resolves : FAILED ({error}) — not on the NIQ network?")
        return 1
    if not settings.cis_llm_api_key:
        print("key      : CIS_LLM_API_KEY is missing from .env")
        return 1
    print("key      : present")

    from azure.core.exceptions import AzureError

    from nimo.llm.azure import azure_complete_fn

    client = LlmClient(
        config=config,
        complete=azure_complete_fn(config, settings.cis_llm_api_key),
        cache_dir=None,
    )
    call = LlmCall(
        model=config.model,
        system="You answer with a single JSON object and nothing else.",
        user='Reply with exactly {"ok": true, "model_seen": "<the model name you are>"}.',
        temperature=config.temperature,
        # The configured cap, not a token-pinching one: measured 2026-09-12,
        # a 64-token cap was consumed entirely by hidden reasoning.
        max_tokens=config.max_output_tokens,
        prompt_hash="ping",
    )
    try:
        pong = client.complete_json(call, _Pong)
    except (LlmError, AzureError) as error:
        print(f"call     : FAILED — {type(error).__name__}: {error}")
        return 1
    print(f"call     : OK  ok={pong.ok}  model_seen={pong.model_seen!r}")
    print(
        f"tokens   : prompt {client.counter.prompt_tokens}, "
        f"completion {client.counter.completion_tokens} "
        f"(the `llm_call` log line above shows the hidden reasoning share, if reported; "
        f"size `llm_max_output_tokens` from it)"
    )
    print("The adapter works on this network. Next: the dev gate (docs/06-office-runbook.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
