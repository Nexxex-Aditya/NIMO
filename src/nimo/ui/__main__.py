"""`uv run python -m nimo.ui [--live] [--characteristics] [--adjudicate] [--port 8765]`

The interactive interface (P16, `specs/ui.md`): a local web page over the
same pipeline the CLI runs. Binds to 127.0.0.1 — a single-user demo, not a
service (`04` non-goals). Artifacts go under `data/out/ui/` so the
submission tree is never touched.

`print` is the CLI's user-facing output (`04` §10).
"""

import sys

import uvicorn

from nimo.run.compose import OUT_DIR, Pipeline, PipelineConfigError
from nimo.ui.app import create_app
from nimo.ui.service import UiService


def main(argv: list[str]) -> int:
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8765
    live = "--live" in argv
    try:
        pipeline = Pipeline.create(
            live=live,
            adjudicate="--adjudicate" in argv,
            characteristics="--characteristics" in argv,
            out_dir=OUT_DIR / "ui",
        )
    except PipelineConfigError as error:
        print(str(error))
        return 2
    service = UiService.create(pipeline)
    print(f"NIMO UI: http://127.0.0.1:{port}  mode={'LIVE' if live else 'OFFLINE'}")
    if not live:
        print("offline: retrieval/fetch/match are empty; pass --live for the real thing")
    try:
        uvicorn.run(create_app(service), host="127.0.0.1", port=port, log_level="warning")
    finally:
        pipeline.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
