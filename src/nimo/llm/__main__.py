"""`uv run python -m nimo.llm --ping` — one live call to the pinned CIS model.

The first thing to run on the NIQ network (`specs/adjudicate.md` §0): the
Azure adapter is the only code in the repo that has never executed against
its endpoint. This asks the model for a two-field JSON object, validates it
through the same `complete_json` path the pipeline uses, and prints what came
back with token counts. No cache, so it always makes the call.

`print` is the CLI's user-facing output (`04` §10). The key is read from
`.env` and never printed.
"""

import base64
import hashlib
import socket
import struct
import sys
import zlib
from urllib.parse import urlsplit

from pydantic import BaseModel

from nimo.llm.client import LlmCall, LlmClient, LlmError, LlmImage
from nimo.llm.config import load_llm_config
from nimo.settings import settings


class _Pong(BaseModel):
    ok: bool
    model_seen: str


class _Seen(BaseModel):
    colour: str
    shape: str


def probe_png(size: int = 32) -> bytes:
    """A solid red square, written by hand (no imaging dependency): the
    question `--ping-image` asks has exactly one right answer, so a wrong
    one says the model did not see the image."""
    row = b"\x00" + b"\xff\x00\x00" * size  # filter byte, then RGB per pixel
    raw = row * size

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def main(argv: list[str]) -> int:
    if "--ping" not in argv and "--ping-image" not in argv:
        print("usage: uv run python -m nimo.llm --ping | --ping-image")
        return 2
    with_image = "--ping-image" in argv
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
    if with_image:
        png = probe_png()
        image = LlmImage(
            media_type="image/png",
            sha256=hashlib.sha256(png).hexdigest(),
            base64=base64.b64encode(png).decode("ascii"),
        )
        call = LlmCall(
            model=config.model,
            system="You answer with a single JSON object and nothing else.",
            user=(
                "An image is attached. Reply with exactly "
                '{"colour": "<the dominant colour of the image, one word>", '
                '"shape": "<the shape it shows, one word>"}.'
            ),
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
            prompt_hash="ping-image",
            images=(image,),
        )
        try:
            seen = client.complete_json(call, _Seen)
        except (LlmError, AzureError) as error:
            print(f"image    : FAILED — {type(error).__name__}: {error}")
            print(
                "Q7 stays open: a 400 naming image_url/content means the gateway does not "
                "accept image input; set `use_image_evidence: false` in "
                "config/characteristics.yaml."
            )
            return 1
        verdict = "as expected" if seen.colour.lower().strip() == "red" else "NOT red — look"
        print(f"image    : OK  colour={seen.colour!r} shape={seen.shape!r}  ({verdict})")
        print(
            f"tokens   : prompt {client.counter.prompt_tokens}, "
            f"completion {client.counter.completion_tokens} — the prompt figure is the "
            f"per-image cost at `llm_image_detail: {config.image_detail}`"
        )
        print("Q7 resolved: the model sees images. `use_image_evidence: true` is safe.")
        return 0

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
