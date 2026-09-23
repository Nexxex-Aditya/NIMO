// Builds presentation/NIMO_Product_Truth_Agent.pptx — every number on these
// slides is measured and recorded in docs/02-decision-log.md or docs/04 §1.
// Run: cd presentation && node build_deck.js
const pptxgen = require("pptxgenjs");
const path = require("path");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.title = "NIMO — the Product Truth Agent";
pres.company = "Team Matrix Slayers";

const INK = "0B2A33", TEAL = "0E7C7B", TEAL_D = "0A5C5B", MINT = "E6F4F1", MINT_T = "9FE3D6";
const AMBER = "D9822B", CORAL = "C0492F", TEXT = "1F2D33", MUTED = "5B6B70", LINE = "D5E3E0";
const WHITE = "FFFFFF", GREYBAR = "B7C9CC";
const HEAD = "Cambria", BODY = "Calibri";
const A = (f) => path.join(__dirname, "assets", f);

function kicker(slide, text, y = 0.42) {
  slide.addText(text, { x: 0.6, y, w: 8, h: 0.3, fontFace: BODY, fontSize: 12, bold: true,
    color: TEAL, charSpacing: 3, margin: 0, isTextBox: true });
}
function title(slide, text, y = 0.72, color = TEXT, size = 30) {
  slide.addText(text, { x: 0.6, y, w: 12.1, h: 0.75, fontFace: HEAD, fontSize: size, bold: true,
    color, margin: 0, valign: "top", isTextBox: true });
}
function body(slide, text, x, y, w, h, opts = {}) {
  slide.addText(text, Object.assign({ x, y, w, h, fontFace: BODY, fontSize: 15, color: TEXT,
    valign: "top", margin: 0, isTextBox: true }, opts));
}
function card(slide, x, y, w, h, fill = MINT) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill },
    line: { color: fill }, rectRadius: 0.08 });
}
function dot(slide, n, x, y, d = 0.42, fill = TEAL) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill } });
  slide.addText(String(n), { x, y, w: d, h: d, align: "center", valign: "middle", fontFace: BODY,
    fontSize: 13, bold: true, color: WHITE, margin: 0, isTextBox: true });
}
function bullets(slide, items, x, y, w, h, size = 15) {
  slide.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } })),
    { x, y, w, h, fontFace: BODY, fontSize: size, color: TEXT, valign: "top", margin: 0,
      paraSpaceAfter: 6, isTextBox: true });
}
function footer(slide, text) {
  slide.addText(text, { x: 0.6, y: 7.02, w: 12.1, h: 0.3, fontFace: BODY, fontSize: 10.5,
    color: MUTED, margin: 0, isTextBox: true });
}

// ---------------------------------------------------------------- 1 title
{
  const s = pres.addSlide(); s.background = { color: INK };
  s.addText("NIMO", { x: 0.8, y: 1.35, w: 7, h: 1.2, fontFace: HEAD, fontSize: 80, bold: true,
    color: WHITE, margin: 0, isTextBox: true });
  s.addText("The Product Truth Agent", { x: 0.8, y: 2.6, w: 8, h: 0.7, fontFace: HEAD,
    fontSize: 32, color: MINT_T, margin: 0, isTextBox: true });
  s.addText("Finds the web page that is the product, codes its characteristics, and shows the evidence for every answer.",
    { x: 0.8, y: 3.55, w: 7.4, h: 1.0, fontFace: BODY, fontSize: 19, color: "DCE8EA", margin: 0, isTextBox: true });
  s.addText("Team Matrix Slayers  ·  NielsenIQ Innovation Portal hackathon  ·  September 2026",
    { x: 0.8, y: 6.45, w: 9, h: 0.4, fontFace: BODY, fontSize: 14, color: "A9C2C6", margin: 0, isTextBox: true });
  const stages = ["Normalize", "Registry memory", "Retrieve", "Fetch & extract", "Match", "Classify module",
    "Characteristics", "Reason", "Assemble"];
  stages.forEach((name, i) => {
    const y = 0.75 + i * 0.66;
    if (i < stages.length - 1) s.addShape(pres.shapes.LINE, { x: 9.66, y: y + 0.42, w: 0, h: 0.24,
      line: { color: "3E6B73", width: 1.5 } });
    dot(s, i, 9.45, y, 0.42, i === 1 ? AMBER : TEAL);
    s.addText(name, { x: 10.05, y, w: 2.9, h: 0.42, fontFace: BODY, fontSize: 14, color: "DCE8EA",
      valign: "middle", margin: 0, isTextBox: true });
  });
  s.addNotes("NIMO resolves a retail product record to the one web page that is that product, identifies its module, codes the characteristics that apply, and explains every answer from recorded evidence. The column on the right is the pipeline you will see in the demo; stage 1, in amber, is the memory that lets repeat products skip the expensive stages.");
}

