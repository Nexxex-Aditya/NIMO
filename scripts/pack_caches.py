"""Bundle `data/cache/{search,pages,llm,images}` into one zip for another
machine (the office laptop cannot search or fetch retailer pages itself).

    uv run python scripts/pack_caches.py [OUT.zip]

Written to a `.part` name and renamed on completion, so an interrupted build
never leaves a truncated file under the final name. On the other machine,
unzip at the repo root so the paths read `data/cache/search`, ... .
"""

import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBDIRS = ("search", "pages", "llm", "images")


def main(argv: list[str]) -> int:
    final = Path(argv[0]) if argv else ROOT.parent / f"nimo-cache-{time.strftime('%Y-%m-%d')}.zip"
    part = final.with_suffix(".zip.part")
    started = time.time()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for sub in SUBDIRS:
            count = 0
            for path in sorted((ROOT / "data" / "cache" / sub).rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(ROOT).as_posix())
                    count += 1
            counts[sub] = count
    part.replace(final)
    with zipfile.ZipFile(final) as bundle:
        bad = bundle.testzip()
        entries = len(bundle.namelist())
    print(
        f"{final}: {entries} files {counts}, {final.stat().st_size / 1e6:.0f} MB, "
        f"{time.time() - started:.0f}s, integrity {'OK' if bad is None else 'BAD: ' + bad}"
    )
    return 0 if bad is None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
