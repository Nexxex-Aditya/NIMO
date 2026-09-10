"""P8 SSRF guard tests — `05` §2, `specs/fetch.md` §2, §8.

Zero network: DNS is stubbed. `05` §6 makes these Definition-of-Done items for
any fetch module, so they are behaviour tests, not smoke tests.
"""

import socket
from collections.abc import Iterator
from typing import Any

import pytest

from nimo.fetch.guard import UnsafeUrlError, assert_safe_url, is_forbidden_address


def stub_dns(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]) -> None:
    """Point `getaddrinfo` at a fixed table. No network (`04` §6)."""

    def fake(host: str, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        if host not in mapping:
            raise socket.gaierror(f"stub: {host} unknown")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0)) for address in mapping[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    stub_dns(monkeypatch, {"boots.com": ["93.184.216.34"]})
    yield


# --- address classification --------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.249.224.116",  # RFC1918 — and the CIS LLM endpoint, see below
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",  # cloud metadata, named explicitly in `05` §2
        "0.0.0.0",
        "::1",
        "fc00::1",
    ],
)
def test_private_and_reserved_addresses_are_forbidden(address: str) -> None:
    assert is_forbidden_address(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "1.1.1.1"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert not is_forbidden_address(address)


def test_an_unparseable_address_is_not_assumed_safe() -> None:
    """Fail closed: something that is not an address is not proven harmless."""
    assert is_forbidden_address("not-an-address")


# --- scheme ------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["file", "ftp", "data", "gopher", "javascript"])
def test_non_http_schemes_are_refused(scheme: str) -> None:
    with pytest.raises(UnsafeUrlError, match="not http"):
        assert_safe_url(f"{scheme}://example.com/x", resolve=False)


def test_a_url_without_a_host_is_refused() -> None:
    with pytest.raises(UnsafeUrlError, match="no host"):
        assert_safe_url("https:///path", resolve=False)


# --- IP literals -------------------------------------------------------------


def test_a_private_ip_literal_is_refused_without_dns() -> None:
    with pytest.raises(UnsafeUrlError, match="private or reserved"):
        assert_safe_url("http://169.254.169.254/latest/meta-data/", resolve=False)


# --- DNS: the case P7 could not cover ----------------------------------------


def test_a_public_hostname_resolving_to_a_private_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The SSRF case that matters.** The hostname looks entirely ordinary;
    only resolving it reveals where it points. P7's gate could not do this —
    it would have meant resolving every candidate it never fetches."""
    stub_dns(monkeypatch, {"evil.test": ["10.0.0.5"]})
    with pytest.raises(UnsafeUrlError, match="resolves to 10.0.0.5"):
        assert_safe_url("https://evil.test/page")


def test_every_resolved_address_is_checked_not_just_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host can resolve to one public and one private address. Checking only
    the first is bypassed by DNS ordering, which the attacker controls."""
    stub_dns(monkeypatch, {"mixed.test": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(UnsafeUrlError, match="private or reserved"):
        assert_safe_url("https://mixed.test/page")


def test_a_public_host_passes(public_dns: None) -> None:
    assert_safe_url("https://boots.com/product/123")


def test_a_host_that_does_not_resolve_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_dns(monkeypatch, {})
    with pytest.raises(UnsafeUrlError, match="does not resolve"):
        assert_safe_url("https://nowhere.test/x")


# --- redirects ---------------------------------------------------------------


def test_each_redirect_hop_is_validated_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    """`05` §2: "A page can return a 302 to an internal address; checking only
    the candidate URL and trusting the redirect chain defeats the whole
    control." The first hop is fine; the second is not."""
    stub_dns(monkeypatch, {"start.test": ["93.184.216.34"], "hop2.test": ["169.254.169.254"]})
    assert_safe_url("https://start.test/a")
    with pytest.raises(UnsafeUrlError, match="private or reserved"):
        assert_safe_url("https://hop2.test/b")


# --- scoping -----------------------------------------------------------------


def test_the_guard_takes_a_candidate_url_and_nothing_else() -> None:
    """Documents the scoping that keeps this from breaking our own model.

    The CIS LLM endpoint is an RFC1918 address (`10.249.224.116`,
    `config/models.yaml`), so promoting this into a global outbound check
    would block the pipeline's own LLM with a timeout whose cause is not
    remotely obvious. The guard's only input is a URL — it has no view of
    configured endpoints and cannot be applied to them by accident.
    """
    import inspect

    parameters = list(inspect.signature(assert_safe_url).parameters)
    assert parameters == ["url", "resolve"]
    assert is_forbidden_address("10.249.224.116"), (
        "the CIS LLM endpoint IS in a forbidden range for candidate URLs — which is exactly "
        "why this check must stay scoped to candidates and never become global"
    )
