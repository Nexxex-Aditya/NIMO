"""P8 extraction tests — `specs/fetch.md` §5, §8.

**Every test runs against a real captured page.** `04` §8 requires frozen HTML
per retailer, and hand-written HTML would not have produced the three
behaviours that actually matter here: `@graph` nesting, a malformed block
among valid ones, and a page with no structured data at all.

Zero network (`04` §6): fixtures only.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nimo.extract import (
    extract_evidence,
    extract_images,
    extract_jsonld_products,
    extract_open_graph,
    extract_title,
    first_gtin,
    product_brand,
    product_name,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pages"
TS = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)


def page(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


# --- the fixture set itself --------------------------------------------------


def test_fixture_set_covers_ten_retailers_including_the_failures() -> None:
    """A fixture set containing only pages that worked would misrepresent what
    the fetcher faces: 4 of 10 real pages are bot walls or empty shells."""
    pages = sorted(path.stem for path in FIXTURES.glob("*.html"))
    assert len(pages) == 10
    for expected in ("chemist4u", "amazon", "tesco", "boots", "ocado", "weldricks"):
        assert expected in pages


def test_fixtures_carry_no_session_tokens() -> None:
    """`04` §9 is absolute: no credentials, cookies or session tokens in
    fixtures. The first scrub pass missed 45 copies of one Amazon session id
    hiding in data attributes and JSON blobs, so this guards the shapes."""
    import re

    session_id = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
    base64_blob = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
    for path in FIXTURES.glob("*.html"):
        body = path.read_text(encoding="utf-8")
        leftover = [s for s in session_id.findall(body) if s != "000-0000000-0000000"]
        assert not leftover, f"{path.name} still contains a session id: {leftover[:2]}"
        assert not base64_blob.findall(body), f"{path.name} still contains a long token blob"


def test_manifest_records_what_was_captured() -> None:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 10
    for entry in manifest:
        assert entry["url"].startswith("http")
        assert "retailer" in entry


# --- JSON-LD: the three behaviours measurement forced ------------------------


def test_product_nested_in_a_graph_is_found() -> None:
    """chemist-4-u's Product sits inside an `ItemPage`/`WebPage` `@graph`. A
    top-level `@type == "Product"` check finds nothing on that page."""
    products, warnings = extract_jsonld_products(page("chemist4u"))
    assert len(products) == 1
    assert warnings == []
    assert first_gtin(products) == "5011309895612"
    assert product_name(products) == "Eucryl Freshmint Tooth Powder - 50g"
    assert product_brand(products) == "Eucryl"


def test_a_malformed_block_among_valid_ones_warns_but_does_not_fail() -> None:
    """aquafresh ships 5 `ld+json` blocks and one fails to parse. One bad
    block is a parse warning, not a failed page (`03` §3 `parse_warnings`)."""
    products, warnings = extract_jsonld_products(page("aquafresh"))
    assert len(warnings) == 1
    assert "unparseable" in warnings[0]
    assert products == []  # this page genuinely has no Product node


def test_a_page_with_no_json_ld_yields_no_products_and_no_warnings() -> None:
    """Amazon: 1.4 MB, zero JSON-LD, zero OpenGraph. Absence is not an error."""
    products, warnings = extract_jsonld_products(page("amazon"))
    assert products == []
    assert warnings == []


def test_brand_is_read_from_a_nested_brand_object() -> None:
    """schema.org allows `brand` as a string or a `Brand` object; real pages
    use both."""
    assert product_brand([{"brand": {"@type": "Brand", "name": "Eucryl"}}]) == "Eucryl"
    assert product_brand([{"brand": "Eucryl"}]) == "Eucryl"
    assert product_brand([{"name": "no brand here"}]) is None


def test_gtin_is_returned_verbatim_never_reshaped() -> None:
    """`01` §3 is a whole document about an identifier silently reshaped.
    Comparing lengths is the matcher's job (`03` §4 stage 4)."""
    assert first_gtin([{"gtin13": "05011309895612"}]) == "05011309895612"
    assert first_gtin([{"gtin": 5011309895612}]) == "5011309895612"
    assert first_gtin([{"sku": "ABC"}]) is None


def test_type_as_a_list_is_matched() -> None:
    """`["ItemPage","WebPage"]` is real markup; a string comparison misses it."""
    products, _ = extract_jsonld_products(
        '<script type="application/ld+json">'
        '{"@type":["Product","Thing"],"name":"X","gtin13":"1234567890123"}'
        "</script>"
    )
    assert len(products) == 1
    assert first_gtin(products) == "1234567890123"


# --- the same product on two retailers, by GTIN ------------------------------


