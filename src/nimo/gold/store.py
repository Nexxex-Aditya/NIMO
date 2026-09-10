"""Read and write `data/gold/urls.jsonl` — `specs/gold.md`.

Fails loud on a malformed line rather than skipping it (`04` §4). A silently
skipped gold entry would shrink the measurement set with no error, which is
the same class of problem as a fabricated one: it corrupts the instrument
instead of the answer.
"""

from pathlib import Path

from pydantic import ValidationError

from nimo.contracts import GoldUrl

GOLD_PATH = Path(__file__).resolve().parents[3] / "data" / "gold" / "urls.jsonl"
SAMPLE_PATH = Path(__file__).resolve().parents[3] / "data" / "gold" / "sample.txt"

_VALID_SCHEMES = ("http://", "https://")


class GoldSetError(Exception):
    """`data/gold/urls.jsonl` is malformed or violates a `specs/gold.md` rule."""


def _check_label_url_consistency(entry: GoldUrl, line_number: int) -> None:
    """`specs/gold.md` acceptance criterion 4.

    The two halves of the rule are equally important: a `correct` label with
    no URL is a lost label, and a URL under any other label is an unverified
    URL leaking into the measurement set.
    """
    if entry.label == "correct":
        if not entry.url or not entry.url.startswith(_VALID_SCHEMES):
            raise GoldSetError(
                f"line {line_number}: label 'correct' requires an http(s) url, got "
                f"{entry.url!r} (nan_key={entry.nan_key})"
            )
    elif entry.url is not None:
        raise GoldSetError(
            f"line {line_number}: label {entry.label!r} must have url=None, got "
            f"{entry.url!r} (nan_key={entry.nan_key}). A URL under a non-correct "
            f"label is an unverified URL in the measurement set."
        )
    if not entry.evidence.strip():
        raise GoldSetError(
            f"line {line_number}: empty evidence (nan_key={entry.nan_key}). "
            f"specs/gold.md requires what was actually checked on the page."
        )


def load_gold(path: Path = GOLD_PATH) -> list[GoldUrl]:
    """Parse the whole file, or raise. Never partially succeeds."""
    if not path.exists():
        raise GoldSetError(f"{path} not found — P4 produces it (specs/gold.md)")

    entries: list[GoldUrl] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            entry = GoldUrl.model_validate_json(stripped)
        except ValidationError as exc:
            raise GoldSetError(f"{path} line {line_number} is not a valid GoldUrl: {exc}") from exc
        _check_label_url_consistency(entry, line_number)
        if entry.row_uid in seen:
            raise GoldSetError(
                f"{path} line {line_number}: row_uid {entry.row_uid!r} appears twice. "
                f"One label per row (specs/gold.md acceptance criterion 3). Keyed on "
                f"row_uid, not nan_key — the latter collides (`01` §14)."
            )
        seen.add(entry.row_uid)
        entries.append(entry)
    return entries


def write_gold(entries: list[GoldUrl], path: Path = GOLD_PATH) -> None:
    """Write sorted by `(sheet, row_uid)` so the file is diffable and stable."""
    ordered = sorted(entries, key=lambda entry: (entry.sheet, entry.row_uid))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(f"{entry.model_dump_json()}\n" for entry in ordered)
    path.write_text(payload, encoding="utf-8")


def labelled_correct(entries: list[GoldUrl]) -> list[GoldUrl]:
    """The subset that carries a verified URL — what L3 precision scores on."""
    return [entry for entry in entries if entry.label == "correct"]


def load_frozen_sample(path: Path = SAMPLE_PATH) -> list[str]:
    """The committed stratified sample — `specs/gold.md`.

    Frozen rather than recomputed on demand: labels are written against a
    specific sample, and a sampler change that silently re-bases it would
    invalidate them without any error. A test asserts this file still equals
    the sampler's output.
    """
    if not path.exists():
        raise GoldSetError(f"{path} not found — P4 produces it (specs/gold.md)")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
