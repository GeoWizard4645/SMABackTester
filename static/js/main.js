// SMA Lab front-end: wires the inputs form, runs analyses and renders every tab.

import { $, $$, h, clear, fmt, sigClass, stars, download, toCSV, seriesColor, isDark, loadJson, loadText } from './util.js';
import * as engine from './engine.js';
import { initControls, collectConfig, applyConfig, setStatus, addTicker } from './controls.js';
import * as charts from './charts.js';
import { dataTable, tableBlock, verdict, plainLines, scoreboard, seriesDot } from './tables.js';

const state = {
  meta: null, resp: null, ai: 0, control: null, horizon: 5, tab: 'overview',
  scan: null, scanOpts: { metric: 'car', era: 'All', minN: 10, exclude: 10, min: 20, max: 400, step: 5, ticker: null },
  ex: { ma: '', dir: '', era: '', outcome: '', sort: { key: 'date', dir: 1 }, page: 0, selected: null, win: null },
  price: { log: false },
};
const STORE = 'smalab.cfg.v1';
const cur = () => state.resp && state.resp.results[state.ai];
const plot = (cls = '') => h('div', { class: ('plot ' + cls).trim() });
const era = (res, name) => (name === 'All' ? 'All' : `${name} (${res.eras.find((e) => e.name === name).desc})`);

// ------------------------------------------------------------------ boot
async function boot() {
  initTheme();
  try {
    state.meta = await loadJson('meta-json', 'static/meta.json');
  } catch (e) {
    $('#tab-overview').append(h('div', { class: 'empty' }, h('h2', {}, 'Cannot reach the server'), h('p', {}, String(e.message))));
    return;
  }
  initControls(state.meta);
  restoreConfig();
  wireChrome();
  renderTab();
  const wanted = new URLSearchParams(location.search).get('view');
  if (wanted === 'kalshi' || wanted === 'local') switchView(wanted);
  if (typeof Plotly === 'undefined') setStatus('Plotly failed to load (offline?). Charts need an internet connection for the CDN scripts.', 'err');
}

function restoreConfig() {
  try {
    const m = /#cfg=(.+)$/.exec(location.hash);
    if (m) { applyConfig({ ...state.meta.defaults, ...JSON.parse(decodeURIComponent(escape(atob(m[1])))) }); return; }
    const saved = localStorage.getItem(STORE);
    if (saved) applyConfig({ ...state.meta.defaults, ...JSON.parse(saved) });
  } catch { /* ignore corrupt state */ }
}

function initTheme() { /* single light theme */ }

let kalshiLoaded = false;
async function switchView(view) {
  $('#view-sma').hidden = view !== 'sma';
  $('#view-kalshi').hidden = view !== 'kalshi';
  $('#view-local').hidden = view !== 'local';
  $$('#viewnav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  const url = new URL(location.href);
  if (view !== 'sma') url.searchParams.set('view', view); else url.searchParams.delete('view');
  history.replaceState(null, '', url);
  if (view === 'kalshi' && !kalshiLoaded) {
    kalshiLoaded = true;
    try {
      const mod = await import('./kalshi.js');
      mod.initKalshi($('#view-kalshi'), state.meta.kalshi);
    } catch (e) { kalshiLoaded = false; $('#view-kalshi').textContent = `Could not load the Kalshi lab: ${e.message}`; }
  }
  window.dispatchEvent(new Event('resize'));
}

function wireCopyButtons() {
  $$('.copybtn').forEach((btn) => btn.addEventListener('click', async () => {
    const text = btn.nextElementSibling.innerText.replace(/\n$/, '');
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch { /* fall back below */ }
    if (!ok) { // older browsers / blocked clipboard API
      const box = h('textarea', { style: 'position:fixed;opacity:0' });
      box.value = text;
      document.body.append(box);
      box.select();
      try { ok = document.execCommand('copy'); } catch { /* ignore */ }
      box.remove();
    }
    btn.textContent = ok ? 'Copied' : 'Select and copy';
    setTimeout(() => { btn.textContent = 'Copy'; }, 1600);
  }));
}

function wireChrome() {
  wireCopyButtons();
  $('#viewnav').addEventListener('click', (e) => { const b = e.target.closest('button[data-view]'); if (b) switchView(b.dataset.view); });
  engine.onStatus((t) => {
    const el = $('#py-status');
    el.hidden = false;
    el.textContent = t;
    clearTimeout(el._t);
    if (t === 'Python ready.') el._t = setTimeout(() => { el.hidden = true; }, 3000);
  });
  $('#csv-upload').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    e.target.value = '';
    if (!f) return;
    if (f.size > 8e6) { setStatus('That file is larger than 8 MB.', 'err'); return; }
    setStatus(`Reading ${f.name}…`, 'busy');
    try {
      const r = await engine.call('register_csv', { name: f.name, text: await f.text() });
      addTicker(r.ticker);
      setStatus(`Loaded ${f.name} as ${r.ticker}. Press Run to include it.`);
    } catch (err) { setStatus(err.message, 'err'); }
  });
  $('#run-btn').addEventListener('click', runAnalysis);
  document.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') runAnalysis(); });
  $('#reset-btn').addEventListener('click', () => { applyConfig(state.meta.defaults); history.replaceState(null, '', location.pathname); setStatus('Settings reset to defaults.'); });
  $('#share-btn').addEventListener('click', async () => {
    const enc = btoa(unescape(encodeURIComponent(JSON.stringify(collectConfig()))));
    history.replaceState(null, '', `#cfg=${enc}`);
    try { await navigator.clipboard.writeText(location.href); setStatus('Share link copied to clipboard.'); }
    catch { setStatus('Link is now in the address bar, copy it from there.'); }
  });
  $('#export-btn').addEventListener('click', () => state.resp && download('sma-lab-results.json', JSON.stringify(state.resp), 'application/json'));
  $('#tabs').addEventListener('click', (e) => { const b = e.target.closest('button[data-tab]'); if (b) switchTab(b.dataset.tab); });
  $('#control-select').addEventListener('change', (e) => { state.control = e.target.value; renderTab(); });
  $('#horizon-select').addEventListener('change', (e) => { state.horizon = parseInt(e.target.value, 10); renderTab(); });
  window.addEventListener('resize', () => charts.resizeAll());
}

