"""P6a batch runner & orchestration — `specs/run.md`.

Public surface only.
"""

from nimo.run.artifacts import (
    STAGE_SEQUENCE,
    artifact_filename,
    artifact_path,
    clear_artifacts,
    completed_row_uids,
    config_hash,
    is_row_complete,
    write_artifact,
)
from nimo.run.runner import (
    CacheCounter,
    RowArtifacts,
    RunPaths,
    Stages,
    format_summary,
    offline_stages,
    process_row,
    run,
)

__all__ = [
    "STAGE_SEQUENCE",
    "RowArtifacts",
    "CacheCounter",
    "RunPaths",
    "Stages",
    "artifact_filename",
    "artifact_path",
    "clear_artifacts",
    "completed_row_uids",
    "config_hash",
    "offline_stages",
    "format_summary",
    "is_row_complete",
    "process_row",
    "run",
    "write_artifact",
]
