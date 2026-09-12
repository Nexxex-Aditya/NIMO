# ruff: noqa: E501 — embedded HTML/JS; wrapping it would make it less readable, not more
"""The single page the UI serves. Vanilla HTML/CSS/JS, no external assets, no
build step — it fetches JSON from the app and renders what the pipeline
recorded. Kept as a Python string so it ships inside the package.
"""

STYLE = r"""  :root { --bg:#f6f6f2; --card:#fff; --line:#e2e2dc; --ink:#1b1b1b; --muted:#6b6b66; --accent:#1f5fbf;
          --ok:#1e7d3a; --warn:#a15c00; --bad:#b3261e; --tier0:#e5f5e8; --tier2:#eef1fa; --tier3:#fff3cd; }
  * { box-sizing:border-box }
  body { margin:0; font:14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background:var(--bg); color:var(--ink) }
  header { display:flex; align-items:baseline; gap:16px; padding:14px 22px; background:#fff; border-bottom:1px solid var(--line) }
  header h1 { font-size:18px; margin:0 }
  header .sub { color:var(--muted) }
  .badge { display:inline-block; padding:2px 9px; border-radius:12px; font-size:12px; background:var(--tier2) }
  .badge.live { background:var(--tier0) } .badge.off { background:#eee }
  main { display:grid; grid-template-columns: minmax(280px, 340px) minmax(0, 1fr); gap:18px; padding:18px 22px; min-height:calc(100vh - 56px) }
  @media (max-width: 900px) { main { grid-template-columns: 1fr } }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px }
  .panel h2 { font-size:14px; margin:0 0 10px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em }
  input, select, button, textarea { font:inherit }
  input, select, textarea { width:100%; padding:7px 9px; border:1px solid var(--line); border-radius:7px; background:#fff }
  button { padding:7px 14px; border:1px solid var(--accent); background:var(--accent); color:#fff; border-radius:7px; cursor:pointer }
  button.ghost { background:#fff; color:var(--accent) }
  button:disabled { opacity:.5; cursor:default }
  .row { display:flex; gap:8px; align-items:center; margin:6px 0; flex-wrap:wrap }
  .rows { max-height:52vh; overflow:auto; border:1px solid var(--line); border-radius:7px; margin-top:8px }
  .rows div { padding:6px 9px; border-bottom:1px solid var(--line); cursor:pointer; display:flex; gap:8px; align-items:center }
  .rows div:hover { background:#fafaf5 } .rows div.sel { background:#eef3ff }
  .rows .uid { color:var(--muted); font-size:12px; min-width:52px }
  .rows .dot { width:8px; height:8px; border-radius:50%; background:#ccc; flex:none }
  .rows .dot.ok { background:var(--ok) } .rows .dot.bad { background:var(--bad) }
  .stage { display:grid; grid-template-columns:150px 1fr; gap:6px 14px; padding:10px 0; border-top:1px solid var(--line) }
  .stage:first-of-type { border-top:0 }
  .stage b { color:var(--muted); font-weight:600 }
  .tier { display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; background:var(--tier2) }
  .tier.tier0_exact, .tier.tier1_ann { background:var(--tier0) } .tier.tier3_llm { background:var(--tier3) }
  .reason { background:var(--bg); border-radius:8px; padding:12px; margin-top:10px }
  .scroll { overflow-x:auto }
  table { border-collapse:collapse; width:100%; font-size:13px } td, th { border:1px solid var(--line); padding:4px 8px; text-align:left; vertical-align:top }
  th { background:#fafaf5; font-weight:600 }
  .muted { color:var(--muted) } .ok { color:var(--ok) } .bad { color:var(--bad) } .warn { color:var(--warn) }
  .kv { display:inline-block; margin-right:12px } .kv b { font-weight:600 }
  code { font-size:12px; background:#f1f1ec; padding:1px 4px; border-radius:4px }
  #status { font-size:13px; color:var(--muted); margin-top:8px; min-height:18px }
  a { color:var(--accent) }
"""