// ---------------------------------------------------------------- 2 problem
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "THE PROBLEM");
  title(s, "One product, many pages — which one is true?");
  body(s, "The same toothpaste appears on retailers, marketplaces, brand sites and barcode directories under different names, sizes and promotions. The task has two stages, and the second is where most of the score lives.",
    0.6, 1.65, 12.1, 0.8, { fontSize: 16, color: MUTED });
  const steps = [
    ["Find the page", "the single URL that is this product — not a look-alike, a listing or a homepage"],
    ["Identify the module", "one of 59 oral-care modules, e.g. TOOTH CLEANING - PASTE"],
    ["Decide what applies", "which of the 13 characteristics exist for that module — the rest must stay empty"],
    ["Code the values", "from page, image and guideline evidence, inside the organizers' vocabulary"],
  ];
  steps.forEach(([h, d], i) => {
    const x = 0.6 + i * 3.1;
    card(s, x, 2.75, 2.8, 2.35);
    dot(s, i + 1, x + 0.25, 2.97);
    body(s, h, x + 0.25, 3.55, 2.35, 0.4, { fontSize: 17, bold: true, color: TEAL_D });
    body(s, d, x + 0.25, 3.98, 2.35, 1.05, { fontSize: 13.5 });
    if (i < 3) s.addShape(pres.shapes.LINE, { x: x + 2.82, y: 3.92, w: 0.26, h: 0,
      line: { color: TEAL, width: 2.25, endArrowType: "triangle" } });
  });
  body(s, "Judged on", 0.6, 5.5, 2, 0.35, { fontSize: 14, bold: true, color: MUTED });
  ["the right URL", "not fooled by similar or misleading matches", "clear, transparent reasoning", "beyond keyword matching"]
    .forEach((t, i) => {
      const w = [1.7, 3.9, 2.9, 2.6][i], x = [0.6, 2.45, 6.5, 9.55][i];
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 5.9, w, h: 0.5, fill: { color: WHITE },
        line: { color: TEAL, width: 1.25 }, rectRadius: 0.25 });
      s.addText(t, { x, y: 5.9, w, h: 0.5, align: "center", valign: "middle", fontFace: BODY,
        fontSize: 13.5, color: TEAL_D, margin: 0, isTextBox: true });
    });
  s.addNotes("From the brief: the agent must choose the most likely product URL, distinguish it from similar or misleading matches, and explain itself. The dataset guide adds the second stage — module, applicable characteristics, values. A non-applicable characteristic must be left empty; a plausible guess there is scored as wrong.");
}

// ---------------------------------------------------------------- 3 data defects
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "WHAT THE DATA ACTUALLY GAVE US");
  title(s, "We measured the dataset before designing anything");
  const cards = [
    ["0", "candidate web pages supplied — PRODUCT_URL is empty in every row", "Built our own retrieval: 5 query strategies, fetch, extract"],
    ["377 / 412", "dev barcodes destroyed by an Excel number format (rounded to 3 digits)", "A rounded barcode is never used as an identifier"],
    ["3 columns", "EXTERNAL_CODE, NAN_KEY and ITEM_CODE all carry the rounding — NAN_KEY collides across products", "Row identity is our own row_uid, never NAN_KEY"],
    ["187", "ground-truth values are '&'-joined (e.g. ANTI BACTERIAL & WHITENING)", "Validation per component — the organizers' own answers pass"],
    ["21 / 50", "retailer strings a regex mis-parses — one silently: 'BOOTS (GB) (HOMESCAN)' → '(HOMESCAN)'", "A hand-reviewed 50-entry table instead of a pattern"],
    ["0", "rows with URL ground truth", "Evaluation from the barcode itself: a page's GTIN confirms or refutes it"],
  ];
  cards.forEach(([n, what, did], i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.6 + col * 4.1, y = 1.7 + row * 2.62;
    card(s, x, y, 3.85, 2.42);
    body(s, n, x + 0.25, y + 0.18, 3.4, 0.62, { fontFace: HEAD, fontSize: 30, bold: true, color: CORAL });
    body(s, what, x + 0.25, y + 0.84, 3.4, 0.82, { fontSize: 13 });
    body(s, "→ " + did, x + 0.25, y + 1.68, 3.4, 0.62, { fontSize: 12.5, bold: true, color: TEAL_D });
  });
  s.addNotes("Every one of these was found by measuring the real workbook, and each changed the design. The barcode rounding is the big one: 377 of 412 dev barcodes are holes, while qa's are clean — so dev cannot be used to tune anything barcode-based, and a rounded value used as a key would merge unrelated products.");
}

