"""P8 fetch — `specs/fetch.md`.

Currently the SSRF guard only. The fetch client (robots.txt, per-domain rate
limiting, content-addressed page cache, manual per-hop redirect handling) is
the remaining half of P8 — see `specs/fetch.md` §2-§4 and `04` §1's P7a row.
"""

from nimo.fetch.guard import (
    ALLOWED_SCHEMES,
    UnsafeUrlError,
    assert_safe_url,
    is_forbidden_address,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "UnsafeUrlError",
    "assert_safe_url",
    "is_forbidden_address",
]