# The row renderer, shared with the static explorer (`nimo.site`): one
# function turns a card dict into the stage-by-stage HTML, so the exported
# page and the live page cannot drift apart.
CARD_JS = r"""const esc = (v) => String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function host(u) { try { return new URL(u).host.replace(/^www\./, ''); } catch { return u || '-'; } }
function pct(x) { return (100 * x).toFixed(0) + '%'; }

function renderCard(c) {
  if (c.failure) {
    return `<div class="stage"><b>failed at</b><div class="bad">${esc(c.failure.stage)} — ${esc(c.failure.error_type)}: ${esc(c.failure.message)}</div></div>`;
  }
  const q = c.query, t = q.tokens, m = c.match, f = m.features, cls = c.classify, ch = c.characteristics;
  const rows = [];
  rows.push(['normalize', `<code>${esc(q.desc_clean)}</code><br><span class="kv"><b>size</b> ${t.size_value ?? '—'} ${esc(t.size_unit||'')}</span><span class="kv"><b>count</b> ${t.count ?? '—'}</span><span class="kv"><b>hints</b> ${esc((t.format_hints||[]).join(', ')||'—')}</span><span class="kv"><b>barcode</b> ${q.barcode ? esc(q.barcode) : (q.barcode_corrupt ? '<span class="warn">corrupt in source</span>' : 'none')}</span><span class="kv"><b>retailer</b> ${esc(q.retailer)}</span>`]);
  rows.push(['registry', `<span class="tier ${esc(c.tier)}">${esc(c.tier)}</span> ${c.registry.hit ? `hit on <code>${esc(c.registry.entity.entity_id)}</code> — page and characteristics carried, stages 2–4 skipped` : 'miss — the product is new to the registry'}`]);
  if (!c.registry.hit) {
    const byS = {}; for (const cand of c.retrieve.candidates) byS[cand.source_query] = (byS[cand.source_query]||0) + 1;
    rows.push(['retrieve', `${c.retrieve.candidates.length} candidates · ${esc(JSON.stringify(byS))} · brand signal ${pct(c.retrieve.brand_signal)}`]);
    const st = {}; let withG = 0; for (const e of c.fetch) { st[e.fetch_status] = (st[e.fetch_status]||0)+1; if (e.gtin) withG++; }
    rows.push(['fetch', `${c.fetch.length} fetched · ${esc(JSON.stringify(st))} · pages publishing a GTIN: ${withG}<br>` +
      c.fetch.slice(0, 8).map(e => `<span class="muted">${esc(e.fetch_status)}</span> ${e.gtin ? '<span class="ok">GTIN</span> ' : ''}<a href="${esc(e.url)}" target="_blank">${esc(host(e.url))}</a> <span class="muted">${esc((e.title||'').slice(0,70))}</span>`).join('<br>')]);
    const ftxt = f ? `gtin_exact <b>${f.barcode_exact}</b> · size <b>${esc(f.size_match)}</b> · count <b>${esc(f.count_match)}</b> · brand ${f.brand_match.toFixed(2)} · variant ${f.variant_overlap.toFixed(2)} · flags ${esc(JSON.stringify(f.negative_flags))} · calibrated <b>${f.calibrated_prob.toFixed(2)}</b>` : '';
    rows.push(['match', m.url ? `<a href="${esc(m.url)}" target="_blank">${esc(host(m.url))}</a> · score ${m.confidence.toFixed(2)} · gap ${m.runner_up_gap.toFixed(2)}${m.adjudicated_by_llm ? ' · <span class="tier tier3_llm">Tier 3 tiebreak</span>' : ''}<br><span class="muted">${ftxt}</span>` + (m.adjudication ? `<br><span class="muted">model: ${esc(m.adjudication.rationale)}</span>` : '') : '<span class="warn">abstained — no candidate met the evidence threshold</span>']);
  }
  rows.push(['classify', `<b>${esc(cls.module)}</b> <span class="muted">· ${esc(cls.source)} · confidence ${cls.confidence.toFixed(2)}${cls.nearest_example_row_uid ? ` · most resembles ${esc(cls.nearest_example_row_uid)}` : ''}${cls.runner_up ? ` · runner-up ${esc(cls.runner_up)}` : ''}</span>`]);
  const coded = Object.entries(ch.values).filter(([k,v]) => v !== null);
  const empty = ch.applicable.filter(k => ch.values[k] === null);
  let chtml = `<span class="muted">${esc(ch.source)} · ${ch.applicable.length} applicable · ${coded.length} coded</span>`;
  if (coded.length) chtml += `<table style="margin-top:6px">${coded.map(([k,v]) => `<tr><td>${esc(k)}</td><td><b>${esc(v)}</b></td></tr>`).join('')}</table>`;
  if (empty.length && ch.source === 'llm') chtml += `<div class="muted">no evidence: ${esc(empty.join(', '))}</div>`;
  if (Object.keys(ch.rejected).length) chtml += `<div class="warn">refused by the validator: ${esc(JSON.stringify(ch.rejected))}</div>`;
  if (ch.source === 'gate_only') chtml += `<div class="muted">values need the model (run with --characteristics on the NIQ network); the null pattern above is exact for this module</div>`;
  rows.push(['characteristics', chtml]);
  rows.push(['reason', `<div class="reason">${esc(c.reason.text)}</div><div class="muted" style="margin-top:4px">provenance: ${esc(c.reason.claims.join(' · '))}</div>`]);
  return rows.map(([k, v]) => `<div class="stage"><b>${k}</b><div>${v}</div></div>`).join('');
}

function render(c) { $('#card').innerHTML = renderCard(c); }

"""

_PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIMO — the Product Truth Agent</title>
<style>
__STYLE__</style>
</head>
<body>
<header>
  <h1>NIMO</h1><span class="sub">the Product Truth Agent</span>
  <span id="mode" class="badge">…</span>
  <span id="reg" class="sub"></span>
</header>
<main>
  <aside>
    <div class="panel">
      <h2>Try any product</h2>
      <div class="row"><input id="q-desc" placeholder="retailer description, e.g. aquafresh whitening pump 100ml"></div>
      <div class="row"><input id="q-brand" placeholder="brand, e.g. AQUAFRESH (HALEON)"></div>
      <div class="row"><input id="q-barcode" placeholder="barcode (optional)"><input id="q-country" placeholder="country" value="GB" style="width:90px"></div>
      <div class="row"><input id="q-retailer" placeholder="retailer as in the sheet, e.g. P00R4 (GB) BOOTS (optional)"></div>
      <div class="row"><button id="lookup">Resolve</button><span class="muted">runs the full pipeline for this record</span></div>
    </div>
    <div class="panel" style="margin-top:14px">
      <h2>Dataset rows</h2>
      <div class="row">
        <select id="sheet"><option value="qa">qa (412)</option><option value="dev">dev (412)</option></select>
        <input id="filter" placeholder="filter…">
      </div>
      <div id="rows" class="rows"></div>
    </div>
  </aside>
  <section>
    <div class="panel">
      <div class="row" style="justify-content:space-between">
        <h2 id="title" style="margin:0">Pick a row, or resolve a product</h2>
        <span>
          <button id="run" class="ghost" disabled>Run</button>
          <button id="rerun" class="ghost" disabled title="clears this row's artifacts and runs it again — a GTIN-confirmed row comes back as a Tier 0 registry hit">Run again (warm)</button>
        </span>
      </div>
      <div id="status"></div>
      <div id="card" class="scroll"></div>
    </div>
    <div class="panel" style="margin-top:14px">
      <h2>Registry — the memory</h2>
      <div id="registry" class="muted scroll">…</div>
    </div>
  </section>
</main>
<script>
const $ = (s) => document.querySelector(s);
let current = null;   // {sheet, row_uid}
let allRows = [];

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) { const t = await r.json().catch(() => ({detail: r.statusText})); throw new Error(t.detail || r.statusText); }
  return r.json();
}

async function loadStatus() {
  const s = await api('/api/status');
  const m = $('#mode');
  m.textContent = s.live ? 'LIVE' + (s.characteristics ? ' + model' : '') + (s.adjudicate ? ' + tiebreak' : '') : 'OFFLINE';
  m.className = 'badge ' + (s.live ? 'live' : 'off');
  $('#reg').textContent = `registry: ${s.registry_entities} entities · calibration ${s.curve ? 'loaded' : 'none'}` + (s.llm_calls ? ` · model calls ${s.llm_calls}` : '');
}

