"""Loader exception taxonomy — `specs/loader.md`, "Error handling".

Small and specific on purpose. `04` §4 forbids reusing a bare `ValueError`
for everything: a caller that wants to distinguish "the source file changed
underneath us" from "this row references a retailer nobody mapped" needs
distinct types to catch.
"""


class LoaderError(Exception):
    """Base for every loader failure. Never raised directly."""


class DatasetDriftError(LoaderError):
    """A known fingerprint of the source workbook no longer holds.

    Raised when the file itself has changed shape or content in a way that
    invalidates `01-dataset-contract.md` — corruption count, column set,
    sheet set, row count. `05` §5 names silent input schema drift as a
    latent-failure mode; this is the loud failure that prevents it.
    """


class DatasetSchemaError(LoaderError):
    """The workbook's structure violates a contract stated in `01`.

    Distinct from drift: drift means "this changed", schema means "this was
    never valid" — a non-`ORAL HEALTH` category, an unparseable
    `possible_values` literal, a characteristic-name mapping that is not
    bijective.
    """


class RetailerNotMappedError(LoaderError):
    """A `RETAILER` value has no entry in `config/retailers.yaml`.

    Deliberately fatal rather than a fallback to the raw string
    (`specs/loader.md` §4): an unmapped retailer flowing through silently is
    the exact failure class that already cost 49 rows' worth of correct
    retailer names once, via a regex that matched the wrong substring
    (`01` §12, `05` §5).
    """
