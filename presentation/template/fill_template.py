"""Fill the Hackfest 2026 template with NIMO's content, keeping its design.

    uv run --no-project python presentation/template/fill_template.py

Reads   presentation/template/Hackfest_2026_Solution_Presentation_Template.pptx
Writes  presentation/NIMO_Hackfest_2026.pptx

Only text is replaced (same boxes, fonts and colours as the template), plus
one extra slide in the demo section, built from the template's own slide 4
chrome, carrying two real screenshots from the results explorer.
"""

import re
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "Hackfest_2026_Solution_Presentation_Template.pptx"
OUT = HERE.parent / "NIMO_Hackfest_2026.pptx"
ASSETS = HERE.parent / "assets"
WORK = HERE / "build"

EMU = 914400
INK, BODY, MUTED, NAVY, BLUE, LINE = "172044", "172044", "5E6784", "08124F", "2E6AF6", "DCE1EE"


def emu(inches: float) -> int:
    return int(round(inches * EMU))


# ------------------------------------------------------------------ XML helpers
def run(text: str, sz: int, color: str = BODY, b: bool = False) -> str:
    bold = ' b="1"' if b else ""
    return (f'<a:r><a:rPr lang="en-GB" sz="{sz}"{bold} dirty="0"><a:solidFill>'
            f'<a:srgbClr val="{color}"/></a:solidFill></a:rPr><a:t>{escape(text)}</a:t></a:r>')


def para(runs: list[str], algn: str | None = None, after: int = 0) -> str:
    a = f' algn="{algn}"' if algn else ""
    spc = f'<a:spcAft><a:spcPts val="{after}"/></a:spcAft>' if after else ""
    return f'<a:p><a:pPr marL="0" indent="0"{a}>{spc}<a:buNone/></a:pPr>{"".join(runs)}</a:p>'


def lead(head: str, rest: str, sz: int, after: int = 700) -> str:
    """A paragraph that opens with a short bold phrase in navy."""
    return para([run(head + " ", sz, NAVY, b=True), run(rest, sz)], after=after)


def plain(text: str, sz: int, color: str = BODY, after: int = 0, b: bool = False, algn: str | None = None) -> str:
    return para([run(text, sz, color, b=b)], algn=algn, after=after)


def shapes(xml: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"<p:sp>.*?</p:sp>", xml, re.S)]


def find(xml: str, name: str, contains: str | None = None) -> tuple[int, int, str]:
    hits = [s for s in shapes(xml) if f'name="{name}"' in s[2] and (contains is None or contains in s[2])]
    assert len(hits) == 1, (name, contains, len(hits))
    return hits[0]


def set_text(xml: str, name: str, paras: list[str], *, contains: str | None = None,
             box: tuple[float, float, float, float] | None = None, anchor: str | None = None,
             autofit: bool = True) -> str:
    start, end, sp = find(xml, name, contains)
    head, _, _ = sp.partition("<a:lstStyle/>")
    if anchor:
        head = re.sub(r'anchor="[a-z]+"', f'anchor="{anchor}"', head)
    if not autofit:
        head = re.sub(r"<a:normAutofit[^>]*/>", "", head)
    if box:
        x, y, w, h = box
        xfrm = f'<a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
        head = re.sub(r"<a:xfrm>.*?</a:xfrm>", xfrm, head, count=1, flags=re.S)
    new = head + "<a:lstStyle/>" + "".join(paras) + "</p:txBody></p:sp>"
    return xml[:start] + new + xml[end:]


def set_box(xml: str, name: str, box: tuple[float, float, float, float]) -> str:
    start, end, sp = find(xml, name)
    x, y, w, h = box
    xfrm = f'<a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
    return xml[:start] + re.sub(r"<a:xfrm>.*?</a:xfrm>", xfrm, sp, count=1, flags=re.S) + xml[end:]


