"""Per-row, per-stage artifact storage — `specs/run.md` §3.

`03` §2: every stage writes its intermediate artifact to disk keyed by
`row_uid`. `03` §5: the runner processes by `row_uid`, skips completed rows,
survives interruption.
"""

import hashlib
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

# The stage sequence the runner drives today. Ordered, and a subset of
# `RowFailure.stage`'s Literal — the stages that do not exist yet are simply
# absent, so adding one later is adding a name here and a call in the runner.
STAGE_SEQUENCE: tuple[str, ...] = (
    "normalize",
    "registry",
    "retrieve",
    "fetch",
    "match",
    "classify",
    "characteristics",
)


def artifact_filename(row_uid: str) -> str:
    """`dev:0` -> `dev-0.json`.

    Sanitized for the **filename only**; the `row_uid` inside the file stays
    `dev:0`. `:` is not a legal filename character on Windows, which is the
    machine this project is built on — left unsanitized it surfaces as a
    mid-run crash rather than a design discussion.
    """
    return f"{row_uid.replace(':', '-')}.json"


def artifact_path(root: Path, stage: str, row_uid: str) -> Path:
    return root / stage / artifact_filename(row_uid)


def write_artifact(
    root: Path, stage: str, row_uid: str, model: BaseModel | list[BaseModel]
) -> Path:
    """Write one artifact atomically: temp file, then rename.

    A rename is atomic on POSIX and Windows alike, so a killed run leaves a
    file that either exists complete or does not exist. The alternative — one
    appended JSONL per stage — leaves a truncated final line on `SIGKILL`,
    and a resume path that has to guess whether that line is corruption or a
    partial write either loses good rows or resumes from bad ones
    (`specs/run.md` §3).
    """
    path = artifact_path(root, stage, row_uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            if isinstance(model, list):
                # A stage whose output is a list (candidates, evidence) is
                # written as a JSON array of contracts, not wrapped in a
                # container type that would have to be added to `03` §3.
                file.write("[" + ",".join(item.model_dump_json() for item in model) + "]")
            else:
                file.write(model.model_dump_json())
        os.replace(temp_name, path)
    finally:
        # `finally`, not `except ...: raise` — "always clean up the temp file"
        # is what is meant, and `04` §4 keeps broad excepts to the single
        # sanctioned site in the runner. After a successful `os.replace` the
        # temp name is already gone, so this is a no-op on the happy path.
        Path(temp_name).unlink(missing_ok=True)
    return path


def clear_artifacts(root: Path, row_uid: str, stages: tuple[str, ...] = STAGE_SEQUENCE) -> None:
    """Remove every artifact for one row.

    Used when a row fails partway: `04` §4's "never write a partial output
    row" applies to intermediate artifacts too, because a later stage reading
    a half-populated artifact set is how a plausible wrong answer gets built.
    """
    for stage in stages:
        artifact_path(root, stage, row_uid).unlink(missing_ok=True)


def is_row_complete(root: Path, row_uid: str, stages: tuple[str, ...] = STAGE_SEQUENCE) -> bool:
    """Whether every stage has an artifact for this row.

    A row with *some* artifacts is not complete and is re-run from the start —
    partial state is never trusted, because the run that produced it was
    interrupted for a reason nobody recorded.

    **Non-empty, not merely present.** A zero-byte artifact — a full disk, a
    kill between `mkstemp` and the write — would otherwise count as complete
    and be skipped on every future resume, permanently. `st_size` costs the
    same single `stat` call `exists()` already made. Full JSON parsing is
    deliberately not done here: it would mean reading ~1200 files on every
    resume to guard against a case atomic rename already makes very unlikely,
    and the reader raises loudly if one ever is malformed.
    """
    for stage in stages:
        path = artifact_path(root, stage, row_uid)
        if not path.exists() or path.stat().st_size == 0:
            return False
    return True


def completed_row_uids(root: Path, row_uids: list[str]) -> set[str]:
    return {row_uid for row_uid in row_uids if is_row_complete(root, row_uid)}


def config_hash(config_dir: Path) -> str:
    """`sha256` over the sorted contents of every file in `config/`.

    `05` §5's version-skew guardrail: "which config produced this output" has
    to be answerable after the fact. Hashes file *contents*, not mtimes — a
    checkout, a copy or a `git clone` changes mtimes without changing
    behavior, and a hash that moves when nothing meaningful changed teaches
    people to ignore it.
    """
    digest = hashlib.sha256()
    for path in sorted(config_dir.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(config_dir).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()[:16]}"