// ---------------------------------------------------------------- 4 architecture
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "ARCHITECTURE");
  title(s, "Eight deterministic stages; the model is a bounded part");
  const top = [
    ["0", "Normalize", "brand, size, pack count, variant words; every stripped token recorded"],
    ["1", "Registry memory", "Tier 0 by barcode, Tier 1 by identity within a block; a hit skips search"],
    ["2", "Retrieve", "5 strategies via Brave Search API or self-hosted SearxNG, cache-first"],
    ["3", "Fetch & extract", "robots, pacing, SSRF check per redirect; JSON-LD first"],
    ["4", "Match", "hard rules, calibrated score; Tier 3 model tiebreak picks an index"],
  ];
  const bottom = [
    ["5", "Classify module", "char-4-gram nearest centroid; cites its nearest labelled row"],
    ["6", "Characteristics", "applicability gate, one model call with the pack shot, validator"],
    ["7", "Reason", "composed from the typed record — every clause tagged with its source"],
    ["8", "Assemble", "exact qa schema, byte-identical xlsx + csv, explorer page"],
  ];
  const draw = (items, y, x0) => items.forEach(([n, h, d], i) => {
    const x = x0 + i * 2.5;
    const llm = n === "4" || n === "6";
    card(s, x, y, 2.3, 1.95, n === "1" ? "FCEFE1" : MINT);
    dot(s, n, x + 0.18, y + 0.18, 0.4, n === "1" ? AMBER : TEAL);
    body(s, h, x + 0.68, y + 0.2, 1.55, 0.4, { fontSize: 14.5, bold: true, color: TEXT, valign: "middle" });
    body(s, d, x + 0.18, y + 0.72, 1.98, 1.15, { fontSize: 11.5, color: TEXT });
    if (llm) {
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 1.62, y: y - 0.16, w: 0.62, h: 0.3,
        fill: { color: AMBER }, line: { color: AMBER }, rectRadius: 0.15 });
      s.addText("LLM", { x: x + 1.62, y: y - 0.16, w: 0.62, h: 0.3, align: "center", valign: "middle",
        fontFace: BODY, fontSize: 10.5, bold: true, color: WHITE, margin: 0, isTextBox: true });
    }
    if (i < items.length - 1) s.addShape(pres.shapes.LINE, { x: x + 2.3, y: y + 0.97, w: 0.2, h: 0,
      line: { color: TEAL, width: 2, endArrowType: "triangle" } });
  });
  draw(top, 1.85, 0.6);
  draw(bottom, 4.55, 1.85);
  // Match (top right) -> down, left along y=4.22, down into Classify (bottom left)
  s.addShape(pres.shapes.LINE, { x: 11.75, y: 3.8, w: 0, h: 0.42, line: { color: TEAL, width: 2 } });
  s.addShape(pres.shapes.LINE, { x: 3.0, y: 4.22, w: 8.75, h: 0, line: { color: TEAL, width: 2 } });
  s.addShape(pres.shapes.LINE, { x: 3.0, y: 4.22, w: 0, h: 0.31, line: { color: TEAL, width: 2, endArrowType: "triangle" } });
  // Registry hit shortcut: from box 1 straight down onto that path
  s.addShape(pres.shapes.LINE, { x: 4.25, y: 3.8, w: 0, h: 0.42, line: { color: AMBER, width: 2.25, dashType: "dash" } });
  body(s, "registry hit: skip stages 2, 3, 4", 4.4, 3.86, 3.2, 0.32, { fontSize: 12, bold: true, color: AMBER });
  footer(s, "Every stage writes a typed artifact keyed by row_uid: resumable after any interruption, and a warm re-run produces a byte-identical submission.");
  s.addNotes("Nine boxes, stage 0 to 8. The model appears in exactly two places, both bounded: the Tier-3 tiebreak, whose answer is an index into candidates the deterministic layer already chose, and characteristic extraction, whose answer is validated against the organizers' vocabulary. A registry hit jumps from stage 1 straight to classification.");
}

// ---------------------------------------------------------------- 5 pipeline vs agent
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "DESIGN STANCE");
  title(s, "Why a pipeline, not an autonomous agent");
  const hdr = (t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: TEAL }, fontSize: 14 } });
  const rows = [
    [hdr(""), hdr("Autonomous agent loop"), hdr("NIMO pipeline")],
    ["Reproducible", "a different trajectory every run", "same input → same output; warm re-run byte-identical"],
    ["Debuggable", "a transcript", "a typed record per stage: which feature misfired is visible"],
    ["Cost", "model reads every candidate page", "rules first; the model sees ≤ 3 structured candidates, only when needed"],
    ["Transparent", "chain-of-thought", "reasoning composed from recorded fields, each clause cited"],
    ["Safe", "page text can steer the agent", "page text is delimited data; the model's answer is an index, never a URL"],
  ].map((r, i) => i === 0 ? r : r.map((c, j) => ({ text: c, options: { bold: j === 0, color: j === 0 ? TEAL_D : TEXT,
    fill: { color: i % 2 ? WHITE : "F3F8F7" }, fontSize: 13.5 } })));
  s.addTable(rows, { x: 0.6, y: 1.75, w: 12.1, colW: [2.1, 4.4, 5.6], rowH: 0.6, fontFace: BODY,
    border: { type: "solid", pt: 0.75, color: LINE }, valign: "middle", margin: [0.04, 0.12, 0.04, 0.12] });
  card(s, 0.6, 5.65, 12.1, 1.15, "FCEFE1");
  body(s, "Considered and rejected on measurement: a learned GNN (no multi-hop structure, 412 rows cannot train it — Union-Find gives the graph answer with no training), hyperbolic RAG (the taxonomy is 3 levels, fully enumerable), pure-LLM ranking of raw HTML (discards the barcode, size and pack-count signals that decide identity).",
    0.85, 5.78, 11.6, 0.95, { fontSize: 13 });
  s.addNotes("The brief rewards transparent reasoning and the evaluation is a 412-row batch, so reproducibility and per-stage traceability decide the architecture. The model is used where it adds judgement, and is fenced so it cannot introduce a URL or a value outside the allowed set.");
}

