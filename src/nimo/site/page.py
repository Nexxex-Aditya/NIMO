# ruff: noqa: E501 — embedded HTML/JS; wrapping it would make it less readable, not more
"""The explorer page template. Vanilla HTML/CSS/JS, no external assets, no
network: the data is embedded as JSON and everything renders in the browser.
Placeholders: `__TITLE__`, `__STYLE__` and `__CARD_JS__` (shared with the live
UI, `nimo.ui.page`), `__DATA__` (the run, as JSON).
"""

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
__STYLE__
  header { flex-wrap:wrap }
  .num { display:inline-block; margin:4px 14px 4px 0 } .num b { font-size:20px; font-weight:700; margin-right:4px }
  .filters { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin:6px 0 }
  .filters label { font-size:12px; color:var(--muted) }
  .rows { max-height:60vh }
  .rows .brand { font-weight:600; margin-right:4px }
  .head { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; margin-bottom:6px }
  .head h3 { margin:0; font-size:16px }
  .notes li { margin:3px 0 }
  .reg { max-height:38vh; overflow:auto }
  .empty { color:var(--muted); padding:24px 0; text-align:center }
  footer { padding:14px 22px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); background:#fff }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="sub">NIMO — the Product Truth Agent · a read-only view of one run. Every line names the pipeline stage it came from; nothing on this page was computed after the run.</span>
</header>
<main>
  <section>
    <div class="panel">
      <h2>The run</h2>
      <div id="numbers"></div>
      <ul class="notes" id="notes"></ul>
    </div>
    <div class="panel" style="margin-top:14px">
      <h2>Rows</h2>
      <input id="q" placeholder="search brand, description, module, URL, row id…">
      <div class="filters">
        <div><label>resolution tier</label><select id="f-tier"><option value="">any</option></select></div>
        <div><label>module</label><select id="f-module"><option value="">any</option></select></div>
        <div><label>identity</label><select id="f-identity"><option value="">any</option><option value="gtin">GTIN-confirmed</option><option value="adj">adjudicated (Tier 3)</option><option value="image">pack shot examined</option><option value="failed">failed rows</option></select></div>
        <div><label>&nbsp;</label><button class="ghost" id="clear" style="width:100%">clear</button></div>
      </div>
      <div class="muted" id="count"></div>
      <div class="rows" id="rows"></div>
    </div>
    <div class="panel" style="margin-top:14px">
      <h2>Registry — resolved products</h2>
      <div id="registry" class="reg"></div>
    </div>
  </section>
  <section>
    <div class="panel">
      <div class="head" id="head"><h3>Pick a row</h3><span class="muted">the record, then every stage's output in pipeline order</span></div>
      <div id="card"><div class="empty">Select a row on the left.</div></div>
    </div>
    <div class="panel" style="margin-top:14px">
      <h2>How to read a card</h2>
      <div class="muted">
        <b>normalize</b> — the retailer description parsed into brand, size, count, variant words. &nbsp;
        <b>registry</b> — <span class="tier tier0_exact">tier0_exact</span> means this product was resolved before and its answer was remembered; stages 2–4 were skipped. &nbsp;
        <b>retrieve / fetch</b> — the candidate pages found and what each yielded (a GTIN on the page is the strongest identity signal). &nbsp;
        <b>match</b> — why one page won: an exact GTIN, or the weighted features; <span class="tier tier3_llm">Tier 3</span> means the model broke a tie by pointing at one of the fixed candidates. &nbsp;
        <b>classify</b> — the module, with the labelled row it most resembles. &nbsp;
        <b>characteristics</b> — only the ones that apply to the module; values validated against the organizers' vocabulary; what the validator refused is shown. &nbsp;
        <b>reason</b> — composed from the fields above, each clause tagged with its source.
      </div>
    </div>
  </section>
</main>
<footer id="foot"></footer>
<script id="nimo-data" type="application/json">__DATA__</script>
<script>
const $ = (s) => document.querySelector(s);
__CARD_JS__
const DATA = JSON.parse($('#nimo-data').textContent);
const ROWS = DATA.rows.map(c => ({ c, text: [c.row_uid, c.query.brand, c.query.desc_raw, c.classify.module, c.match.url || '', c.query.retailer].join(' ').toLowerCase() }));
const FAILED = DATA.failures.map(f => ({ c: { row_uid: f.row_uid, failure: f, query: { brand: '', desc_raw: '' }, tier: 'failed', classify: { module: '' }, match: {}, characteristics: { values: {}, applicable: [], source: '' } }, text: (f.row_uid + ' failed ' + f.stage).toLowerCase() }));
let current = null;

