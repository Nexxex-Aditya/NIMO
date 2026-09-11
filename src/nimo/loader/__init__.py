"""P2 dataset loader — `specs/loader.md`.

Public surface only. `specs/contracts.md`'s rule applies here too: don't build
an API wider than later phases actually import.
"""

from nimo.loader.dataset import (
    applicable_characteristics,
    assert_guideline_modules_subset,
    characteristic_rule,
    load_characteristic_guidelines,
    load_characteristic_rules,
    load_module_labels,
    load_qa_header,
    load_rows,
    read_external_codes,
    read_header,
)
from nimo.loader.errors import (
    DatasetDriftError,
    DatasetSchemaError,
    LoaderError,
    RetailerNotMappedError,
)
from nimo.loader.fields import (
    barcode_valid,
    collapse_whitespace,
    normalize_characteristic_name,
    parse_barcode,
    parse_brand,
    parse_countries,
    repair_encoding,
)

__all__ = [
    "DatasetDriftError",
    "DatasetSchemaError",
    "LoaderError",
    "RetailerNotMappedError",
    "applicable_characteristics",
    "assert_guideline_modules_subset",
    "barcode_valid",
    "characteristic_rule",
    "collapse_whitespace",
    "load_characteristic_guidelines",
    "load_characteristic_rules",
    "load_module_labels",
    "load_qa_header",
    "load_rows",
    "read_external_codes",
    "normalize_characteristic_name",
    "parse_barcode",
    "parse_brand",
    "parse_countries",
    "read_header",
    "repair_encoding",
]
