"""P7 canonicalization and candidate-safety tests — `specs/retrieval.md` §3, §4.

Pure functions, zero network (`04` §6).
"""

import pytest

from nimo.retrieval import UrlError, canonicalize, is_private_host, is_safe_candidate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Boots.com/Product/123", "https://boots.com/Product/123"),
        ("https://boots.com/product/123/", "https://boots.com/product/123"),
        ("https://boots.com/product/123#reviews", "https://boots.com/product/123"),
        ("https://boots.com:443/product", "https://boots.com/product"),
        ("http://boots.com:80/product", "http://boots.com/product"),
        ("https://boots.com/", "https://boots.com/"),
    ],
)
def test_canonical_forms(raw: str, expected: str) -> None:
    assert canonicalize(raw) == expected


def test_tracking_parameters_are_dropped() -> None:
    assert (
        canonicalize("https://boots.com/p?utm_source=google&utm_medium=cpc&gclid=abc")
        == "https://boots.com/p"
    )


def test_product_identifying_parameters_are_kept() -> None:
    """The load-bearing half of the rule. On real retailer sites `?variant=`
    is the difference between a 75ml and a 100ml listing, so stripping unknown
    parameters would merge two different products into one candidate — the
    exact identity error the matcher exists to avoid (`specs/retrieval.md` §3).
    """
    assert (
        canonicalize("https://boots.com/p?variant=75ml&utm_source=x")
        == "https://boots.com/p?variant=75ml"
    )
    assert "sku=ABC" in canonicalize("https://boots.com/p?sku=ABC&sessionid=zzz")


def test_query_parameters_are_sorted_so_orderings_dedup() -> None:
    left = canonicalize("https://boots.com/p?b=2&a=1")
    right = canonicalize("https://boots.com/p?a=1&b=2")
    assert left == right


def test_unicode_lookalike_hyphen_is_normalized() -> None:
    """`01` §13: `sample_output`'s `PRODUCT_URL` contains a `U+2011`
    non-breaking hyphen. Treated as a literal character it produces a URL that
    resolves nowhere and dedups against nothing."""
    assert canonicalize("https://boots.com/anti‑plaque") == "https://boots.com/anti-plaque"


@pytest.mark.parametrize("dash", ["‐", "‑", "‒", "–", "—", "―", "−"])
def test_every_unicode_dash_folds_to_ascii(dash: str) -> None:
    """NFKC is necessary but NOT sufficient, which was found by testing rather
    than assumed: NFKC maps `U+2011` to `U+2010`, not to ASCII `-`, and the
    whole U+2010..U+2015 range plus `U+2212` survive it as non-ASCII. A URL
    still carrying one resolves nowhere."""
    canonical = canonicalize(f"https://boots.com/anti{dash}plaque")
    assert canonical == "https://boots.com/anti-plaque"
    assert canonical.isascii()


@pytest.mark.parametrize("invisible", ["­", "​", "‌", "‍", "﻿"])
def test_invisible_characters_are_deleted_not_folded(invisible: str) -> None:
    """They carry no meaning in a URL and survive copy-paste from rendered
    pages — folding them to a visible character would corrupt the path."""
    assert canonicalize(f"https://boots.com/anti{invisible}plaque") == (
        "https://boots.com/antiplaque"
    )


def test_canonicalization_is_idempotent() -> None:
    for url in (
        "https://www.Boots.com/P/123/?utm_source=x&variant=75ml#frag",
        "http://superdrug.com:80/a/b/",
        "https://amazon.co.uk/dp/B01?th=1",
    ):
        once = canonicalize(url)
        assert canonicalize(once) == once


@pytest.mark.parametrize("scheme", ["file", "ftp", "data", "javascript"])
def test_non_http_schemes_are_rejected(scheme: str) -> None:
    """`05` §2 rejects these outright, before a fetcher ever sees them."""
    with pytest.raises(UrlError, match="not http"):
        canonicalize(f"{scheme}://etc/passwd")


def test_empty_and_hostless_urls_are_rejected() -> None:
    with pytest.raises(UrlError):
        canonicalize("   ")
    with pytest.raises(UrlError, match="no host"):
        canonicalize("https:///path")


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "10.249.224.116", "192.168.1.1", "172.16.0.1", "169.254.169.254", "::1"],
)
def test_private_and_reserved_ip_literals_are_recognized(host: str) -> None:
    """`169.254.169.254` is the cloud metadata endpoint `05` §2 names
    specifically; `10.249.224.116` is the CIS LLM endpoint, included here to
    make the scoping point concrete."""
    assert is_private_host(host)


@pytest.mark.parametrize("host", ["boots.com", "8.8.8.8", "93.184.216.34"])
def test_public_hosts_are_not_flagged(host: str) -> None:
    assert not is_private_host(host)


def test_candidate_gate_drops_private_and_non_http() -> None:
    assert not is_safe_candidate("http://127.0.0.1/admin")
    assert not is_safe_candidate("http://169.254.169.254/latest/meta-data/")
    assert not is_safe_candidate("file:///etc/passwd")
    assert not is_safe_candidate("not a url")
    assert is_safe_candidate("https://boots.com/product/123")


def test_the_gate_is_scoped_to_candidates_not_all_outbound_traffic() -> None:
    """Documents the interaction that would otherwise be rediscovered as a
    mystery timeout: the CIS LLM endpoint is an RFC1918 address, so this check
    must never be promoted into a global outbound guard
    (`02-decision-log.md`, `config/models.yaml`)."""
    assert is_private_host("10.249.224.116")
    # ...and nothing in this module inspects a configured endpoint — the gate
    # takes a candidate URL as its only input.
    assert not is_safe_candidate("https://10.249.224.116/chat/completions")
