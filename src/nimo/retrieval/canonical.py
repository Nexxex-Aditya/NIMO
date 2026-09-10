"""URL canonicalization and the candidate safety gate — `specs/retrieval.md` §3, §4.

Pure. No I/O, no DNS, no network — hostname resolution and post-redirect
re-validation are P8's, because they need the HTTP client's redirect chain.
"""

import ipaddress
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Tracking and session parameters, dropped so two URLs differing only by
# provenance dedup to one candidate.
#
# What is deliberately NOT here: every other query parameter. On real retailer
# sites `?variant=`, `?sku=` and `?size=` are the difference between two
# products, so stripping unknown parameters would merge a 75ml and a 100ml
# listing into a single candidate — the exact identity error the whole matcher
# exists to avoid (`specs/retrieval.md` §3).
_TRACKING_PARAMS = frozenset(
    {
        "gclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "ref",
        "referrer",
        "sessionid",
        "session_id",
        "sid",
        "phpsessid",
        "jsessionid",
    }
)

_DEFAULT_PORTS = {"http": "80", "https": "443"}

# NFKC is necessary but NOT sufficient, which was found by testing rather than
# assumed: `unicodedata.normalize("NFKC", "‑")` yields `‐` (HYPHEN),
# not ASCII `-`. The whole U+2010..U+2015 range, U+2212 MINUS SIGN and U+00AD
# SOFT HYPHEN all survive NFKC as non-ASCII, so a URL containing the `U+2011`
# that `01` §13 found in `sample_output` would still resolve nowhere after
# normalization alone.
_DASH_FOLD = str.maketrans(
    {
        "‐": "-",  # HYPHEN
        "‑": "-",  # NON-BREAKING HYPHEN — the one `01` §13 actually found
        "‒": "-",  # FIGURE DASH
        "–": "-",  # EN DASH
        "—": "-",  # EM DASH
        "―": "-",  # HORIZONTAL BAR
        "−": "-",  # MINUS SIGN
        # Invisible formatting characters are DELETED, not folded: they carry
        # no meaning in a URL and survive copy-paste from rendered pages.
        "­": None,  # SOFT HYPHEN
        "​": None,  # ZERO WIDTH SPACE
        "‌": None,  # ZERO WIDTH NON-JOINER
        "‍": None,  # ZERO WIDTH JOINER
        "﻿": None,  # ZERO WIDTH NO-BREAK SPACE / BOM
    }
)


class UrlError(Exception):
    """A URL cannot be canonicalized or is not safe to carry forward."""


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("utm_") or lowered in _TRACKING_PARAMS


def canonicalize(url: str) -> str:
    """Canonical form of a candidate URL. Raises `UrlError` if unusable.

    Order matters and is stated in `specs/retrieval.md` §3. Normalization
    comes first because `01` §13 found a `U+2011` non-breaking hyphen in
    `sample_output`'s `PRODUCT_URL`: treated as a literal character it
    produces a URL that resolves nowhere and dedups against nothing. NFKC
    alone does not fix it — see `_DASH_FOLD`.
    """
    normalized = unicodedata.normalize("NFKC", url.strip()).translate(_DASH_FOLD)
    if not normalized:
        raise UrlError("empty URL")

    parts = urlsplit(normalized)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlError(
            f"scheme {scheme!r} is not http(s) — `05` §2 rejects file://, ftp://, data: and "
            f"anything else outright, before a fetcher ever sees it"
        )
    if not parts.hostname:
        raise UrlError(f"no host in {url!r}")

    host = parts.hostname.lower().removeprefix("www.")
    port = parts.port
    netloc = host if port is None or str(port) == _DEFAULT_PORTS[scheme] else f"{host}:{port}"

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    kept = sorted(
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking(name)
    )
    return urlunsplit((scheme, netloc, path, urlencode(kept), ""))


def is_private_host(host: str) -> bool:
    """Whether `host` is an IP literal in a private or reserved range.

    **Scoped to untrusted candidate URLs from search results — never a global
    outbound check.** The CIS LLM endpoint is itself an RFC1918 address
    (`10.249.224.116`, `config/models.yaml`), so a guard applied to all
    outbound traffic would block the pipeline's own model with a timeout whose
    cause is not remotely obvious from the symptom (`02-decision-log.md`).

    Only IP *literals* are judged here. A hostname that resolves to a private
    address is P8's problem: doing DNS at query time would mean resolving every
    candidate before deciding whether to fetch it.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def is_safe_candidate(url: str) -> bool:
    """The cheap front gate: can this candidate enter the pipeline at all?

    P8 re-validates after every redirect hop (`05` §2) — a page can 302 to an
    internal address, and checking only the original URL defeats the control.
    """
    try:
        canonical = canonicalize(url)
    except UrlError:
        return False
    host = urlsplit(canonical).hostname
    return host is not None and not is_private_host(host)