function numbers() {
  const s = DATA.summary;
  const tiers = Object.entries(s.tiers).map(([k, v]) => `<span class="num"><b>${v}</b><span class="tier ${esc(k)}">${esc(k)}</span></span>`).join('');
  $('#numbers').innerHTML =
    `<div><span class="num"><b>${s.rows_complete}</b>of ${s.rows_total} rows resolved</span>${s.rows_failed ? `<span class="num bad"><b>${s.rows_failed}</b>failed</span>` : ''}</div>` +
    `<div>${tiers}</div>` +
    `<div><span class="num"><b>${s.gtin_confirmed}</b>identity confirmed by GTIN</span><span class="num"><b>${s.adjudicated}</b>rows sent to Tier 3</span><span class="num"><b>${s.decided_by_model}</b>decided by the model <span class="muted">(on the rest it saw no fit; Layer A's pick kept)</span></span><span class="num"><b>${s.rows_with_image}</b>pack shots examined</span></div>` +
    `<div><span class="num"><b>${s.coded_cells}</b>of ${s.applicable_cells} applicable characteristic cells coded</span><span class="num"><b>${s.modules}</b>modules</span><span class="num"><b>${DATA.registry.length}</b>registry entities</span></div>`;
  $('#notes').innerHTML = DATA.notes.map(n => `<li>${esc(n)}</li>`).join('');
  $('#foot').textContent = `sheet ${DATA.sheet} · generated ${DATA.generated_at} · config ${DATA.config_hash} · characteristics sources ${JSON.stringify(DATA.summary.characteristics_sources)}`;
}

function fillFilters() {
  const tiers = [...new Set(ROWS.map(r => r.c.tier))].sort();
  $('#f-tier').innerHTML += tiers.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
  const mods = [...new Set(ROWS.map(r => r.c.classify.module))].sort();
  $('#f-module').innerHTML += mods.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
}

function matches(r) {
  const q = $('#q').value.trim().toLowerCase();
  if (q && !r.text.includes(q)) return false;
  const tier = $('#f-tier').value; if (tier && r.c.tier !== tier) return false;
  const mod = $('#f-module').value; if (mod && r.c.classify.module !== mod) return false;
  const id = $('#f-identity').value;
  if (id === 'gtin') return r.c.tier === 'tier0_exact' || r.c.tier === 'tier1_ann' || ((r.c.match.features || {}).barcode_exact === true);
  if (id === 'adj') return !!r.c.match.adjudicated_by_llm;
  if (id === 'image') return !!r.c.characteristics.image_sha256;
  if (id === 'failed') return !!r.c.failure;
  return !r.c.failure;
}

function renderRows() {
  const all = $('#f-identity').value === 'failed' ? FAILED : ROWS.concat(FAILED);
  const shown = all.filter(matches);
  $('#count').textContent = `${shown.length} of ${ROWS.length + FAILED.length} rows`;
  $('#rows').innerHTML = shown.map(r => `<div data-uid="${esc(r.c.row_uid)}" class="${current === r.c.row_uid ? 'sel' : ''}"><span class="dot ${r.c.failure ? 'bad' : 'ok'}"></span><span class="uid">${esc(r.c.row_uid)}</span><span><span class="brand">${esc(r.c.query.brand)}</span>${esc((r.c.query.desc_raw || '').slice(0, 70))}</span></div>`).join('') || '<div class="empty">nothing matches</div>';
  for (const el of $('#rows').children) el.onclick = () => select(el.dataset.uid);
}

function select(uid) {
  current = uid;
  const r = ROWS.concat(FAILED).find(x => x.c.row_uid === uid);
  if (!r) return;
  const c = r.c;
  $('#head').innerHTML = `<h3>${esc(c.row_uid)}</h3><span><b>${esc(c.query.brand)}</b> · ${esc(c.query.desc_raw)}</span><span class="muted">${esc(c.query.retailer || '')} ${esc((c.query.countries || []).join(','))}</span>`;
  $('#card').innerHTML = renderCard(c);
  renderRows();
}

function registry() {
  const e = DATA.registry;
  const withC = e.filter(x => Object.keys(x.characteristics || {}).length).length;
  $('#registry').innerHTML = `<div class="kv"><b>${e.length}</b> resolved products</div><div class="kv"><b>${e.filter(x => x.module).length}</b> with a module</div><div class="kv"><b>${withC}</b> with characteristics</div>` +
    (e.length ? `<table style="margin-top:8px"><tr><th>brand</th><th>barcode</th><th>module</th><th>page</th><th>rows</th></tr>` +
      e.map(x => `<tr><td>${esc(x.brand)}</td><td>${esc(x.barcode || '')}</td><td>${esc(x.module || '—')}</td><td><a href="${esc(x.resolved_url)}" target="_blank">${esc(host(x.resolved_url))}</a></td><td>${x.members.map(m => `<a href="#" data-uid="${esc(m)}">${esc(m)}</a>`).join(' ')}</td></tr>`).join('') + '</table>' : '');
  for (const a of $('#registry').querySelectorAll('a[data-uid]')) a.onclick = (ev) => { ev.preventDefault(); select(a.dataset.uid); };
}

for (const id of ['#q', '#f-tier', '#f-module', '#f-identity']) $(id).oninput = renderRows;
$('#clear').onclick = () => { for (const id of ['#q', '#f-tier', '#f-module', '#f-identity']) $(id).value = ''; renderRows(); };
numbers(); fillFilters(); registry(); renderRows();
if (location.hash.length > 1) select(decodeURIComponent(location.hash.slice(1)));
</script>
</body>
</html>
"""