// ---------------------------------------------------------------- 6 registry
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "MEMORY");
  title(s, "Resolve once, answer from memory: the entity registry");
  const hdr = (t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: TEAL }, fontSize: 13 } });
  const tiers = [
    [hdr("Tier"), hdr("Trigger"), hdr("Cost")],
    ["0 · exact", "barcode already resolved", "milliseconds"],
    ["1 · similar", "identity similarity ≥ 0.75 inside a size/brand block", "milliseconds"],
    ["2 · retrieval", "miss — search, fetch, match", "seconds"],
    ["3 · model", "top candidates too close to call", "one call"],
  ].map((r, i) => i === 0 ? r : r.map((c, j) => ({ text: c, options: { bold: j === 0, fontSize: 13,
    color: j === 0 ? TEAL_D : TEXT, fill: { color: i % 2 ? WHITE : "F3F8F7" } } })));
  s.addTable(tiers, { x: 0.6, y: 1.8, w: 7.3, colW: [1.6, 4.1, 1.6], rowH: 0.52, fontFace: BODY,
    border: { type: "solid", pt: 0.75, color: LINE }, valign: "middle", margin: [0.04, 0.12, 0.04, 0.12] });
  bullets(s, [
    "Confirmed-same products are merged with Union-Find — deterministic, no training data.",
    "Written only on barcode-confirmed identity, and every write is audit-logged.",
    "Tier 1 is precision-first: on 20 hand-checked pairs it accepts 3 of 4 true duplicates and 0 of 14 look-alikes (Sensodyne Pronamel Extra Fresh vs Whitening differ by two words).",
  ], 0.6, 4.6, 7.3, 2.3, 14);
  card(s, 8.4, 1.8, 4.3, 4.9, INK);
  body(s, "111 of 412", 8.7, 2.2, 3.8, 0.9, { fontFace: HEAD, fontSize: 40, bold: true, color: WHITE });
  body(s, "qa rows answered straight from the registry on the re-run — search, fetch and match skipped", 8.7, 3.15, 3.7, 1.2, { fontSize: 15, color: "DCE8EA" });
  body(s, "115", 8.7, 4.55, 3.8, 0.7, { fontFace: HEAD, fontSize: 32, bold: true, color: MINT_T });
  body(s, "resolved products in memory, each with the rows folded into it and the page that proved it", 8.7, 5.25, 3.7, 1.2, { fontSize: 14, color: "DCE8EA" });
  s.addNotes("Production catalogs repeat. Without memory every re-observation costs the full search and model bill. The registry turns a second sighting into a lookup. Tier 0 cannot fire inside a single pass of this dataset — no two qa rows share a barcode — so its value shows on the re-run, where it answered 111 rows from memory.");
}

// ---------------------------------------------------------------- 7 retrieval
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "RETRIEVAL");
  title(s, "Finding candidates on a real, hostile web");
  const strat = [
    ["S2", "barcode + brand", "finds the retailers that publish structured data"],
    ["S3", "brand + variant + size", "the product-name query"],
    ["S4", "site:retailer", "the row's own retailer domain"],
    ["S5", "description verbatim", "fallback"],
    ["S1", "bare barcode", "last — digit strings match phone prefixes"],
  ];
  strat.forEach(([k, q, why], i) => {
    const y = 1.8 + i * 0.62;
    dot(s, k, 0.6, y, 0.46);
    body(s, q, 1.2, y + 0.02, 2.6, 0.42, { fontSize: 14.5, bold: true, valign: "middle" });
    body(s, why, 3.75, y + 0.02, 2.9, 0.42, { fontSize: 12.5, color: MUTED, valign: "middle" });
  });
  bullets(s, [
    "Free engines, engineered: rotation, per-engine circuit breaker, early exit, cache — 412 qa rows in 107 minutes, zero failures.",
    "Brave Search API when Docker is unavailable: cache-first over every harvested answer, capped per run.",
    "Pages about the product — homepages, listings, barcode directories — never fill the fetch budget.",
  ], 0.6, 5.0, 6.1, 1.95, 13.5);
  s.addChart(pres.charts.BAR, [
    { name: "Before the fix", labels: ["Product page", "Brand homepage", "Directory", "Search listing"], values: [271, 100, 36, 5] },
    { name: "After", labels: ["Product page", "Brand homepage", "Directory", "Search listing"], values: [377, 0, 35, 0] },
  ], { x: 7.0, y: 1.7, w: 5.7, h: 4.9, barDir: "col", barGrouping: "clustered", chartColors: [GREYBAR, TEAL],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: TEXT,
    showLegend: true, legendPos: "b", legendFontSize: 12, catAxisLabelFontSize: 12, catAxisLabelColor: TEXT,
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showTitle: true, title: "What the 412 qa answers point at", titleFontSize: 14, titleColor: TEXT });
  s.addNotes("The dataset gave us no candidate pages, so retrieval is ours. Measured on our own output: 100 of 412 qa answers were brand homepages, because the barcode query returned the brand's homepage and those filled the fetch budget before the product-name query ran. Pages about the product no longer count toward the budget; homepages went from 100 to zero and product pages from 271 to 377.");
}

