"""SSRF controls for the fetcher — `05` §2, `specs/fetch.md` §2.

**This phase owns `05` §2.** P7 dropped candidates whose host was a private IP
*literal*; everything that needs DNS or the redirect chain lives here, because
resolving every candidate at query time would mean resolving pages we never
fetch.

**Scoped to untrusted candidate URLs, never a global outbound check.** The CIS
LLM endpoint is itself an RFC1918 address (`10.249.224.116`,
`config/models.yaml`), so a guard applied to all outbound traffic would block
the pipeline's own model with a timeout whose cause is not remotely obvious
from the symptom. This module takes a candidate URL and nothing else.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeUrlError(Exception):
    """A URL must not be fetched. Carries why, for the trace."""


def _addresses(host: str) -> list[str]:
    """Every address `host` resolves to.

    **Every** address, not the first: a hostname can resolve to one public and
    one private address, and a guard that checks only the first is trivially
    bypassed by ordering. `getaddrinfo` is also what the HTTP client will use,
    so this checks the same answer the connection would get.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise UnsafeUrlError(f"{host!r} does not resolve: {error}") from error
    return sorted({str(info[4][0]) for info in infos})


def is_forbidden_address(address: str) -> bool:
    """Whether an IP is in a range the fetcher must never reach.

    `is_global` is False for loopback, link-local, RFC1918, reserved,
    multicast and unspecified ranges in one check — including
    `169.254.169.254`, the cloud metadata endpoint `05` §2 names specifically,
    which matters if this ever runs inside a corporate VPN or a cloud VM.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True  # unparseable is not proven safe
    return not parsed.is_global


def assert_safe_url(url: str, *, resolve: bool = True) -> None:
    """Raise `UnsafeUrlError` unless this URL is safe to fetch.

    Called on the original URL **and again on every redirect target**. `05` §2:
    "A page can return a 302 to an internal address; checking only the
    candidate URL and trusting the redirect chain defeats the whole control."

    `resolve=False` skips DNS, for the scheme/shape checks alone in contexts
    where a lookup is not wanted.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"scheme {scheme!r} is not http(s) — `05` §2 rejects file://, ftp://, data: and "
            f"everything else outright"
        )
    host = parts.hostname
    if not host:
        raise UnsafeUrlError(f"no host in {url!r}")

    if is_forbidden_address(host) and _looks_like_ip(host):
        raise UnsafeUrlError(f"{host} is an IP literal in a private or reserved range")

    if not resolve:
        return

    for address in _addresses(host):
        if is_forbidden_address(address):
            raise UnsafeUrlError(
                f"{host} resolves to {address}, which is in a private or reserved range. "
                f"A public hostname pointing at an internal address is the SSRF case `05` §2 "
                f"exists for, and it is invisible without resolving."
            )


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
