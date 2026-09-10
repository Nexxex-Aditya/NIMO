"""The hand-adjudicated blocked-pair set — `specs/registry.md` §4b.

`data/gold/pairs.jsonl` is P6's measurement instrument, the same role
`data/gold/urls.jsonl` plays for P9/P10. `03` §4 stage 1 says `tau_ann` must
be *tuned, not hand-picked*, and there was nothing to tune it against until
these 20 pairs were read in full and labelled.

Fail-loud on a malformed line, for the reason `specs/gold.md` gives about the
URL set: this file is the thing that measures everything else, so a silently
skipped entry moves a threshold with no error anywhere.
"""

from pathlib import Path

from nimo.contracts import GoldPair


class GoldPairError(Exception):
    """`data/gold/pairs.jsonl` is missing or malformed."""


def load_gold_pairs(path: Path) -> list[GoldPair]:
    """Read the adjudicated pair set, in file order."""
    if not path.exists():
        raise GoldPairError(f"{path} not found — `specs/registry.md` §4b requires it")

    pairs: list[GoldPair] = []
    seen: set[tuple[str, str]] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            pair = GoldPair.model_validate_json(line)
        except ValueError as error:
            raise GoldPairError(f"{path}:{number} is not a valid GoldPair: {error}") from error
        identity = (pair.left_row_uid, pair.right_row_uid)
        if identity in seen:
            raise GoldPairError(
                f"{path}:{number} repeats the pair {identity}. A duplicated pair silently "
                f"double-weights one adjudication when tuning a threshold against this file."
            )
        if pair.left_row_uid == pair.right_row_uid:
            raise GoldPairError(f"{path}:{number} pairs a row with itself: {identity}")
        seen.add(identity)
        pairs.append(pair)

    if not pairs:
        raise GoldPairError(f"{path} is empty — an empty instrument measures nothing")
    return pairs