// ---------------------------------------------------------------- 8 matching + calibration
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "MATCHING");
  title(s, "Hard rules first, then a score that means a probability");
  const rules = [
    ["Page GTIN = our barcode", "accept — identity by identifier", TEAL],
    ["Page GTIN ≠ our barcode", "reject — however similar the text", CORAL],
    ["Size or pack count differ", "demote — 2-pack ≠ single, 75 ml ≠ 100 ml", AMBER],
    ["Refill, travel, bundle, sample", "demote — a different SKU of the line", AMBER],
    ["Homepage, listing, directory", "demote — about the product, not of it", AMBER],
  ];
  rules.forEach(([c, o, col], i) => {
    const y = 1.8 + i * 0.86;
    card(s, 0.6, y, 6.0, 0.72, "F3F8F7");
    s.addShape(pres.shapes.OVAL, { x: 0.8, y: y + 0.24, w: 0.24, h: 0.24, fill: { color: col }, line: { color: col } });
    body(s, c, 1.2, y + 0.08, 2.7, 0.56, { fontSize: 14, bold: true, valign: "middle" });
    body(s, o, 3.9, y + 0.08, 2.6, 0.56, { fontSize: 12.5, color: MUTED, valign: "middle" });
  });
  body(s, "Everything else: weighted brand, variant, format, retailer and market features — market is scored, never a filter.",
    0.6, 6.2, 6.0, 0.7, { fontSize: 13, color: MUTED });
  s.addChart(pres.charts.BAR, [{ name: "Observed correct", labels: ["< 0.13", "0.13–0.45", "0.45–0.55", "0.55–0.60", "0.60–0.63", "0.63–0.90", "≥ 0.90"],
    values: [0, 35, 68, 72, 81, 93, 100] }], {
    x: 7.0, y: 1.7, w: 5.7, h: 4.6, barDir: "col", chartColors: [TEAL], showValue: true,
    dataLabelPosition: "outEnd", dataLabelFormatCode: '0"%"', dataLabelFontSize: 11, dataLabelColor: TEXT,
    showLegend: false, catAxisLabelFontSize: 11, catAxisLabelColor: TEXT, valAxisHidden: true,
    valAxisMaxVal: 110, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showTitle: true, title: "Raw text score → probability the page is the product", titleFontSize: 14, titleColor: TEXT,
    showCatAxisTitle: true, catAxisTitle: "raw match score", catAxisTitleFontSize: 11, catAxisTitleColor: MUTED });
  body(s, "Isotonic fit on 236 pages whose own barcode labels them right or wrong · held-out calibration error 0.068",
    7.0, 6.35, 5.7, 0.55, { fontSize: 12, color: MUTED });
  s.addNotes("The barcode is the strongest identity signal, so it is a rule, not a weight. For pages without one, the weighted score is calibrated: we fitted it against 236 pages that publish a barcode, so 'confidence 0.93' means about 93 in 100 such picks are the product. The label comes from the identifier, not from the score, so the oracle cannot leak into what it measures.");
}

