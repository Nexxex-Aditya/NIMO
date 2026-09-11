"""The extraction cascade — `03` §4 stage 3, `specs/fetch.md` §5.

Pure: HTML in, `CandidateEvidence` out. No network, no clock (the caller
supplies `fetched_at`, per `04` §5).

`03` §4 stage 3's priority order stands, and the measured availability of each
tier over ten real pages is why the lower tiers are not optional:

    JSON-LD Product   3/10   carries gtin/brand/name in one place
    microdata/RDFa    0/10   kept because absence in a sample of ten is not proof
    OpenGraph         4/10   most reliable single source of title and image
    body text        10/10   the ONLY evidence for Amazon, the largest retailer

A page that yields partial evidence is more useful than one discarded, so
every parse problem appends to `parse_warnings` rather than raising.
"""

import hashlib
import html as html_module
import re
from datetime import datetime
from typing import Literal

from nimo.contracts import CandidateEvidence
from nimo.extract.jsonld import (
    extract_jsonld_products,
    first_gtin,
)

FetchStatus = Literal["ok", "http_error", "timeout", "blocked", "parse_error"]

_OG = re.compile(
    r"<meta[^>]+property\s*=\s*[\"']og:([\w:]+)[\"'][^>]+content\s*=\s*[\"']([^\"']*)[\"']",
    re.I,
)
_OG_REVERSED = re.compile(
    r"<meta[^>]+content\s*=\s*[\"']([^\"']*)[\"'][^>]+property\s*=\s*[\"']og:([\w:]+)[\"']",
    re.I,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_IMG = re.compile(r"<img[^>]+src\s*=\s*[\"']([^\"']+)[\"']", re.I)
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Icons, sprites and tracking pixels are never the pack shot.
_NOT_A_PACKSHOT = re.compile(r"(sprite|icon|logo|pixel|badge|flag|star|1x1|blank)", re.I)


def extract_open_graph(html: str) -> dict[str, str]:
    """OpenGraph tags. Attribute order varies between sites, so both orderings
    are matched — checking only `property` before `content` silently misses
    every page that writes them the other way round."""
    tags: dict[str, str] = {}
    for key, value in _OG.findall(html):
        tags.setdefault(key.lower(), value.strip())
    for value, key in _OG_REVERSED.findall(html):
        tags.setdefault(key.lower(), value.strip())
    return tags


def extract_title(html: str, og: dict[str, str]) -> str | None:
    """OpenGraph title first, `<title>` second.

    `og:title` is the page's own statement of what the product is; `<title>`
    is often decorated with the retailer name and marketing. `01` §5 records
    that the organizers' `sample_output` put page *titles* in `PRODUCT_URL`,
    so this field may end up being submitted — `[PROVISIONAL — Q2]`.
    """
    if og.get("title"):
        return _unescape(og["title"])
    match = _TITLE.search(html)
    if not match:
        return None
    text = _WS.sub(" ", _TAG.sub(" ", _unescape(match.group(1)))).strip()
    return text or None


def _unescape(text: str) -> str:
    """Resolve HTML entities. Measured on chemist-4-u, whose title is
    `Eucryl&#x20;Freshmint&#x20;Tooth&#x20;Powder` — left encoded it would
    reach the submission, and `01` §5 says the title may BE the submitted
    value (`[PROVISIONAL — Q2]`)."""
    return html_module.unescape(text)


def extract_body_text(html: str, limit: int) -> str:
    """Boilerplate-stripped visible text.

    A dependency-free strip rather than `trafilatura` at this layer: the
    fixtures are already script-stripped, the extractor must survive markup
    too broken for a real parser, and `04` §3's typing rules make an untyped
    import a documented exception rather than a default. `trafilatura` is
    available and can replace this if measurement shows it recovers materially
    more product text.
    """
    text = _SCRIPT_STYLE.sub(" ", html)
    text = _TAG.sub(" ", text)
    return _WS.sub(" ", _unescape(text)).strip()[:limit]


def extract_images(html: str, og: dict[str, str], limit: int) -> list[str]:
    """Candidate pack-shot URLs, best guess first.

    `og:image` leads because it is the page's own declaration of the primary
    image; `03` §4 stage 3's "largest, in-gallery, non-icon" heuristic needs
    dimensions that are not in the markup, so ordering by declaration and
    filtering obvious non-product assets is what is honestly available here.
    """
    images: list[str] = []
    if og.get("image"):
        images.append(og["image"])
    for src in _IMG.findall(html):
        if _NOT_A_PACKSHOT.search(src) or src.startswith("data:"):
            continue
        if src not in images:
            images.append(src)
        if len(images) >= limit:
            break
    return images[:limit]


def extract_evidence(
    url: str,
    html: str,
    fetched_at: datetime,
    *,
    status: FetchStatus = "ok",
    http_status: int | None = None,
    detail: str | None = None,
    body_text_limit: int = 20000,
    image_limit: int = 12,
) -> CandidateEvidence:
    """Run the full cascade over one page.

    Called for **failed** fetches too, with `status` set and `html` whatever
    came back. `03` §4 stage 3: "A page that fails extraction gets
    `fetch_status` set and stays in the record. Do not drop it — a systematic
    block on one retailer is a finding, not noise." Measured, 4 of 10 real
    pages are bot walls or JS shells, so that path is the common one.
    """
    products, warnings = extract_jsonld_products(html)
    og = extract_open_graph(html)
    body = extract_body_text(html, body_text_limit)

    if status == "ok" and not products and not og and len(body) < 200:
        warnings.append(
            "no JSON-LD, no OpenGraph and almost no text — likely a JS shell or bot wall"
        )
    if status != "ok":
        # `05` §5's aggregate-domain-block guardrail needs the reason in the
        # artifact, not only in the fetcher's counters: the office run of
        # 2026-09-12 had 94% of fetches fail as `http_error` with no status
        # recorded anywhere a later reader could see (a corporate proxy).
        reason = f"fetch {status}"
        if http_status is not None:
            reason += f": HTTP {http_status}"
        if detail:
            reason += f" ({detail})"
        warnings.insert(0, reason)

    return CandidateEvidence(
        url=url,
        fetch_status=status,
        fetched_at=fetched_at,
        content_hash="sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()[:16],
        title=extract_title(html, og),
        jsonld_product=products[0] if products else None,
        gtin=first_gtin(products),
        og=dict(og),
        breadcrumbs=[],
        body_text=body,
        image_urls=extract_images(html, og, image_limit),
        price=og.get("price:amount"),
        parse_warnings=warnings,
    )