async function loadRows() {
  const sheet = $('#sheet').value;
  allRows = await api('/api/rows?sheet=' + sheet);
  renderRows();
}
function renderRows() {
  const f = $('#filter').value.toLowerCase();
  const box = $('#rows'); box.innerHTML = '';
  for (const r of allRows) {
    if (f && !(r.desc + ' ' + r.brand + ' ' + r.row_uid).toLowerCase().includes(f)) continue;
    const d = document.createElement('div');
    d.innerHTML = `<span class="dot ${r.complete ? 'ok' : (r.failed_at ? 'bad' : '')}"></span><span class="uid">${esc(r.row_uid)}</span><span>${esc(r.brand)} · ${esc(r.desc)}</span>`;
    if (current && current.row_uid === r.row_uid) d.className = 'sel';
    d.onclick = () => selectRow($('#sheet').value, r.row_uid, r.complete);
    box.appendChild(d);
  }
}

async function selectRow(sheet, row_uid, complete) {
  current = {sheet, row_uid};
  renderRows();
  $('#title').textContent = row_uid;
  $('#run').disabled = false; $('#rerun').disabled = !complete;
  $('#card').innerHTML = ''; $('#status').textContent = complete ? '' : 'not run yet — press Run';
  if (complete) { try { render(await api(`/api/rows/${sheet}/${encodeURIComponent(row_uid)}`)); } catch (e) { $('#status').textContent = e.message; } }
}

async function runCurrent(force) {
  if (!current) return;
  $('#run').disabled = true; $('#rerun').disabled = true;
  $('#status').textContent = force ? 'running again (artifacts cleared)…' : 'running…';
  try {
    const card = await api('/api/run', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({sheet: current.sheet, row_uid: current.row_uid, force})});
    render(card);
    const r = card.run || {};
    $('#status').textContent = `done in ${r.wall_time_s}s · registry ${r.registry_before} → ${r.registry_after}` + (r.llm_calls ? ` · model calls ${r.llm_calls}` : '');
    await loadStatus(); await loadRows(); await loadRegistry();
  } catch (e) { $('#status').textContent = 'failed: ' + e.message; }
  $('#run').disabled = false; $('#rerun').disabled = false;
}

async function lookup() {
  const body = {desc: $('#q-desc').value, brand: $('#q-brand').value, barcode: $('#q-barcode').value || null,
                retailer: $('#q-retailer').value || null, country: $('#q-country').value || null};
  $('#status').textContent = 'resolving…'; $('#card').innerHTML = ''; $('#title').textContent = 'ad-hoc product';
  try {
    const card = await api('/api/lookup', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
    current = {sheet: 'adhoc', row_uid: card.row_uid};
    $('#title').textContent = card.row_uid; $('#run').disabled = false; $('#rerun').disabled = false;
    render(card);
    const r = card.run || {};
    $('#status').textContent = `done in ${r.wall_time_s}s · registry ${r.registry_before} → ${r.registry_after}`;
    await loadStatus(); await loadRegistry();
  } catch (e) { $('#status').textContent = 'failed: ' + e.message; }
}

__CARD_JS__
async function loadRegistry() {
  const r = await api('/api/registry');
  $('#registry').innerHTML = `<div class="kv"><b>${r.entities}</b> resolved products</div><div class="kv"><b>${r.with_module}</b> with a module</div><div class="kv"><b>${r.with_characteristics}</b> with characteristics</div>` +
    (r.recent.length ? `<table style="margin-top:8px"><tr><th>brand</th><th>barcode</th><th>module</th><th>page</th><th>members</th></tr>` +
      r.recent.map(e => `<tr><td>${esc(e.brand)}</td><td>${esc(e.barcode||'')}</td><td>${esc(e.module||'—')}</td><td><a href="${esc(e.resolved_url)}" target="_blank">${esc(host(e.resolved_url))}</a></td><td>${esc(e.members.join(', '))}</td></tr>`).join('') + '</table>' : '');
}

$('#sheet').onchange = loadRows; $('#filter').oninput = renderRows;
$('#run').onclick = () => runCurrent(false); $('#rerun').onclick = () => runCurrent(true);
$('#lookup').onclick = lookup;
loadStatus(); loadRows(); loadRegistry();
</script>
</body>
</html>
"""

PAGE = _PAGE_TEMPLATE.replace("__STYLE__", STYLE).replace("__CARD_JS__", CARD_JS)