// ---------------------------------------------------------------- 9 module classification
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "MODULE CLASSIFICATION");
  title(s, "80.3% module accuracy — a model chosen on the long tail");
  s.addChart(pres.charts.BAR, [
    { name: "Overall accuracy", labels: ["TF-IDF nearest centroid (shipped)", "Complement NB", "Multinomial NB", "k-NN (k = 1)"], values: [80.3, 78.4, 73.1, 66.3] },
    { name: "Macro (per-module) accuracy", labels: ["TF-IDF nearest centroid (shipped)", "Complement NB", "Multinomial NB", "k-NN (k = 1)"], values: [49.7, 38.3, 22.6, 32.1] },
  ], { x: 0.6, y: 1.65, w: 7.0, h: 5.2, barDir: "col", barGrouping: "clustered", chartColors: [TEAL, AMBER],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: '0.0"%"', dataLabelFontSize: 11,
    dataLabelColor: TEXT, showLegend: true, legendPos: "b", legendFontSize: 12, catAxisLabelFontSize: 11.5,
    catAxisLabelColor: TEXT, valAxisHidden: true, valAxisMaxVal: 95, valGridLine: { style: "none" },
    catGridLine: { style: "none" } });
  const pts = [
    ["Macro is the headline", "The top 4 modules are 77% of rows. Complement NB is within 2 points overall and 11 behind on macro — it buys the head by dropping the tail."],
    ["Character 4-grams, not words", "+8 points: the data writes toothpaste as 'tooth paste', 't/paste', 'pste'."],
    ["BRAND measured out", "Adding it costs 7.5 points: Oral-B makes brushes, heads and paste."],
    ["It cites its evidence", "Each prediction names its nearest labelled row — a citation a person can open."],
  ];
  pts.forEach(([h, d], i) => {
    const y = 1.75 + i * 1.3;
    body(s, h, 8.0, y, 4.7, 0.38, { fontSize: 15, bold: true, color: TEAL_D });
    body(s, d, 8.0, y + 0.4, 4.7, 0.85, { fontSize: 12.5 });
  });
  s.addNotes("MODULE is the only fully labelled column, so this is where we could measure properly. We report macro accuracy first because overall accuracy would have picked a model that ignores the rare modules. Adding page titles as module evidence was also measured on the full dev harvest and lost accuracy, so the module comes from the description.");
}

// ---------------------------------------------------------------- 10 characteristics
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "CHARACTERISTICS");
  title(s, "The model proposes, the vocabulary disposes");
  const pts = [
    ["Applicability gate — ours, before and after the model", "Only characteristics that apply to the module are asked; a volunteered one is dropped. Under predicted modules: precision 0.955, recall 0.928."],
    ["One call per row, with the pack shot", "Only that row's guidelines, the page excerpt around ingredients and pack terms, and the product image (636 of 824 rows have one)."],
    ["Validated against the organizers' list", "Per '&' component: reproduces their counts exactly — 1,719 values accepted, the 2 known data errors refused."],
    ["Practice over prose where they differ", "Measured defaults where the coders' practice departs from the written guideline (e.g. fluoride)."],
  ];
  pts.forEach(([h, d], i) => {
    const y = 1.75 + i * 1.28;
    dot(s, i + 1, 0.6, y, 0.42);
    body(s, h, 1.2, y, 4.6, 0.42, { fontSize: 14.5, bold: true, color: TEAL_D, valign: "middle" });
    body(s, d, 1.2, y + 0.45, 4.6, 0.8, { fontSize: 12.5 });
  });
  s.addImage({ path: A("card_qa28_model.png"), x: 6.2, y: 1.7, w: 6.5, h: 4.06 });
  body(s, "qa:28, real output from the model on the NIQ network: Green People children's mandarin & aloe vera toothpaste → BABY & CHILD · TUBE · 100% · MILK TEETH · WITHOUT FLUORIDE · ALOE VERA & MANDARIN",
    6.2, 5.85, 6.5, 0.9, { fontSize: 12, color: MUTED });
  s.addNotes("Characteristics are most of the scored surface. The applicability gate is deterministic, so the model can never fill a characteristic that does not exist for the module. Every value it proposes is checked against the organizers' vocabulary; what it said and was refused is recorded. The screenshot is a real row from our office run on the internal model.");
}

// ---------------------------------------------------------------- 11 reasoning
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "REASONING");
  title(s, "Reasoning composed from recorded fields — never generated");
  card(s, 0.6, 1.75, 7.6, 3.55, "F3F8F7");
  body(s, "“The selected page (superdrug.com) was ranked first on brand match 1.00, variant overlap 0.80 (teeth, whitening, week, charcoal), ahead of the runner-up by 0.19 (calibrated probability 0.93). Classified as TOOTH STAIN REMOVERS - POWDER from the description, which most resembles dev:98 (similarity 0.30). … Page evidence used: structured product data (JSON-LD), the page title, 5635 characters of page text.”",
    0.9, 1.95, 7.0, 2.6, { fontSize: 15.5, italic: true });
  body(s, "qa:0 — BRILLIANT teeth whitening 1 week charcoal kit. The brand word also found paint pages and a tutoring site; the matcher ranked the Superdrug product page first.",
    0.9, 4.55, 7.0, 0.7, { fontSize: 12, color: MUTED });
  const tags = ["selection.url", "selection.brand_match", "selection.variant_overlap", "selection.runner_up_gap",
    "selection.calibrated_prob", "module.module", "module.nearest_example", "evidence.fields"];
  body(s, "Provenance tags stored with the text", 0.6, 5.55, 7.6, 0.35, { fontSize: 13, bold: true, color: MUTED });
  tags.forEach((t, i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = 0.6 + col * 1.92, y = 5.95 + row * 0.5;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 1.82, h: 0.38, fill: { color: MINT },
      line: { color: MINT }, rectRadius: 0.19 });
    s.addText(t, { x, y, w: 1.82, h: 0.38, align: "center", valign: "middle", fontFace: BODY,
      fontSize: 10, color: TEAL_D, margin: 0, isTextBox: true });
  });
  const g = [
    ["No invented claims", "Every number in the text is a field's value — tested."],
    ["No injection surface", "Page text is never quoted; only validated fields are cited."],
    ["Absence is stated, not guessed", "“No evidence for FLUORIDE; left empty” — as in the organizers' own sample."],
  ];
  g.forEach(([h, d], i) => {
    const y = 1.8 + i * 1.6;
    card(s, 8.6, y, 4.1, 1.42);
    body(s, h, 8.85, y + 0.18, 3.6, 0.4, { fontSize: 15, bold: true, color: TEAL_D });
    body(s, d, 8.85, y + 0.6, 3.6, 0.75, { fontSize: 13 });
  });
  s.addNotes("The brief scores transparent reasoning. A generated explanation can say something no evidence supports; a composed one cannot, because it can only render fields the pipeline recorded. The test suite checks that every number in the text is the string form of a field, and that a record with no fluoride evidence produces no fluoride claim.");
}

