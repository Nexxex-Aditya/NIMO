"""P14 assembly — `specs/assemble.md`.

Public surface only.
"""

from nimo.assemble.assemble import (
    CONFIG_PATH,
    INPUT_COLUMNS,
    TEXT_COLUMNS,
    AssemblyError,
    AssemblyReport,
    OutputConfig,
    OutputConfigError,
    assemble_input_rows,
    assemble_rows,
    assembly_summary_json,
    format_report,
    load_output_config,
    to_csv_text,
    write_csv,
    write_xlsx,
)

__all__ = [
    "CONFIG_PATH",
    "INPUT_COLUMNS",
    "TEXT_COLUMNS",
    "AssemblyError",
    "AssemblyReport",
    "OutputConfig",
    "OutputConfigError",
    "assemble_input_rows",
    "assemble_rows",
    "assembly_summary_json",
    "format_report",
    "load_output_config",
    "to_csv_text",
    "write_csv",
    "write_xlsx",
]