function switchTab(name) {
  state.tab = name;
  $$('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  $$('.panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${name}`));
  renderTab();
}

// ------------------------------------------------------------------ run
async function runAnalysis() {
  const cfg = collectConfig();
  if (!cfg.tickers.length) { setStatus('Add at least one asset first.', 'err'); return; }
  const btn = $('#run-btn');
  btn.disabled = true;
  const t0 = performance.now();
  setStatus(`Analysing ${cfg.tickers.length} asset${cfg.tickers.length > 1 ? 's' : ''}… (first run per asset downloads its history)`, 'busy');
  try {
    const resp = await engine.call('analyze', { config: cfg }, { onProgress: (t) => setStatus(t, 'busy') });
    try { localStorage.setItem(STORE, JSON.stringify(cfg)); } catch { /* ignore */ }
    if (!resp.results.length) {
      state.resp = null;
      setStatus(Object.values(resp.errors).join(' | ') || 'No results.', 'err');
      renderTab();
      return;
    }
    state.resp = resp;
    state.ai = 0;
    state.ex = { ...state.ex, ma: '', dir: '', era: '', outcome: '', page: 0, selected: null, win: null };
    state.horizon = resp.config.plot_horizon;
    state.scan = null;
    buildSelectors();
    $('#export-btn').disabled = false;
    const errs = Object.entries(resp.errors).map(([t, m]) => `${t}: ${m}`);
    setStatus(`Done in ${((performance.now() - t0) / 1000).toFixed(1)}s.` + (errs.length ? ' Some assets failed, see Overview.' : ''), errs.length ? 'err' : '');
    renderTab();
  } catch (e) {
    setStatus(e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

function buildSelectors() {
  const r = state.resp;
  const seg = clear($('#asset-select'));
  r.results.forEach((res, i) => seg.append(h('button', { type: 'button', class: i === state.ai ? 'on' : '', onclick: () => { state.ai = i; state.control = null; state.ex.selected = null; state.ex.win = null; buildSelectors(); renderTab(); } }, res.ticker === 'SYNTHETIC' ? 'Synthetic' : res.ticker)));
  const res = cur();
  const cs = clear($('#control-select'));
  res.mas.slice(1).forEach((c) => cs.append(h('option', { value: String(c) }, `${c}-day control`)));
  if (!res.mas.slice(1).length) cs.append(h('option', { value: '' }, 'no control'));
  if (!state.control || !res.mas.includes(parseInt(state.control, 10))) state.control = String(res.mas[1] ?? '');
  cs.value = state.control;
  const hs = clear($('#horizon-select'));
  r.config.horizons.forEach((k) => hs.append(h('option', { value: String(k) }, `${k} days`)));
  if (!r.config.horizons.includes(state.horizon)) state.horizon = r.config.plot_horizon;
  hs.value = String(state.horizon);
}

// ------------------------------------------------------------------ tab router
function renderTab() {
  const t = state.tab;
  const has = !!state.resp;
  // The little selector bar only appears where it matters.
  $('#subbar').hidden = !has || ['method', 'scan'].includes(t);
  const sg = $$('.subgroup');
  sg[0].hidden = t === 'overview' || state.resp?.results.length < 2;
  sg[1].hidden = ['overview', 'explorer'].includes(t);
  sg[2].hidden = false;
  const fn = { overview: renderOverview, charts: renderCharts, tables: renderTables, scan: renderScan, explorer: renderExplorer, method: renderMethod }[t];
  const root = $(`#tab-${t}`);
  if (!has && !['method', 'scan', 'overview'].includes(t)) { clear(root).append(emptyState()); return; }
  fn(root);
}
function renderCharts(root) {
  clear(root);
  const parts = [h('div'), h('div'), h('div')];
  root.append(...parts);
  renderEras(parts[0]);
  renderStudy(parts[1]);
  renderPrice(parts[2]);
}
const emptyState = () => h('div', { class: 'empty' }, h('h2', {}, 'Run an analysis first'), h('p', {}, 'Fill in the inputs above and press Run.'));

// ------------------------------------------------------------------ overview
function renderOverview(root) {
  clear(root);
  if (!state.resp) {
    root.append(h('div', { class: 'empty' },
      h('h2', {}, 'No results yet'),
      h('p', {}, 'Traders watch the 200-day average. If enough of them act on it, it might become a real floor or ceiling just because everyone believes in it. This page tests that against lines nobody watches.'),
      h('p', {}, h('button', { class: 'btn primary big', type: 'button', onclick: runAnalysis }, 'Run the example (S&P 500, 200-day vs 174-day)')),
      h('p', { class: 'note' }, 'New here? “How it works” explains everything in plain steps.')));
    return;
  }
  const { results, errors, config, seconds } = state.resp;
  const hz = state.horizon;
  root.append(h('div', { class: 'block' },
    h('h2', {}, 'Results at a glance'),
    h('p', { class: 'sub' }, `Testing the ${config.target}-day line against ${config.controls.length ? config.controls.join(', ') + '-day' : 'no'} comparison line${config.controls.length > 1 ? 's' : ''}. The verdicts look ${hz} days ahead (change “Look ahead” above).`),
    Object.keys(errors).length ? h('div', { class: 'callout warn' }, h('b', {}, 'Some assets could not be analysed:'), h('ul', { class: 'warnlist' }, Object.entries(errors).map(([t, m]) => h('li', {}, `${t}: ${m}`)))) : null,
    (results.length > 1 || results[0].mas.length > 2) ? [h('h3', {}, 'Scoreboard: tested line minus comparison line'), scoreboard(results, hz),
      h('p', { class: 'note' }, 'Positive = the tested line reacts more. Shaded cells are statistically significant (p below 0.05).')] : null));

  for (const res of results) {
    const blk = h('div', { class: 'block' }, h('h2', {}, `${res.label}`),
      h('p', { class: 'sub' }, `${res.span.start} to ${res.span.end}, ${res.span.bars.toLocaleString()} days of data, periods: ${res.eras.map((e) => `${e.name} ${e.desc}`).join(', ')}`));
    const cs = res.mas.slice(1);
    if (!cs.length) blk.append(h('p', { class: 'note' }, 'No control line selected, add one to compare.'));
    for (const c of cs) {
      const v = verdict(res, String(c), hz);
      if (!v) continue;
      blk.append(h('div', { class: 'verdict' },
        h('span', { class: `vbadge ${v.kind}` }, `${res.mas[0]} vs ${c}`),
        h('div', {}, h('div', { class: 'vtitle' }, v.headline), plainLines(v, hz, res, c)),
        h('div', { class: 'vmeta' }, v.era)));
    }
    if (res.skipped_controls.length) blk.append(h('p', { class: 'note' }, `Skipped (no events): ${res.skipped_controls.join(', ')}.`));
    if (res.warnings.length) blk.append(h('details', {}, h('summary', { class: 'note' }, `${res.warnings.length} caveat${res.warnings.length > 1 ? 's' : ''} for this asset`), h('ul', { class: 'warnlist' }, res.warnings.map((w) => h('li', {}, w)))));
    root.append(blk);
  }
  root.append(h('div', { class: 'callout warn' }, h('b', {}, 'Reading the numbers. '),
    'A p-value below 0.05 means the difference is unlikely to be pure luck. But this page makes many comparisons, so a few will look significant by chance: treat a single hit (one horizon, one period, one asset) as weak evidence. The tests are also less reliable when a period covers fewer than about 10 years.'));
}

// ------------------------------------------------------------------ price & events
function renderPrice(root) {
  clear(root);
  const res = cur();
  const box = plot('tall');
  root.append(h('div', { class: 'block' }, h('h2', {}, `${res.label}: price, lines and touch events`),
    h('p', { class: 'sub' }, '▲ support tests (price came from above) and ▼ resistance tests (from below), coloured by line. Dotted verticals are era boundaries. Click legend entries to hide lines or events; drag the slider to zoom.'),
    h('div', { class: 'toolrow' }, h('label', { class: 'cb' }, h('input', { type: 'checkbox', checked: state.price.log, onchange: (e) => { state.price.log = e.target.checked; charts.plotPrice(box, res, state.price); } }), 'Log price scale')),
    box));
  charts.plotPrice(box, res, state.price);
}

// ------------------------------------------------------------------ event study
function renderStudy(root) {
  clear(root);
  const res = cur(), pre = state.resp.config.pre;
  const divs = [plot('short'), plot('short'), plot('short')], eraDiv = plot('short');
  const sel = h('select', { onchange: (e) => charts.plotStudyByEra(eraDiv, res, e.target.value, pre) }, res.mas.map((m) => h('option', { value: String(m) }, `${m}-day line`)));
  root.append(
    h('div', { class: 'block' }, h('h2', {}, `${res.label}: what happens after a touch`),
      h('p', { class: 'sub' }, `The average price path from ${pre} days before each touch to ${state.resp.config.post} days after (day 0 = the touch), compared with a normal day. If a line really acts as a floor, price should rise after touching it from above; as a ceiling, it should fall after touching it from below. A flat line means no reaction.`),
      h('div', { class: 'grid-3' }, divs)),
    h('div', { class: 'block' }, h('h2', {}, 'Does it change between time periods?'), h('div', { class: 'toolrow' }, h('div', {}, h('label', {}, 'Line'), sel)), eraDiv));
  charts.plotStudy(divs, res, pre);
  charts.plotStudyByEra(eraDiv, res, res.mas[0], pre);
}

// ------------------------------------------------------------------ eras
function renderEras(root) {
  clear(root);
  const res = cur(), hz = state.horizon, c = state.control;
  const d = { bounce: plot('short'), car: plot('short'), gapBounce: plot('short'), gapCar: plot('short') };
  root.append(
    h('div', { class: 'block' }, h('h2', {}, `${res.label}: by time period (looking ${hz} days ahead)`),
      h('p', { class: 'sub' }, `Top: how often price bounced away from each line, and the average move afterwards, in each period. Bottom: the ${res.mas[0]}-day line minus the ${c || '—'}-day line. A bar whose whisker crosses zero means no clear difference.`),
      h('div', { class: 'grid-auto' }, d.bounce, d.car, d.gapBounce, d.gapCar)));
  charts.plotEraBars(d, res, c, hz);
  const exp = res.expansion[c];
  if (exp) {
    const v = verdict(res, c, hz);
    root.append(h('div', { class: 'block' }, h('h2', {}, `Did the gap change from ${res.base_era} to ${res.late_era}?`),
      h('p', { class: 'sub' }, `Difference-in-differences: (target − control in ${res.late_era}) − (target − control in ${res.base_era}). Positive supports “the effect grew in the modern era”.`),
      v ? h('div', { class: 'callout' }, v.era) : null,
      dataTable(expCols(res), exp, { groupKey: 'metric' })));
  }
}
function expCols(res) {
  const f = (r) => (r.metric === 'bounce' ? fmt.pp : fmt.spct);
  return [
    { key: 'metric', label: 'Metric', left: true }, { key: 'horizon', label: 'Horizon' },
    { key: 'diff_base', label: `Gap in ${res.base_era}`, fmt: (v, r) => f(r)(v) },
    { key: 'diff_late', label: `Gap in ${res.late_era}`, fmt: (v, r) => f(r)(v) },
    { key: 'did', label: 'Change (DiD)', fmt: (v, r) => f(r)(v) },
    { key: 'boot_lo', label: 'Boot CI low', fmt: (v, r) => f(r)(v) }, { key: 'boot_hi', label: 'Boot CI high', fmt: (v, r) => f(r)(v) },
    { key: 'boot_p', label: 'Boot p', fmt: (v) => fmt.p(v) + stars(v), cls: (r) => sigClass(r.boot_p) },
    { key: 'reg_coef', label: 'OLS coef', fmt: (v, r) => f(r)(v) },
    { key: 'reg_p', label: 'OLS p (clustered)', fmt: (v) => fmt.p(v) + stars(v), cls: (r) => sigClass(r.reg_p) },
  ];
}

// ------------------------------------------------------------------ tables
function renderTables(root) {
  clear(root);
  const res = cur(), c = state.control;
  const eraTxt = (v) => era(res, v);
  const pv = (k, label) => ({ key: k, label, fmt: (v) => fmt.p(v) + stars(v), cls: (r) => sigClass(r[k]) });
  const eraOrder = [...res.eras.map((e) => e.name), 'All'];
  const byEra = (a, b) => eraOrder.indexOf(a.era) - eraOrder.indexOf(b.era);

  root.append(h('div', { class: 'block' }, h('h2', {}, `${res.label}: tables`), h('p', { class: 'sub' }, 'Every number behind the charts. Shaded p-values: p < 0.05 (light), p < 0.01 (dark). Use “Download CSV” to take any table into a spreadsheet.'),
    tableBlock('1. Events detected', [
      { key: 'ma', label: 'Line', left: true }, { key: 'era', label: 'Era', left: true, fmt: eraTxt },
      { key: 'total', label: 'Events' }, { key: 'support', label: 'Support tests' }, { key: 'resistance', label: 'Resistance tests' },
    ], res.counts, { csv: `${res.ticker}-counts.csv`, groupKey: 'ma' }),
    tableBlock('2. Bounce rate and direction-adjusted CAR, per line / era / horizon', [
      { key: 'ma', label: 'Line', left: true }, { key: 'era', label: 'Era', left: true, fmt: eraTxt }, { key: 'horizon', label: 'Horizon' }, { key: 'n', label: 'n' },
      { key: 'bounce_rate', label: 'Bounce rate', fmt: (v) => fmt.pct(v) }, { key: 'bounce_lo', label: 'CI low', fmt: (v) => fmt.pct(v) }, { key: 'bounce_hi', label: 'CI high', fmt: (v) => fmt.pct(v) },
      { key: 'car_mean', label: 'Mean CAR', fmt: (v) => fmt.spct(v) }, { key: 'car_std', label: 'SD', fmt: (v) => fmt.pct(v, 2) },
      { key: 'car_lo', label: 'CI low', fmt: (v) => fmt.spct(v) }, { key: 'car_hi', label: 'CI high', fmt: (v) => fmt.spct(v) },
    ], res.summary.filter((r) => r.horizon === state.horizon || true), { csv: `${res.ticker}-summary.csv`, groupKey: 'ma', note: 'Bounce CIs are Wilson intervals; CAR CIs are Student-t. CAR is measured against the unconditional return of the same era.' })));

  if (c && res.comparisons[c]) {
    const rows = [...res.comparisons[c]].sort(byEra);
    const valf = (r, v) => (r.metric === 'bounce' ? fmt.pct(v) : r.metric === 'car' ? fmt.spct(v) : fmt.num(v, 3));
    const gapf = (r, v) => (r.metric === 'bounce' ? fmt.pp(v) : r.metric === 'car' ? fmt.spct(v) : fmt.num(v, 3));
    root.append(h('div', { class: 'block' }, tableBlock(`3. ${res.mas[0]} vs ${c}: tests per era`, [
      { key: 'era', label: 'Era', left: true, fmt: eraTxt }, { key: 'metric', label: 'Metric', left: true }, { key: 'horizon', label: 'Horizon', fmt: (v) => (v ? v : '–') },
      { key: 'n_target', label: `n ${res.mas[0]}` }, { key: 'n_control', label: `n ${c}` },
      { key: 'mean_target', label: `Mean ${res.mas[0]}`, fmt: (v, r) => valf(r, v) }, { key: 'mean_control', label: `Mean ${c}`, fmt: (v, r) => valf(r, v) },
      { key: 'diff', label: 'Difference', fmt: (v, r) => gapf(r, v) },
      pv('t_p', 'Student t'), pv('welch_p', 'Welch t'), pv('mwu_p', 'Mann-Whitney'),
      { key: 'boot_lo', label: 'Boot CI low', fmt: (v, r) => gapf(r, v) }, { key: 'boot_hi', label: 'Boot CI high', fmt: (v, r) => gapf(r, v) }, pv('boot_p', 'Boot p'),
    ], rows, { csv: `${res.ticker}-${res.mas[0]}-vs-${c}.csv`, groupKey: 'era', note: 'The first three p-values assume independent samples, which is false here (both lines see the same prices), so they are conservative. The year-cluster bootstrap p-value is the one to trust. “atr_ratio” / “tr_ratio” rows compare event-day volatility with the prior 20 days.' })));
    root.append(h('div', { class: 'block' }, tableBlock(`4. Era change in the gap (${res.base_era} to ${res.late_era})`, expCols(res), res.expansion[c], { csv: `${res.ticker}-did-${c}.csv`, groupKey: 'metric' })));
  }
  root.append(h('div', { class: 'block' }, tableBlock('5. Range expansion on event day', [
    { key: 'ma', label: 'Line', left: true }, { key: 'era', label: 'Era', left: true, fmt: eraTxt }, { key: 'n', label: 'Events' },
    { key: 'atr_ratio', label: 'ATR / prior-20 ATR', fmt: (v) => fmt.num(v, 3) }, { key: 'tr_ratio', label: 'TR / prior-20 TR', fmt: (v) => fmt.num(v, 3) },
    { key: 'abs_dist_pct', label: 'Mean |distance to line|', fmt: (v) => fmt.pct(v, 2) }, { key: 'abs_dist_atr', label: 'Mean |distance| in ATR', fmt: (v) => fmt.num(v, 2) },
  ], res.range, { csv: `${res.ticker}-range.csv`, groupKey: 'ma', note: '1.0 means a normal day. Values above 1 mean the touch day had an unusually wide range.' })));
}

// ------------------------------------------------------------------ line scan
function renderScan(root) {
  clear(root);
  const o = state.scanOpts;
  const cfg = collectConfig();
  const tickers = cfg.tickers.length ? cfg.tickers : ['^GSPC'];
  if (!o.ticker || !tickers.includes(o.ticker)) o.ticker = state.resp ? cur().ticker : tickers[0];
  const num = (id, v, min, max, w) => h('div', {}, h('label', { for: id }, w), h('input', { id, type: 'number', value: v, min, max, onchange: (e) => { o[id.replace('sc-', '')] = parseFloat(e.target.value); } }));
  const sel = (id, opts, val, label, fn) => h('div', {}, h('label', { for: id }, label), h('select', { id, onchange: (e) => fn(e.target.value) }, opts.map(([v, t]) => h('option', { value: v, selected: String(v) === String(val) }, t))));
  const out = h('div', { id: 'scan-out' });
  root.append(h('div', { class: 'block' }, h('h2', {}, 'Is the target line special, or would any line look like this?'),
    h('p', { class: 'sub' }, 'Runs the identical event study for every line length in a range (using the settings above) and shows where your target ranks. If the 200 is a genuine focal point, it should stand out from its neighbours; if it sits in the middle of the pack, any line would have looked just as good.'),
    h('div', { class: 'toolrow' },
      sel('sc-ticker', tickers.map((t) => [t, t]), o.ticker, 'Asset', (v) => { o.ticker = v; }),
      num('sc-min', o.min, 2, 999, 'Shortest line'), num('sc-max', o.max, 3, 1000, 'Longest line'), num('sc-step', o.step, 1, 100, 'Step'),
      h('button', { class: 'btn primary', type: 'button', id: 'scan-run', onclick: runScan }, 'Run scan')),
    h('p', { class: 'note' }, `Uses target ${cfg.target}-day ${cfg.ma_type.toUpperCase()} with the other settings above. At most 250 line lengths.`)), out);
  if (state.scan) drawScan(out);
}
async function runScan() {
  const o = state.scanOpts, out = $('#scan-out'), btn = $('#scan-run');
  btn.disabled = true;
  clear(out).append(h('div', { class: 'block' }, h('span', { class: 'spinner' }), 'Scanning line lengths…'));
  try {
    state.scan = await engine.call('scan', { config: collectConfig(), ticker: o.ticker, min: o.min, max: o.max, step: o.step });
    if (!state.scan.horizons.includes(o.horizon)) o.horizon = state.scan.horizons.includes(5) ? 5 : state.scan.horizons[0];
    drawScan(out);
  } catch (e) {
    clear(out).append(h('div', { class: 'callout warn' }, e.message));
  } finally { btn.disabled = false; }
}
function drawScan(out) {
  const o = state.scanOpts, s = state.scan;
  clear(out);
  const sel = (label, opts, val, fn) => h('div', {}, h('label', {}, label), h('select', { onchange: (e) => fn(e.target.value) }, opts.map(([v, t]) => h('option', { value: v, selected: String(v) === String(val) }, t))));
  const line = plot('tall'), hist = plot('short'), cap = h('div', { class: 'callout' });
  const redraw = () => { const st = charts.plotScan(line, hist, s, o); fillCaption(cap, st, s, o); };
  out.append(h('div', { class: 'block' },
    h('div', { class: 'toolrow' },
      sel('Metric', [['car', 'Direction-adjusted CAR'], ['bounce', 'Bounce rate']], o.metric, (v) => { o.metric = v; redraw(); }),
      sel('Horizon', s.horizons.map((k) => [k, `${k} days`]), o.horizon, (v) => { o.horizon = parseInt(v, 10); redraw(); }),
      sel('Era', s.eras.map((e) => [e.name, e.name === 'All' ? 'All (full sample)' : `${e.name} ${e.desc}`]), o.era, (v) => { o.era = v; redraw(); }),
      h('div', {}, h('label', {}, 'Min events per line'), h('input', { type: 'number', value: o.minN, min: 1, onchange: (e) => { o.minN = parseInt(e.target.value, 10) || 1; redraw(); } })),
      h('div', {}, h('label', { title: 'Lines within this many bars of the target are left out of the comparison group because they are almost the same line' }, 'Exclude neighbours ±'), h('input', { type: 'number', value: o.exclude, min: 0, onchange: (e) => { o.exclude = parseInt(e.target.value, 10) || 0; redraw(); } }))),
    line, cap, hist,
    h('p', { class: 'note' }, `Scanned ${s.windows.length} lines (${s.windows[0]}–${s.windows[s.windows.length - 1]}) on ${s.ticker} in ${s.seconds}s. Neighbouring lines share most of their events, so they are far from independent, the empirical p-value below is a rough guide, not a formal test.`)));
  redraw();
}
function fillCaption(cap, st, s, o) {
  clear(cap);
  if (st.error) { cap.append(st.error); return; }
  const f = o.metric === 'bounce' ? (v) => fmt.pct(v) : (v) => fmt.spct(v);
  cap.append(h('b', {}, `Target ${s.target}: ${f(st.target)} (n=${st.n}). `),
    `That is higher than ${st.pctBelow.toFixed(0)}% of the other ${st.m} lines (median ${f(st.median)}; middle 90% of lines: ${f(st.q05)} to ${f(st.q95)}). `,
    `Empirical one-sided p (a line this high or higher) = ${st.pUp.toFixed(3)}; two-sided = ${st.pTwo.toFixed(3)}. `,
    st.pTwo < 0.05 ? 'The target stands out from the crowd, but check other horizons and eras before trusting that.' : 'The target is unremarkable compared with lines nobody watches.');
}

// ------------------------------------------------------------------ event explorer
function renderExplorer(root) {
  clear(root);
  const res = cur(), x = state.ex, hz = state.horizon;
  let rows = res.events.filter((e) => (!x.ma || e.ma === +x.ma) && (!x.dir || e.direction === x.dir) && (!x.era || e.era === x.era)
    && (!x.outcome || (x.outcome === 'bounce' ? e[`bounce_${hz}`] === 1 : e[`bounce_${hz}`] === 0)));
  const { key, dir } = x.sort;
  rows = [...rows].sort((a, b) => ((a[key] ?? -Infinity) > (b[key] ?? -Infinity) ? dir : (a[key] ?? -Infinity) < (b[key] ?? -Infinity) ? -dir : 0));
  const per = 40, pages = Math.max(1, Math.ceil(rows.length / per));
  x.page = Math.min(x.page, pages - 1);
  const sel = (label, val, opts, fn) => h('div', {}, h('label', {}, label), h('select', { onchange: (e) => { fn(e.target.value); x.page = 0; renderExplorer(root); } }, opts.map(([v, t]) => h('option', { value: v, selected: String(v) === String(val) }, t))));
  const cols = [
    { key: 'date', label: 'Date', left: true, sortable: true }, { key: 'ma', label: 'Line', sortable: true },
    { key: 'direction', label: 'Test', left: true, sortable: true }, { key: 'era', label: 'Era', left: true, sortable: true },
    { key: 'dist_atr', label: 'Dist (ATR)', fmt: (v) => fmt.num(v, 2), sortable: true },
    { key: 'tr_ratio', label: 'Range ×', fmt: (v) => fmt.num(v, 2), sortable: true },
    { key: `ret_${hz}`, label: `Return ${hz}b`, fmt: (v) => fmt.spct(v), sortable: true },
    { key: `car_${hz}`, label: `CAR ${hz}b`, fmt: (v) => fmt.spct(v), sortable: true },
    { key: `bounce_${hz}`, label: `Bounce ${hz}b`, fmt: (v) => (v == null ? '-' : v === 1 ? 'yes' : 'no'), sortable: true },
  ];
  const detail = h('div', { id: 'ex-detail' });
  root.append(h('div', { class: 'block' }, h('h2', {}, `${res.label}: event explorer`),
    h('p', { class: 'sub' }, 'Every detected touch. Click a row to see the exact candles, the touch band, the failure level and the outcome, with the definition checked step by step.'),
    h('div', { class: 'toolrow' },
      sel('Line', x.ma, [['', 'All lines'], ...res.mas.map((m) => [m, `${m}-day`])], (v) => { x.ma = v; }),
      sel('Test', x.dir, [['', 'Both'], ['support', 'Support'], ['resistance', 'Resistance']], (v) => { x.dir = v; }),
      sel('Era', x.era, [['', 'All eras'], ...res.eras.map((e) => [e.name, `${e.name} ${e.desc}`])], (v) => { x.era = v; }),
      sel(`Outcome at ${hz} days`, x.outcome, [['', 'Any'], ['bounce', 'Bounced'], ['fail', 'Did not bounce']], (v) => { x.outcome = v; }),
      h('button', { class: 'btn', type: 'button', onclick: () => download(`${res.ticker}-events.csv`, toCSV(rows)) }, 'Download CSV')),
    dataTable(cols, rows.slice(x.page * per, (x.page + 1) * per), {
      sort: x.sort, onSort: (k) => { x.sort = { key: k, dir: x.sort.key === k ? -x.sort.dir : 1 }; renderExplorer(root); },
      selected: (r) => x.selected && r.date === x.selected.date && r.ma === x.selected.ma,
      onRowClick: (r) => { x.selected = r; loadEvent(r, detail); renderExplorerTableHighlight(root); },
    }),
    h('div', { class: 'pager' }, h('button', { class: 'btn tiny', type: 'button', disabled: x.page === 0, onclick: () => { x.page--; renderExplorer(root); } }, '‹ Prev'),
      `Page ${x.page + 1} of ${pages}, ${rows.length} events`,
      h('button', { class: 'btn tiny', type: 'button', disabled: x.page >= pages - 1, onclick: () => { x.page++; renderExplorer(root); } }, 'Next ›'))),
    detail);
  if (x.selected && x.win) drawEvent(detail); else detail.append(h('div', { class: 'note', style: 'padding:6px 2px' }, 'Select an event above.'));
}
function renderExplorerTableHighlight(root) {
  const x = state.ex;
  $$('table.dt tbody tr', root).forEach((tr) => tr.classList.toggle('sel', tr.children[0].textContent === x.selected.date && tr.children[1].textContent === String(x.selected.ma)));
}
async function loadEvent(ev, detail) {
  const x = state.ex;
  clear(detail).append(h('div', { class: 'block' }, h('span', { class: 'spinner' }), 'Loading candles…'));
  try {
    x.win = await engine.call('event_window', { config: state.resp.config, ticker: cur().ticker, ma: ev.ma, date: ev.date, direction: ev.direction });
    drawEvent(detail);
  } catch (e) { clear(detail).append(h('div', { class: 'callout warn' }, e.message)); }
}
function drawEvent(detail) {
  const x = state.ex, ev = x.selected, w = x.win, cfg = state.resp.config, i0 = w.event_index;
  clear(detail);
  const chart = plot('tall');
  const sup = ev.direction === 'support';
  const px = (j) => (cfg.breach_basis === 'low' ? (sup ? w.low[j] : w.high[j]) : w.close[j]);
  // approach check
  const approach = [];
  for (let k = 1; k <= cfg.approach; k++) {
    const j = i0 - k;
    if (j < 0) break;
    const ok = sup ? w.close[j] > w.sma[j] : w.close[j] < w.sma[j];
    approach.push([k, w.close[j], w.sma[j], ok]);
  }
  const touchOk = sup ? w.low[i0] <= w.upper[i0] : w.high[i0] >= w.lower[i0];
  const mark = (ok) => h('span', { class: ok ? 'ok' : 'no' }, ok ? 'yes' : 'no');
  const outcomes = cfg.horizons.map((k) => {
    if (i0 + k >= w.dates.length) return h('li', {}, `${k} days: window runs past the end of the data`);
    let breached = false;
    for (let j = i0; j <= i0 + k; j++) if (sup ? px(j) < w.breach[j] : px(j) > w.breach[j]) breached = true;
    const higher = sup ? w.close[i0 + k] > w.close[i0] : w.close[i0 + k] < w.close[i0];
    const ret = w.close[i0 + k] / w.close[i0] - 1;
    return h('li', {}, `${k} days: close ${fmt.money(w.close[i0 + k])} (${fmt.spct(ret)}), ${sup ? 'higher' : 'lower'} than entry? `, mark(higher), ', breached failure level? ', mark(!breached), ` to bounce = `, mark(higher && !breached));
  });
  detail.append(h('div', { class: 'block explain' },
    h('h2', {}, `${ev.ma}-day line: ${ev.direction} test on ${ev.date}`),
    h('p', { class: 'sub' }, `${ev.era}, closed ${fmt.num(ev.dist_atr, 2)} ATR ${ev.dist_atr >= 0 ? 'above' : 'below'} the line, event-day range ${fmt.num(ev.tr_ratio, 2)}× its recent average`),
    chart,
    h('h3', {}, '1, Approach'), h('p', { class: 'note' }, `The previous ${cfg.approach} closes must all be strictly ${sup ? 'above' : 'below'} the line (checked against each day’s own line value).`),
    h('ul', { class: 'step-list' }, approach.map(([k, c, s, ok]) => h('li', {}, `t−${k}: close ${fmt.money(c)} vs line ${fmt.money(s)} `, mark(ok)))),
    h('h3', {}, '2, Touch'), h('p', {}, sup
      ? ['Low ', h('b', {}, fmt.money(w.low[i0])), ` ≤ upper band edge (line + ${cfg.band}×ATR) `, h('b', {}, fmt.money(w.upper[i0])), ' ', mark(touchOk)]
      : ['High ', h('b', {}, fmt.money(w.high[i0])), ` ≥ lower band edge (line − ${cfg.band}×ATR) `, h('b', {}, fmt.money(w.lower[i0])), ' ', mark(touchOk)]),
    h('p', { class: 'note' }, `ATR on the touch day = ${fmt.num(w.atr_event, 4)}; entry is the close, ${fmt.money(w.close[i0])}.`),
    h('h3', {}, '3, Outcomes'), h('p', { class: 'note' }, `Failure level = line ${sup ? '−' : '+'} ${cfg.breach}×ATR (on ${cfg.breach_basis === 'low' ? 'intraday ' + (sup ? 'lows' : 'highs') : 'closes'}); it moves with the line, ATR is frozen at the event day.`),
    h('ul', { class: 'step-list' }, outcomes),
    h('p', { class: 'note' }, `Abnormal (CAR) numbers subtract the average ${era2(state.resp, ev.era)} return for the same horizon, then flip the sign for resistance tests, see the table row above.`)));
  charts.plotEventWindow(chart, w, ev, ev.direction, cfg.horizons, cfg);
}
const era2 = (resp, name) => `${name} (${cur().eras.find((e) => e.name === name)?.desc ?? ''})`;

// ------------------------------------------------------------------ method
let methodLoaded = false;
async function renderMethod(root) {
  if (!methodLoaded) {
    clear(root).append(h('div', { class: 'note' }, 'Loading…'));
    try {
      const html = await loadText('method-html', 'static/method.html');
      root.innerHTML = html;
      methodLoaded = true;
    } catch { root.textContent = 'Could not load the method page.'; return; }
    wireCalculators(root);
  }
  typeset(root);
}
function typeset(root, tries = 0) {
  if (window.renderMathInElement) {
    window.renderMathInElement(root, { delimiters: [{ left: '$$', right: '$$', display: true }, { left: '$', right: '$', display: false }], throwOnError: false });
  } else if (tries < 40) setTimeout(() => typeset(root, tries + 1), 150);
}
function wireCalculators(root) {
  const g = (id) => parseFloat(root.querySelector('#' + id).value);
  const touch = () => {
    const sma = g('c-sma'), atr = g('c-atr'), band = g('c-band'), lo = g('c-low'), hi = g('c-high');
    const up = sma + band * atr, dn = sma - band * atr;
    root.querySelector('#c-touch-out').textContent =
      `Band = [${dn.toFixed(2)}, ${up.toFixed(2)}]\nSupport touch (needs prior closes above): Low ${lo} ≤ ${up.toFixed(2)}? ${lo <= up ? 'YES' : 'no'}\nResistance touch (needs prior closes below): High ${hi} ≥ ${dn.toFixed(2)}? ${hi >= dn ? 'YES' : 'no'}`;
  };
  const wilson = () => {
    const x = g('c-x'), n = g('c-n'), z = 1.959964;
    if (!(n > 0) || x < 0 || x > n) { root.querySelector('#c-wilson-out').textContent = 'Need 0 ≤ successes ≤ n'; return; }
    const p = x / n, d = 1 + z * z / n, c = (p + z * z / (2 * n)) / d, hw = (z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d;
    const nlo = p - z * Math.sqrt(p * (1 - p) / n), nhi = p + z * Math.sqrt(p * (1 - p) / n);
    root.querySelector('#c-wilson-out').textContent =
      `p̂ = ${(100 * p).toFixed(1)}%\nWilson 95% CI: ${(100 * Math.max(0, c - hw)).toFixed(1)}% – ${(100 * Math.min(1, c + hw)).toFixed(1)}%\nNaive (normal) CI: ${(100 * Math.max(0, nlo)).toFixed(1)}% – ${(100 * Math.min(1, nhi)).toFixed(1)}%`;
  };
  ['c-sma', 'c-atr', 'c-band', 'c-low', 'c-high'].forEach((id) => root.querySelector('#' + id).addEventListener('input', touch));
  ['c-x', 'c-n'].forEach((id) => root.querySelector('#' + id).addEventListener('input', wilson));
  touch(); wilson();
}

boot();