// ---------------------------------------------------------------- 12 prototype
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "THE WORKING PROTOTYPE");
  title(s, "Three ways to use it");
  s.addImage({ path: A("card_qa0.png"), x: 0.6, y: 1.65, w: 7.4, h: 4.63 });
  body(s, "Results explorer: every row's evidence, stage by stage — one HTML file, opens with no server.", 0.6, 6.35, 7.4, 0.5, { fontSize: 12, color: MUTED });
  const ways = [
    ["Live interface", "Run any dataset row, or type a new product and watch it resolve end to end.", "uv run python -m nimo.ui --live"],
    ["Results explorer", "The whole 412-row run in one self-contained page, searchable and filterable.", "uv run python -m nimo.site --sheet qa"],
    ["Your own Excel file", "Any .xlsx / .csv with RETAILER_DESC and BRAND, through the same pipeline.", "uv run python -m nimo.run --input my.xlsx --live"],
  ];
  ways.forEach(([h, d, cmd], i) => {
    const y = 1.7 + i * 1.72;
    card(s, 8.35, y, 4.35, 1.55);
    body(s, h, 8.6, y + 0.15, 3.9, 0.38, { fontSize: 15.5, bold: true, color: TEAL_D });
    body(s, d, 8.6, y + 0.53, 3.9, 0.55, { fontSize: 12.5 });
    body(s, cmd, 8.6, y + 1.1, 3.95, 0.34, { fontFace: "Courier New", fontSize: 9.5, color: INK });
  });
  s.addNotes("The interface runs the same composed pipeline as the batch CLI — it adds nothing that could drift. In the demo: a dataset row, then the same row again to show the registry answering from memory, then a new product typed in and resolved live through the Brave Search API.");
}

// ---------------------------------------------------------------- 13 results
{
  const s = pres.addSlide(); s.background = { color: INK };
  s.addText("RESULTS AT A GLANCE", { x: 0.6, y: 0.42, w: 8, h: 0.3, fontFace: BODY, fontSize: 12, bold: true,
    color: MINT_T, charSpacing: 3, margin: 0, isTextBox: true });
  title(s, "Measured, not asserted", 0.72, WHITE);
  const stats = [
    ["412 / 412", "qa rows resolved end to end"],
    ["114", "answers confirmed by the page's own barcode"],
    ["111", "rows answered from registry memory on re-run"],
    ["0", "brand homepages submitted (was 100)"],
    ["80.3%", "module accuracy, leave-one-out (49.7% macro)"],
    ["0.068", "held-out calibration error of the match score"],
    ["68.6%", "characteristics, first run, record-only — before page evidence and practice defaults"],
    ["827", "automated tests, zero network — strict typing"],
  ];
  stats.forEach(([n, l], i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = 0.6 + col * 3.07, y = 1.85 + row * 2.55;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 2.85, h: 2.3, fill: { color: "123C47" },
      line: { color: "123C47" }, rectRadius: 0.08 });
    s.addText(n, { x: x + 0.22, y: y + 0.25, w: 2.45, h: 0.85, fontFace: HEAD, fontSize: 34, bold: true,
      color: i === 3 ? MINT_T : WHITE, margin: 0, isTextBox: true });
    s.addText(l, { x: x + 0.22, y: y + 1.15, w: 2.45, h: 1.05, fontFace: BODY, fontSize: 13.5,
      color: "C9DADD", valign: "top", margin: 0, isTextBox: true });
  });
  s.addNotes("Each number is recorded in the decision log with how it was measured. The 68.6% characteristic figure is the honest first measurement: it came from a run on a network that blocked 94% of page fetches, so the model coded mostly from the record; the page cache and measured practice defaults were built for exactly that gap.");
}