def set_notes(root: Path, n: int, text: str) -> None:
    path = root / "ppt" / "notesSlides" / f"notesSlide{n}.xml"
    if not path.exists():
        return
    xml = path.read_text(encoding="utf-8")
    m = re.search(r'<p:sp>(?:(?!</p:sp>).)*?<p:ph type="body"(?:(?!</p:sp>).)*?</p:sp>', xml, re.S)
    if not m:
        return
    sp = m.group(0)
    head, _, _ = sp.partition("<a:lstStyle/>") if "<a:lstStyle/>" in sp else (sp.split("<p:txBody>")[0] + "<p:txBody><a:bodyPr/>", "", "")
    body = "".join(f'<a:p><a:r><a:rPr lang="en-GB" dirty="0"/><a:t>{escape(p)}</a:t></a:r></a:p>' for p in text.split("\n"))
    new = head + "<a:lstStyle/>" + body + "</p:txBody></p:sp>"
    path.write_text(xml[: m.start()] + new + xml[m.end():], encoding="utf-8")


# ------------------------------------------------------------------ build
def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    with zipfile.ZipFile(TEMPLATE) as z:
        z.extractall(WORK)
    slides = WORK / "ppt" / "slides"

    # ---- 1 cover
    p = slides / "slide1.xml"
    x = p.read_text(encoding="utf-8")
    x = set_text(x, "Text 1", [
        plain("NIMO", 4400, "FFFFFF", b=True, algn="l"),
        plain("The Product Truth Agent", 2400, "FFFFFF", b=True, algn="l", after=900),
        plain("Team Matrix Slayers", 1500, "DCE8FF", algn="l"),
    ], contains="Solution Presentation Template", box=(0.37, 3.55, 7.0, 1.95), anchor="b", autofit=False)
    p.write_text(x, encoding="utf-8")

    # ---- 2 problem & solution
    p = slides / "slide2.xml"
    x = p.read_text(encoding="utf-8")
    x = set_text(x, "Text 2", [plain("Linking a retail record to the right product page, and reading that page correctly, is still done by hand.", 1050, MUTED)])
    x = set_text(x, "Text 6", [plain(
        "One product appears on dozens of pages with different names, pack sizes and promotions. "
        "Picking the true page and coding its 13 characteristics is manual, slow and easy to get "
        "wrong on look-alikes: a 2-pack, a refill, a sister variant.", 1200)],
        box=(0.84, 2.14, 5.43, 0.82), anchor="t")
    x = set_text(x, "Text 11", [plain(
        "NIQ coding and data-quality teams who link retailer records to products and "
        "characteristics, and the analysts and clients downstream who depend on that coding "
        "being right.", 1200)], box=(7.05, 2.14, 5.43, 0.82), anchor="t")
    x = set_text(x, "Text 16", [plain(
        "NIMO reads a retail record (description, brand, barcode, retailer), finds the page that "
        "is that product, names its module, fills only the characteristics that apply and "
        "explains each answer. It writes the submission file itself, in the exact qa format.", 1200)],
        box=(0.84, 3.82, 5.43, 1.05), anchor="t")
    x = set_text(x, "Text 21", [plain(
        "It proves identity instead of guessing: the same barcode on the page confirms it, a "
        "different one rules it out. It remembers every product it has confirmed, so a repeat "
        "costs a lookup, not a search. And every answer comes with its evidence.", 1200)],
        box=(7.05, 3.82, 5.43, 1.05), anchor="t")
    x = set_box(x, "Shape 23", (0.62, 5.42, 1.39, 0.34))
    x = set_text(x, "Text 24", [plain("BEFORE → AFTER", 850, BLUE, b=True, algn="ctr")], box=(0.62, 5.51, 1.39, 0.16))
    x = set_text(x, "Text 25", [para([
        run("Before: ", 1100, NAVY, b=True), run("a coder opens pages one by one.   ", 1100, MUTED),
        run("After: ", 1100, NAVY, b=True),
        run("all 412 qa products resolved in one run, 114 confirmed by barcode, each with its reasoning.", 1100, MUTED)])],
        box=(2.2, 5.42, 10.4, 0.34))
    p.write_text(x, encoding="utf-8")

    # ---- 3 detailed solution
    p = slides / "slide3.xml"
    x = p.read_text(encoding="utf-8")
    x = set_text(x, "Text 2", [plain("Rules and evidence do most of the work. The model is used only where judgement is needed.", 1050, MUTED)])
    x = set_text(x, "Text 6", [
        lead("Barcode first.", "A page showing the record's barcode is accepted; a different barcode is rejected, however similar the text looks.", 1150),
        lead("A memory of products.", "Every confirmed product is stored. On the re-run, 111 of the 412 qa rows were answered from memory, with no search at all.", 1150),
        lead("Reasoning you can check.", "Each sentence is built from a recorded field, so it cannot claim anything the evidence does not show.", 1150, after=0),
    ], box=(0.84, 2.3, 3.65, 3.0), anchor="t")
    x = set_text(x, "Text 11", [
        lead("Cheaper as it grows.", "A product seen once is a lookup the next time, so the cost per row falls as the registry fills.", 1150),
        lead("Built for large runs.", "Every step is cached and resumable. 412 rows ran in 107 minutes on free search engines, and a re-run gives a byte-identical file.", 1150),
        lead("Any list, any machine.", "An Excel file with a description and brand goes through the same pipeline. Search works through SearxNG or the Brave API, with no Docker needed.", 1150, after=0),
    ], box=(5.05, 2.3, 3.65, 3.0), anchor="t")
    x = set_text(x, "Text 16", [
        lead("Two narrow jobs.", "The model breaks ties between close candidates, answering with a number that points at one of them, never a URL. It also reads evidence into characteristic values.", 1150),
        lead("Checked, not trusted.", "It is only asked for characteristics that apply to the module, and every value must be in NIQ's allowed list.", 1150),
        lead("Low cost.", "About 1M tokens for all 412 rows, and none on a re-run.", 1150, after=0),
    ], box=(9.26, 2.3, 3.24, 3.0), anchor="t")
    x = set_text(x, "Text 19", [plain("ONE ROW, END TO END", 850, "FFFFFF", b=True, algn="ctr")])
    x = set_text(x, "Text 20", [plain(
        "Record  ›  memory check  ›  web search  ›  fetch pages  ›  match  ›  module  ›  characteristics  ›  reasoning  ›  qa output row",
        1100, NAVY)], box=(2.35, 5.78, 10.3, 0.3))
    p.write_text(x, encoding="utf-8")

    # ---- 4 how it works
    p = slides / "slide4.xml"
    x = p.read_text(encoding="utf-8")
    x = set_text(x, "Text 2", [plain("From one product record to one validated output row.", 1050, MUTED)])
    flow = {
        "Text 6": "A product record: description, brand, barcode, retailer, country. From the qa sheet, the web form or any Excel file.",
        "Text 12": "Registry lookup, five search strategies, barcode rules, a calibrated match score, a module classifier, and the LLM for ties and characteristics.",
        "Text 18": "Searches the web, fetches candidate pages safely, confirms barcodes, keeps only the characteristics that apply and validates every value.",
        "Text 24": "One row per product in the exact qa format: URL, module, 13 characteristics and the reasoning. Plus a searchable results page.",
    }
    for name, text in flow.items():
        x = set_text(x, name, [plain(text, 1100)], anchor="t")
    x = set_text(x, "Text 29", [plain(t, 1100, after=200) for t in (
        "Identity proven by barcode", "Remembers every resolved product", "Every answer cites its evidence")], anchor="t")
    x = set_text(x, "Text 33", [plain(t, 1100, after=200) for t in (
        "Python 3.12, pydantic, httpx, FastAPI", "SearxNG or the Brave Search API", "NIQ CIS LLM (hack-fest-gpt-5.6-luna)")], anchor="t")
    x = set_text(x, "Text 37", [plain(t, 1100, after=200) for t in (
        "Live UI: uv run python -m nimo.ui --live", "Results page: site_qa.html, opens offline",
        "github.com/Nexxex-Aditya/NIMO  ·  screenshots next")], anchor="t")
    p.write_text(x, encoding="utf-8")
    demo_chrome = x  # the new slide reuses this slide's header and footer

    # ---- 5 impact
    p = slides / "slide5.xml"
    x = p.read_text(encoding="utf-8")
    x = set_text(x, "Text 2", [plain("What it delivered on the qa set, where else it applies, and what we would do next.", 1050, MUTED)])
    x = set_text(x, "Text 6", [
        plain("412 of 412 qa products resolved end to end; 114 confirmed by the page's own barcode.", 1150, after=600),
        plain("Brand homepages given as answers: 100 before our fix, 0 after.", 1150, after=600),
        plain("Module accuracy 80.3% on the labelled set. A match confidence of 0.93 means about 93 in 100 are right.", 1150),
    ], box=(0.84, 2.2, 3.65, 1.75), anchor="t")
    x = set_text(x, "Text 11", [plain(
        "Any catalogue that must be tied to the web: new product onboarding, retailer assortment "
        "checks, price and availability tracking, attribute enrichment. Other categories need new "
        "vocabularies and guidelines, not new code.", 1150)], box=(5.06, 2.2, 3.65, 1.75), anchor="t")
    x = set_text(x, "Text 16", [plain(
        "Run search, pages and the model on one network. Learn the 32 modules missing from the "
        "labelled data from page evidence. Agree with NIQ how a blank URL scores against a wrong "
        "one, then switch on abstention, which is already built.", 1150)], box=(9.28, 2.2, 3.22, 1.75), anchor="t")
    x = set_text(x, "Text 20", [plain("Team Matrix Slayers", 1500, "FFFFFF", b=True)])
    x = set_text(x, "Text 21", [plain("Aditya Samal  ·  Build lead  ·  Architecture, pipeline, evaluation and demo", 1100, "E5E9F7")])
    x = set_text(x, "Text 23", [plain("412 / 412 ROWS", 850, BLUE, b=True, algn="ctr")])
    p.write_text(x, encoding="utf-8")

    # ---- new slide after 4: what a result looks like
    keep = [find(demo_chrome, n)[2] for n in ("Text 0", "Text 1", "Slide Number Placeholder 0")]
    keep.append(set_text(find(demo_chrome, "Text 2")[2], "Text 2", [plain(
        "Two real rows from NIMO's results page. Every line names the pipeline step that produced it.", 1050, MUTED)]))
    keep[1] = keep[1].replace("How It Works", "What a Result Looks Like")
    frame_tpl = find(demo_chrome, "Shape 3")[2]

    def frame(idn: int, x0: float) -> str:
        f = frame_tpl.replace('name="Shape 3"', f'name="Frame {idn}"')
        f = re.sub(r'<p:cNvPr id="\d+"', f'<p:cNvPr id="{idn}"', f)
        return re.sub(r"<a:xfrm>.*?</a:xfrm>", f'<a:xfrm><a:off x="{emu(x0)}" y="{emu(1.62)}"/><a:ext cx="{emu(5.95)}" cy="{emu(5.1)}"/></a:xfrm>', f, flags=re.S)

    def textbox(idn: int, box: tuple[float, float, float, float], paras: list[str]) -> str:
        bx, by, bw, bh = box
        return (f'<p:sp><p:nvSpPr><p:cNvPr id="{idn}" name="Caption {idn}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
                f'<p:spPr><a:xfrm><a:off x="{emu(bx)}" y="{emu(by)}"/><a:ext cx="{emu(bw)}" cy="{emu(bh)}"/></a:xfrm>'
                f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
                f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"/><a:lstStyle/>{"".join(paras)}</p:txBody></p:sp>')

    def picture(idn: int, rid: str, box: tuple[float, float, float, float], descr: str) -> str:
        bx, by, bw, bh = box
        return (f'<p:pic><p:nvPicPr><p:cNvPr id="{idn}" name="Screenshot {idn}" descr="{escape(descr)}"/>'
                f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
                f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
                f'<p:spPr><a:xfrm><a:off x="{emu(bx)}" y="{emu(by)}"/><a:ext cx="{emu(bw)}" cy="{emu(bh)}"/></a:xfrm>'
                f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:ln w="9525"><a:solidFill><a:srgbClr val="{LINE}"/></a:solidFill></a:ln></p:spPr></p:pic>')

    # image sizes: crop_qa0 1200x762, crop_qa28 1200x950
    left_img = (0.745, 2.08, 5.7, 5.7 * 762 / 1200)
    right_h = 3.9
    right_img = (6.73 + (5.95 - right_h * 1200 / 950) / 2, 2.08, right_h * 1200 / 950, right_h)
    new_shapes = [
        frame(101, 0.62), frame(102, 6.73),
        textbox(103, (0.84, 1.78, 5.5, 0.22), [plain("QA:0  ·  THE RIGHT PAGE AMONG LOOK-ALIKES", 850, MUTED, b=True)]),
        textbox(104, (6.95, 1.78, 5.5, 0.22), [plain("QA:28  ·  CHARACTERISTICS CODED BY THE MODEL", 850, MUTED, b=True)]),
        picture(105, "rId3", left_img, "NIMO results card for qa:0"),
        picture(106, "rId4", right_img, "NIMO results card for qa:28"),
        textbox(107, (0.84, 6.08, 5.5, 0.55), [plain(
            "The brand word ‘Brilliant’ also brought back paint pages and a tutoring site. "
            "NIMO picked the Superdrug product page, at a calibrated 0.93, and says why.", 1050, BODY)]),
        textbox(108, (6.95, 6.08, 5.5, 0.55), [plain(
            "Green People kids’ toothpaste: 9 applicable characteristics coded, all within NIQ’s "
            "allowed values. The record says fluoride free; the output says WITHOUT FLUORIDE.", 1050, BODY)]),
    ]
    tree_head = demo_chrome.split("<p:sp>", 1)[0]
    tree_tail = demo_chrome[demo_chrome.rfind("</p:spTree>"):]
    (slides / "slide7.xml").write_text(tree_head + "".join(keep) + "".join(new_shapes) + tree_tail, encoding="utf-8")
    media = WORK / "ppt" / "media"
    shutil.copy(ASSETS / "crop_qa0.png", media / "image3.png")
    shutil.copy(ASSETS / "crop_qa28.png", media / "image4.png")
    (slides / "_rels" / "slide7.xml.rels").write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image3.png"/>'
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image4.png"/>'
        "</Relationships>", encoding="utf-8")
    ct = WORK / "[Content_Types].xml"
    t = ct.read_text(encoding="utf-8")
    t = t.replace("</Types>", '<Override PartName="/ppt/slides/slide7.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>')
    ct.write_text(t, encoding="utf-8")
    rels = WORK / "ppt" / "_rels" / "presentation.xml.rels"
    t = rels.read_text(encoding="utf-8")
    t = t.replace("</Relationships>", '<Relationship Id="rId100" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide7.xml"/></Relationships>')
    rels.write_text(t, encoding="utf-8")
    pres = WORK / "ppt" / "presentation.xml"
    t = pres.read_text(encoding="utf-8")
    anchor = '<p:sldId id="259" r:id="rId5"/>'
    assert t.count(anchor) == 1
    pres.write_text(t.replace(anchor, anchor + '<p:sldId id="265" r:id="rId100"/>'), encoding="utf-8")
    app = WORK / "docProps" / "app.xml"
    app.write_text(app.read_text(encoding="utf-8").replace("<Slides>6</Slides>", "<Slides>7</Slides>"), encoding="utf-8")

    # ---- speaker notes (slides 1-5 have notes parts)
    notes = {
        1: "NIMO is our answer to the Product Truth Agent problem. Give it a retail product record and it finds the web page that really is that product, codes the characteristics NIQ needs, and explains every answer.",
        2: "Today a coder does this by hand, page by page, and look-alikes get through. NIMO does the whole chain and writes the submission file itself. The key difference: it proves identity with the barcode where it can, and remembers what it has already resolved.",
        3: "Three ideas. Barcode first, so identity is proven rather than guessed. A memory of products, so repeats are cheap. And reasoning built from recorded fields, so it can be checked. The model only does two narrow jobs, and everything it says is validated.",
        4: "One record goes in; one validated row comes out. In between: the registry check, web search, page fetching, matching with barcode rules and a calibrated score, the module, the characteristics that apply, and the reasoning. Next slide shows two real rows.",
        5: "Results on the full qa set, the use cases beyond oral care, and what we would do next. All numbers are measured and recorded in our decision log.",
    }
    for n, text in notes.items():
        set_notes(WORK, n, text)

    # ---- pack
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        ct_path = WORK / "[Content_Types].xml"
        z.write(ct_path, "[Content_Types].xml")
        for path in sorted(WORK.rglob("*")):
            # `[trash]/` is Mac PowerPoint's scratch space inside the template; nothing references it
            if path.is_file() and path != ct_path and not path.relative_to(WORK).as_posix().startswith("[trash]"):
                z.write(path, path.relative_to(WORK).as_posix())
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