def test_two_retailers_agree_on_the_gtin_for_one_product() -> None:
    """**The measurement that validates scoring the product rather than the
    URL string.** chemist-4-u and pharmazondirect are different sites with
    different titles and different markup, and both report GTIN
    `5011309895612` for the same Eucryl toothpowder.

    `dev:410` in the P4 gold set is that row, and its label names a *third*
    retailer. Scoring "did we find THE labelled URL" marks both of these
    wrong; scoring the product marks both right — which is what `01` §5
    already hinted when the organizers' own reference answer resolved a GB
    item to Amazon.in.
    """
    left = extract_evidence("https://chemist-4-u.com/p", page("chemist4u"), TS)
    right = extract_evidence("https://pharmazondirect.com/p", page("pharmazon"), TS)
    assert left.gtin == right.gtin == "5011309895612"
    assert left.url != right.url
    assert left.title != right.title


# --- OpenGraph and titles ----------------------------------------------------


def test_open_graph_is_extracted_where_present() -> None:
    og = extract_open_graph(page("wholedent"))
    assert og.get("title")
    assert og.get("image")
    assert len(og) >= 10


def test_html_entities_do_not_survive_into_the_title() -> None:
    """chemist-4-u's raw title is `Eucryl&#x20;Freshmint&#x20;Tooth&#x20;Powder`.
    `01` §5 records that the title may itself be the submitted value
    (`[PROVISIONAL — Q2]`), so an encoded one would ship."""
    title = extract_title(page("chemist4u"), extract_open_graph(page("chemist4u")))
    assert title is not None
    assert "&#x20;" not in title
    assert "Eucryl Freshmint Tooth Powder" in title


def test_title_falls_back_to_the_title_tag_without_open_graph() -> None:
    """Amazon has no OpenGraph at all, so `<title>` is the only source."""
    html = page("amazon")
    assert extract_open_graph(html) == {}
    title = extract_title(html, {})
    assert title is not None and "UltraDEX" in title


# --- images ------------------------------------------------------------------


def test_icons_and_sprites_are_not_offered_as_pack_shots() -> None:
    html = (
        '<meta property="og:image" content="https://cdn.test/packshot.jpg">'
        '<img src="https://cdn.test/sprite-nav.png">'
        '<img src="https://cdn.test/logo.svg">'
        '<img src="data:image/gif;base64,R0lGOD">'
        '<img src="https://cdn.test/product-2.jpg">'
    )
    images = extract_images(html, extract_open_graph(html), limit=12)
    assert images[0] == "https://cdn.test/packshot.jpg"
    assert "https://cdn.test/product-2.jpg" in images
    assert not any("sprite" in i or "logo" in i or i.startswith("data:") for i in images)


# --- failed fetches stay in the record ---------------------------------------


@pytest.mark.parametrize(
    ("name", "marker"), [("boots", "Pardon Our Interruption"), ("weldricks", "Just a moment")]
)
def test_a_bot_wall_still_produces_evidence(name: str, marker: str) -> None:
    """`03` §4 stage 3: "A page that fails extraction gets `fetch_status` set
    and stays in the record. Do not drop it — a systematic block on one
    retailer is a finding, not noise." Measured, this is the common case."""
    evidence = extract_evidence(f"https://{name}.test/p", page(name), TS, status="blocked")
    assert evidence.fetch_status == "blocked"
    assert evidence.content_hash.startswith("sha256:")
    assert marker in (evidence.title or "") + evidence.body_text


def test_an_empty_response_is_flagged_not_silently_accepted() -> None:
    """Ocado returned HTTP 202 with zero bytes — a success status carrying no
    page. Silently accepting that is how an empty evidence record reaches the
    matcher looking like a real one."""
    evidence = extract_evidence("https://ocado.test/p", page("ocado"), TS)
    assert evidence.body_text == ""
    assert any("JS shell or bot wall" in w for w in evidence.parse_warnings)


def test_evidence_is_a_contract_instance_with_a_stable_hash() -> None:
    """`04` §5: same input, same output — the hash must not move between runs."""
    first = extract_evidence("https://chemist-4-u.com/p", page("chemist4u"), TS)
    second = extract_evidence("https://chemist-4-u.com/p", page("chemist4u"), TS)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_body_text_is_capped() -> None:
    """Amazon's page is 900 KB after scrubbing; unbounded body text would
    reach an LLM prompt at P11 and blow the token budget (`05` §3)."""
    evidence = extract_evidence("https://amazon.test/p", page("amazon"), TS, body_text_limit=5000)
    assert len(evidence.body_text) == 5000