// ---------------------------------------------------------------- 14 trust
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "BUILT TO BE TRUSTED");
  title(s, "Safety and engineering discipline");
  const left = [
    ["Untrusted page text is data", "delimited in every prompt; injection fixtures are a permanent test class"],
    ["The model cannot invent a URL", "its answer schema has an index, no URL field; out-of-range is refused"],
    ["SSRF checks on every redirect hop", "private and metadata addresses refused before connecting"],
    ["Pinned model, hard token budget", "a spent budget aborts the run instead of throttling silently"],
    ["Audit-logged memory", "every registry write is traceable and reversible"],
  ];
  const right = [
    ["Deterministic", "the submission xlsx was byte-identical across two different laptops"],
    ["Resumable", "one typed artifact per row per stage; an interruption loses nothing"],
    ["Fail loud", "one failure choke point; a failed row is blank, never half-filled"],
    ["Strict", "mypy --strict, ruff, 827 tests with zero network calls"],
    ["Every decision logged", "what was measured, what was rejected and why — docs/02-decision-log.md"],
  ];
  const col = (items, x) => items.forEach(([h, d], i) => {
    const y = 1.75 + i * 1.02;
    s.addShape(pres.shapes.OVAL, { x, y: y + 0.08, w: 0.3, h: 0.3, fill: { color: TEAL }, line: { color: TEAL } });
    body(s, h, x + 0.5, y, 5.3, 0.4, { fontSize: 15, bold: true, color: TEXT });
    body(s, d, x + 0.5, y + 0.4, 5.3, 0.55, { fontSize: 12.5, color: MUTED });
  });
  col(left, 0.6); col(right, 6.9);
  s.addNotes("The design has two exposed surfaces — web text reaching the model, and URLs we did not choose — and each has a structural control rather than a prompt instruction. On the engineering side, the strongest single check is determinism: the same run on two machines produced a byte-identical submission file.");
}

// ---------------------------------------------------------------- 15 limits
{
  const s = pres.addSlide(); s.background = { color: WHITE };
  kicker(s, "HONEST LIMITS AND NEXT STEPS");
  title(s, "What we know we have not solved");
  card(s, 0.6, 1.75, 5.9, 4.15, "FBEDEA");
  body(s, "Limits", 0.9, 1.95, 5.3, 0.4, { fontSize: 18, bold: true, color: CORAL });
  bullets(s, [
    "32 of 59 modules never appear in the labelled data, so the classifier cannot emit them (interdental brushes among them).",
    "The model is NIQ-internal and the NIQ network blocks most retail pages, so evidence is harvested outside and carried in as caches.",
    "The Tier-3 tiebreak's gain is not yet measured with page evidence in hand.",
    "Many retailers serve bot walls to any polite crawler (156 hosts in the last run).",
  ], 0.9, 2.45, 5.35, 4.2, 14);
  card(s, 6.8, 1.75, 5.9, 4.15, MINT);
  body(s, "Next", 7.1, 1.95, 5.3, 0.4, { fontSize: 18, bold: true, color: TEAL_D });
  bullets(s, [
    "Unseen modules from page evidence: the lever is measured (qa:259), the stage that reads pages is where it belongs.",
    "Run the whole pipeline inside one network that reaches both the model and the web.",
    "Confirm with the organizers: URL vs page title in PRODUCT_URL, and how a blank URL is scored against a wrong one (abstention is built, switched off).",
    "Grow the registry across catalogs — every resolved product makes the next sighting a lookup.",
  ], 7.1, 2.45, 5.35, 4.2, 14);
  s.addNotes("We would rather state these than have them found. The biggest structural one is the unseen modules; the biggest environmental one is that the model and the open web live on different networks, which we bridged with carried caches rather than hid.");
}

// ---------------------------------------------------------------- 16 close
{
  const s = pres.addSlide(); s.background = { color: INK };
  s.addText("Thank you", { x: 0.8, y: 1.5, w: 8, h: 1.1, fontFace: HEAD, fontSize: 54, bold: true,
    color: WHITE, margin: 0, isTextBox: true });
  s.addText("NIMO — the Product Truth Agent · Team Matrix Slayers", { x: 0.8, y: 2.7, w: 10, h: 0.5,
    fontFace: BODY, fontSize: 20, color: MINT_T, margin: 0, isTextBox: true });
  s.addText([
    { text: "Code, docs and decision log", options: { bold: true, color: WHITE, breakLine: true } },
    { text: "github.com/Nexxex-Aditya/NIMO", options: { color: "C9DADD", breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "Run it", options: { bold: true, color: WHITE, breakLine: true } },
    { text: "uv sync  ·  uv run python -m nimo.ui --live", options: { color: "C9DADD", fontFace: "Courier New" } },
  ], { x: 0.8, y: 3.7, w: 10, h: 2.2, fontFace: BODY, fontSize: 17, margin: 0, valign: "top", isTextBox: true });
  s.addNotes("Everything shown is in the repository, including the decision log that records every measurement and every rejected alternative.");
}

pres.writeFile({ fileName: path.join(__dirname, "NIMO_Product_Truth_Agent.pptx") })
  .then((f) => console.log("written " + f));
