// Kalshi 15-minute lab: parameter form, results, and an editable in-browser Python console.

import { $, $$, h, clear, fmt, sigClass, stars, download, toCSV, seriesColor, cssVar } from './util.js';
import * as engine from './engine.js';
import { base, merge, draw, title } from './charts.js';
import { dataTable } from './tables.js';

const STORE = 'smalab.kalshi.v1';
const ALL_CPS = [14, 12, 10, 8, 6, 5, 4, 3, 2, 1];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const FEE_PRESETS = { taker: 0.07, maker: 0.0175, half: 0.035, none: 0 };

const S = { meta: null, root: null, cps: new Set([14, 12, 10, 8, 6, 5, 4, 3, 2, 1]), days: new Set(), result: null, split: 'all', tab: 'results', ranStudy: false };
const el = (id) => S.root.querySelector('#' + id);

// ------------------------------------------------------------------ build UI
export function initKalshi(root, meta) {
  S.meta = meta;
  S.root = root;
  clear(root);
  root.append(
    h('div', { class: 'page' },
      h('p', { class: 'lead' }, 'Are “Yes” contracts on Kalshi’s 15-minute crypto markets overpriced? Choose a market and press Run to see how often “Yes” won at each price, and whether always buying “No” would have paid.'),
      h('section', { class: 'card inputs' },
        h('div', { class: 'form-grid' }, ...basics()),
        h('details', { class: 'adv' }, h('summary', {}, 'More settings'), h('div', { class: 'adv-body' }, ...advanced())),
        h('div', { class: 'runrow' },
          h('button', { class: 'btn primary big', id: 'k-run', type: 'button', onclick: runStudy }, 'Run'),
          h('button', { class: 'btn ghost', type: 'button', onclick: () => { apply(meta.defaults); toast('Reset to defaults.'); } }, 'Reset'),
          h('span', { class: 'status', id: 'k-status', role: 'status' }))),
      h('section', { class: 'output' },
        h('nav', { class: 'tabs', id: 'k-tabs' },
          ...[['results', 'Results'], ['console', 'Python console'], ['notes', 'How it works']].map(([key, t]) => h('button', { 'data-tab': key, class: key === 'results' ? 'active' : '', type: 'button', onclick: () => tab(key) }, t))),
        h('section', { class: 'panel active', id: 'k-results' }, intro()),
        h('section', { class: 'panel', id: 'k-console' }),
        h('section', { class: 'panel', id: 'k-notes' }))));
  wire();
  restore();
  buildConsole();
  buildNotes();
  window.addEventListener('themechange', () => { if (S.result) renderResults(); });
  S.root.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && S.tab === 'results') runStudy(); });
}

const field = (label, input, hint) => h('div', { class: 'f' }, h('label', { class: 'lbl' }, label, hint ? h('span', { class: 'hint' }, ` ${hint}`) : null), input);
const num = (id, min, max, step = 'any') => h('input', { id, type: 'number', min, max, step });
const sel = (id, opts) => h('select', { id }, opts.map(([v, t]) => h('option', { value: v }, t)));
const card = (n, titleText, open, ...kids) => h('details', { class: 'card', open: open ? '' : null }, h('summary', {}, h('span', { class: 'step' }, n), titleText), h('div', { class: 'card-body' }, ...kids));

function basics() {
  const series = Object.entries(S.meta.series).map(([k, n]) => [k, `${n} (${k})`]);
  return [
    h('div', { class: 'f span2' }, field('Market', sel('k-series', series))),
    field('Data', sel('k-source', [['auto', 'Real data (else simulated)'], ['live', 'Real data only'], ['synthetic', 'Simulated data']])),
    field('Days of history', num('k-days', 0.25, 90, 'any')),
    field('Buy this many minutes before expiry', sel('k-entry', [])),
    field('Price to use', sel('k-pricesrc', [['trade', 'Last trade'], ['mid', 'Midpoint of bid and ask'], ['executable', 'What you would really pay (the ask)']])),
    field('Rule 3: “Yes” price from (¢)', num('k-min', 0, 100, 1)),
    field('…to (¢)', num('k-max-price', 0, 100, 1)),
    field('Fees', sel('k-fee', [['taker', 'Kalshi taker fee'], ['half', 'Half the taker fee'], ['maker', 'Maker-like fee'], ['none', 'No fees'], ['custom', 'Custom…']])),
    h('div', { id: 'k-fee-custom-wrap', hidden: '' }, field('Fee rate', num('k-fee-custom', 0, 1, 'any'))),
    field('Contracts per trade', num('k-contracts', 1, 10000, 1)),
  ];
}

function advanced() {
  return [
    h('h3', {}, 'Dates'),
    h('div', { class: 'form-grid' },
      field('From (UTC)', h('input', { id: 'k-start', type: 'date' }), 'overrides “days”'), field('To (UTC)', h('input', { id: 'k-end', type: 'date' })),
      field('Most contracts to load', num('k-max', 50, 3000, 50))),
    h('h3', {}, 'Timing'),
    h('label', { class: 'lbl' }, 'Minutes before expiry to record prices', h('span', { class: 'hint' }, ' (the buy time above must be one of these)')),
    h('div', { class: 'chips toggle', id: 'k-cps' }),
    h('div', { class: 'form-grid' },
      field('Only contracts expiring from (UTC hour)', sel('k-hlo', [['', 'any'], ...Array.from({ length: 24 }, (_, i) => [String(i), `${String(i).padStart(2, '0')}:00`])])),
      field('…until', sel('k-hhi', [['', 'any'], ...Array.from({ length: 24 }, (_, i) => [String(i), `${String(i).padStart(2, '0')}:59`])]))),
    h('label', { class: 'lbl' }, 'Weekdays', h('span', { class: 'hint' }, ' (none selected = every day)')),
    h('div', { class: 'chips toggle', id: 'k-days-chips' }),
    h('h3', {}, 'Strikes and bins'),
    h('div', { class: 'form-grid' },
      field('Up / down means strike vs spot…', sel('k-spotref', [['checkpoint', 'at the buy time (recommended)'], ['open', 'at market open']])),
      field('Price bin width (¢)', sel('k-bin', [['5', '5'], ['10', '10'], ['20', '20']])),
      field('p-value test', sel('k-ptest', [['twoprop', 'Two-proportion z'], ['binomial', 'Exact binomial'], ['pbinom', 'Poisson-binomial z']]))),
    h('label', { class: 'cb-line' }, h('input', { id: 'k-tails', type: 'checkbox' }), ' Also show prices under 10¢ and over 90¢'),
    h('h3', {}, 'Strategies to test'),
    h('label', { class: 'cb-line' }, h('input', { id: 'k-r1', type: 'checkbox' }), ' Rule 1: buy “No” on every contract'),
    h('label', { class: 'cb-line' }, h('input', { id: 'k-r2', type: 'checkbox' }), ' Rule 2: buy “No” only when the strike is above spot'),
    h('label', { class: 'cb-line' }, h('input', { id: 'k-r3', type: 'checkbox' }), ' Rule 3: buy “No” only when “Yes” is inside the price range above'),
    h('label', { class: 'cb-line' }, h('input', { id: 'k-c-on', type: 'checkbox' }), ' Your own rule'),
    h('div', { class: 'form-grid' },
      field('Buy', sel('k-c-side', [['no', '“No”'], ['yes', '“Yes”']])), field('When the strike is', sel('k-c-dir', [['', 'anything'], ['upside', 'above spot'], ['downside', 'below spot']])),
      field('and “Yes” costs from (¢)', num('k-c-min', 0, 100, 1)), field('…to (¢)', num('k-c-max', 0, 100, 1))),
    h('div', { class: 'form-grid', style: 'margin-top:12px' }, field('Starting capital ($)', num('k-capital', 1, 1e9, 'any'))),
    h('h3', {}, 'Simulated data only'),
    h('p', { class: 'help' }, 'Used when the data is simulated. The overpricing is planted on purpose so you can see whether the tests find it. Set both premiums to 0 for a perfectly fair market.'),
    h('div', { class: 'form-grid' },
      field('Overpricing of “Yes” (¢)', num('k-bias', -20, 20, 'any')), field('Extra when strike is above spot (¢)', num('k-upx', -20, 20, 'any')),
      field('Price noise (¢)', num('k-noise', 0, 20, 'any')), field('Random seed', num('k-seed', 0, 2147483647, 1))),
  ];
}

const intro = () => h('div', { class: 'empty' },
  h('h2', {}, 'No results yet'),
  h('p', {}, 'This loads finished 15-minute contracts, checks how often “Yes” really won at each price, then tests a plain “buy No” strategy after Kalshi’s fees.'),
  h('p', { class: 'note' }, 'The first run downloads a Python engine (about 30 MB, then cached). Change any number above and run again.'));

// ------------------------------------------------------------------ wiring & params
function renderChips() {
  const box = clear(el('k-cps'));
  ALL_CPS.forEach((m) => box.append(h('span', { class: 'tchip' + (S.cps.has(m) ? ' on' : ''), role: 'button', tabindex: 0, onclick: () => toggleCp(m), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleCp(m); } } }, `${m}m`)));
  const entry = el('k-entry'), keep = entry.value;
  clear(entry);
  [...S.cps].sort((a, b) => b - a).forEach((m) => entry.append(h('option', { value: String(m) }, `${m} min before expiry`)));
  if ([...entry.options].some((o) => o.value === keep)) entry.value = keep;
  const dbox = clear(el('k-days-chips'));
  DAYS.forEach((d, i) => dbox.append(h('span', { class: 'tchip' + (S.days.has(i) ? ' on' : ''), role: 'button', tabindex: 0, title: 'Leave all off for every day', onclick: () => { S.days.has(i) ? S.days.delete(i) : S.days.add(i); renderChips(); } }, d)));
}
function toggleCp(m) {
  if (S.cps.has(m)) { if (S.cps.size > 1) S.cps.delete(m); else toast('Keep at least one checkpoint.'); } else S.cps.add(m);
  renderChips();
}
function wire() {
  el('k-fee').addEventListener('change', () => { el('k-fee-custom-wrap').hidden = el('k-fee').value !== 'custom'; });
  renderChips();
}

function collect() {
  const v = (id) => el(id).value;
  const n = (id) => parseFloat(v(id));
  const fee = v('k-fee') === 'custom' ? n('k-fee-custom') : FEE_PRESETS[v('k-fee')];
  const hours = v('k-hlo') !== '' && v('k-hhi') !== '' ? [parseInt(v('k-hlo'), 10), parseInt(v('k-hhi'), 10)] : null;
  return {
    source: v('k-source'), series: v('k-series'), days: n('k-days'), max_markets: n('k-max'),
    start: v('k-start') || null, end: v('k-end') || null,
    checkpoints: [...S.cps].sort((a, b) => b - a), entry_checkpoint: parseInt(v('k-entry'), 10),
    price_source: v('k-pricesrc'), hours, weekdays: S.days.size && S.days.size < 7 ? [...S.days].sort() : null,
    spot_ref: v('k-spotref'), bin_width: parseInt(v('k-bin'), 10), p_test: v('k-ptest'), tails: el('k-tails').checked,
    rules: ['r1', 'r2', 'r3'].filter((k) => el(`k-${k}`).checked),
    min_price: n('k-min'), max_price: n('k-max-price'),
    custom: { enabled: el('k-c-on').checked, side: v('k-c-side'), direction: v('k-c-dir'), min: n('k-c-min'), max: n('k-c-max') },
    contracts: parseInt(v('k-contracts'), 10), capital: n('k-capital'), fee_rate: fee, fee_choice: v('k-fee'), fee_custom: n('k-fee-custom'),
    seed: parseInt(v('k-seed'), 10), bias: n('k-bias'), upside_extra: n('k-upx'), noise: n('k-noise'),
  };
}
function apply(p) {
  const set = (id, val) => { if (val !== undefined && val !== null) el(id).value = String(val); };
  set('k-source', p.source); set('k-series', p.series); set('k-days', p.days); set('k-max', p.max_markets);
  el('k-start').value = p.start || ''; el('k-end').value = p.end || '';
  S.cps = new Set(p.checkpoints || ALL_CPS);
  S.days = new Set(p.weekdays || []);
  renderChips();
  set('k-entry', p.entry_checkpoint); set('k-pricesrc', p.price_source);
  el('k-hlo').value = p.hours ? String(p.hours[0]) : ''; el('k-hhi').value = p.hours ? String(p.hours[1]) : '';
  set('k-spotref', p.spot_ref); set('k-bin', p.bin_width); set('k-ptest', p.p_test); el('k-tails').checked = !!p.tails;
  ['r1', 'r2', 'r3'].forEach((k) => { el(`k-${k}`).checked = (p.rules || []).includes(k); });
  set('k-min', p.min_price); set('k-max-price', p.max_price);
  const c = p.custom || {};
  el('k-c-on').checked = !!c.enabled; set('k-c-side', c.side || 'no'); set('k-c-dir', c.direction || ''); set('k-c-min', c.min ?? 0); set('k-c-max', c.max ?? 100);
  set('k-contracts', p.contracts); set('k-capital', p.capital);
  const choice = p.fee_choice || (Object.entries(FEE_PRESETS).find(([, r]) => r === p.fee_rate) || ['custom'])[0];
  set('k-fee', choice); set('k-fee-custom', p.fee_custom ?? p.fee_rate ?? 0.07);
  el('k-fee-custom-wrap').hidden = choice !== 'custom';
  set('k-seed', p.seed); set('k-bias', p.bias); set('k-upx', p.upside_extra); set('k-noise', p.noise);
}
function restore() {
  let p = S.meta.defaults;
  try { const saved = localStorage.getItem(STORE); if (saved) p = { ...p, ...JSON.parse(saved) }; } catch { /* ignore */ }
  apply(p);
}

const setStatus = (msg, kind = '') => { const s = el('k-status'); s.className = 'status ' + kind; clear(s); if (kind === 'busy') s.append(h('span', { class: 'spinner' })); s.append(msg); };
const toast = (msg) => setStatus(msg, '');

// ------------------------------------------------------------------ run
async function runStudy() {
  const p = collect();
  const btn = el('k-run');
  btn.disabled = true;
  const t0 = performance.now();
  setStatus('Starting Python…', 'busy');
  tab('results');
  try {
    try { localStorage.setItem(STORE, JSON.stringify(p)); } catch { /* ignore */ }
    S.result = await engine.call('lab_run', { params: p }, { onProgress: (t) => setStatus(t, 'busy') });
    S.ranStudy = true;
    setStatus(`Done in ${((performance.now() - t0) / 1000).toFixed(1)}s.`);
    renderResults();
  } catch (e) {
    setStatus(e.message, 'err');
    clear(el('k-results')).append(h('div', { class: 'callout warn' }, h('b', {}, 'The study could not run. '), e.message,
      h('p', { class: 'note' }, 'Tip: choose “Synthetic” as the data source to test the pipeline without any network access.')));
  } finally { btn.disabled = false; }
}

function tab(name) {
  S.tab = name;
  $$('#k-tabs button', S.root).forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  ['results', 'console', 'notes'].forEach((k) => el(`k-${k}`).classList.toggle('active', k === name));
  if (name === 'notes') typeset(el('k-notes'));
  window.dispatchEvent(new Event('resize'));
}

// ------------------------------------------------------------------ results
const gapTxt = (g) => (g == null ? 'n/a' : `${g >= 0 ? '+' : ''}${g.toFixed(1)} pp`);
const pTxt = (p) => (p == null ? 'n/a' : fmt.p(p) + stars(p));
const usd = (x) => (x == null ? 'n/a' : `${x < 0 ? '−' : ''}$${Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

function renderResults() {
  const r = S.result, root = clear(el('k-results'));
  const s = r.summary;
  const live = s.source === 'live';
  const calChart = h('div', { class: 'plot', style: 'min-height:520px' });
  const eqChart = h('div', { class: 'plot short' });
  const hrChart = h('div', { class: 'plot short' });
  const calHost = h('div');

  root.append(h('div', { class: 'block' },
    h('h2', {}, `${s.series}: ${S.meta.series[s.series]} 15-minute contracts`),
    h('p', { class: 'sub' }, h('span', { class: 'badge ' + (live ? 'live' : 'syn') }, live ? 'LIVE DATA' : 'SYNTHETIC DATA'),
      ` ${s.markets.toLocaleString()} settled contracts, ${s.priced.toLocaleString()} with a ${s.entry_checkpoint}-minute price, ${s.start} to ${s.end} UTC, price = ${s.price_source}`),
    h('div', {}, pill(`avg Yes price ${s.overall_avg_yes.toFixed(1)}¢`), pill(`Yes won ${(100 * s.overall_yes_rate).toFixed(1)}%`),
      pill(`gap ${gapTxt(s.overall_avg_yes - 100 * s.overall_yes_rate)}`),
      pill(`upside ${s.directions.upside || 0}, downside ${s.directions.downside || 0}`)),
    s.notes.length ? h('div', { class: 'callout warn' }, h('ul', { class: 'warnlist' }, s.notes.map((n) => h('li', {}, n)))) : null,
    h('p', { class: 'note' }, 'Gap = average Yes price minus the share of contracts that actually resolved Yes. Positive means Yes was overpriced. The 45° line on the chart is a perfectly calibrated market.')));

  root.append(h('div', { class: 'block' }, h('h2', {}, '1, Overpricing test: calibration'), calChart,
    h('div', { class: 'seg small', id: 'k-split', style: 'margin:10px 0' }, ['all', 'upside', 'downside'].map((k) => h('button', { type: 'button', class: S.split === k ? 'on' : '', onclick: () => { S.split = k; renderResults(); } }, k === 'all' ? 'All contracts' : `${k[0].toUpperCase()}${k.slice(1)} strikes`))),
    calHost, interpretCal(r)));
  root.append(h('div', { class: 'block' }, h('h2', {}, '2, Asymmetry test: is the bias stronger on upside strikes?'), asymmetryBlock(r.asymmetry)));
  root.append(h('div', { class: 'block' }, h('h2', {}, '3, Strategy test: Buy “No” after fees'), strategyTable(r), eqChart, strategyNotes(r)));
  root.append(h('div', { class: 'block' }, h('h2', {}, '4, Timing: overpricing by hour of day (UTC)'), hrChart,
    h('p', { class: 'note' }, 'Each bar pools every price level for contracts expiring in that hour. Hours with few contracts are noisy; look for stable patterns, not single bars.')));
  root.append(h('div', { class: 'block' }, h('div', { class: 'toolrow' },
    h('button', { class: 'btn', type: 'button', onclick: () => download(`kalshi-${s.series}-contracts.csv`, toCSV(r.contracts)) }, 'Download contracts (CSV)'),
    h('button', { class: 'btn', type: 'button', onclick: () => download('kalshi-lab-results.json', JSON.stringify(r), 'application/json') }, 'Download results (JSON)'),
    h('button', { class: 'btn', type: 'button', onclick: () => tab('console') }, 'Open in the Python console'))));

  calHost.append(calTable(r.calibration[S.split]));
  drawCalibration(calChart, r);
  drawEquity(eqChart, r);
  drawHourly(hrChart, r);
}
const pill = (t) => h('span', { class: 'pill' }, t);

function calTable(t) {
  const rows = [...t.rows, { ...t.overall, bin: 'ALL (binned range)' }];
  return dataTable([
    { key: 'bin', label: 'Price bin', left: true }, { key: 'count', label: 'Count' },
    { key: 'avg_yes', label: 'Avg Yes price', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(1)}¢`) },
    { key: 'actual_pct', label: 'Actual Yes win %', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(1)}%`) },
    { key: 'gap', label: 'Overpricing gap', fmt: gapTxt },
    { key: 'p_value', label: `p-value (${t.p_test})`, fmt: pTxt, cls: (r) => sigClass(r.p_value) },
    { key: 'ci_lo', label: '95% CI of actual', fmt: (v, r) => (v == null ? 'n/a' : `${v.toFixed(1)}–${r.ci_hi.toFixed(1)}%`) },
  ], rows, { selected: (r) => r.bin.startsWith('ALL') });
}

function interpretCal(r) {
  const o = r.calibration.all.overall;
  if (!o.count) return h('p', { class: 'note' }, 'No contracts fall inside the binned price range.');
  const sig = o.p_value != null && o.p_value < 0.05;
  return h('div', { class: 'callout' },
    `Across ${o.count.toLocaleString()} contracts priced ${o.lo}–${o.hi}¢, the average Yes price was ${o.avg_yes.toFixed(1)}¢ but Yes won ${o.actual_pct.toFixed(1)}% of the time (gap ${gapTxt(o.gap)}, p = ${fmt.p(o.p_value)}). `,
    sig ? (o.gap > 0 ? 'That is statistically significant overpricing of Yes.' : 'Yes was significantly UNDERpriced here, the opposite of the hypothesis.') : 'That gap is not statistically distinguishable from zero with this sample.',
    h('span', { class: 'note' }, ' Several bins below may show large gaps by luck: with n of 20–40 per bin the noise is ±10 pp or more.'));
}

function asymmetryBlock(a) {
  const row = (label, g) => h('tr', {}, h('td', { class: 'l' }, label), h('td', {}, g.n_upside), h('td', {}, g.gap_upside == null ? 'n/a' : gapTxt(100 * g.gap_upside)),
    h('td', {}, g.n_downside), h('td', {}, g.gap_downside == null ? 'n/a' : gapTxt(100 * g.gap_downside)),
    h('td', {}, g.diff == null ? 'n/a' : gapTxt(100 * g.diff)), h('td', {}, g.ci_lo == null ? 'n/a' : `${(100 * g.ci_lo).toFixed(1)} to ${(100 * g.ci_hi).toFixed(1)} pp`),
    h('td', { class: sigClass(g.welch_p) }, pTxt(g.welch_p)));
  return h('div', {},
    h('p', { class: 'sub' }, 'Upside strike = strike above spot (Yes needs BTC to rise); downside = strike below spot. Gap = Yes price − realised outcome, averaged per contract.'),
    h('div', { class: 'tablewrap' }, h('table', { class: 'dt' }, h('thead', {}, h('tr', {}, ['Comparison', 'n up', 'Gap up', 'n down', 'Gap down', 'Up − down', '95% CI', 'Welch p'].map((t, i) => h('th', { class: i === 0 ? 'l' : '' }, t)))),
      h('tbody', {}, row('All prices', a), row(`Price-matched (${a.overlap[0]}–${a.overlap[1]}¢ only)`, a.matched)))),
    h('div', { class: 'callout warn' }, h('b', {}, 'Careful: '), 'in an up/down market an upside strike is almost always a cheap out-of-the-money Yes (under 50¢) and a downside strike an expensive in-the-money one, so the “all prices” row mixes direction with the well-known favourite–longshot bias. The price-matched row compares the two directions where both trade, which is the fairer test of an optimism asymmetry.'));
}

function strategyTable(r) {
  return dataTable([
    { key: 'name', label: 'Strategy', left: true }, { key: 'trades', label: 'Trades' },
    { key: 'win_rate', label: 'Win rate', fmt: (v) => (v == null ? 'n/a' : `${(100 * v).toFixed(1)}%`) },
    { key: 'breakeven_win_rate', label: 'Break-even win rate', fmt: (v) => (v == null ? 'n/a' : `${(100 * v).toFixed(1)}%`) },
    { key: 'gross_profit', label: 'Gross profit', fmt: usd }, { key: 'fees', label: 'Total fees', fmt: usd },
    { key: 'net_profit', label: 'Net profit', fmt: usd },
    { key: 'roi_pct', label: 'ROI %', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(2)}%`) },
    { key: 'max_drawdown', label: 'Max DD', fmt: usd },
    { key: 'profit_factor', label: 'Profit factor', fmt: (v) => fmt.num(v, 2) }, { key: 'sharpe', label: 'Sharpe (daily)', fmt: (v) => fmt.num(v, 2) },
    { key: 'p_value', label: 'p (mean net ≠ 0)', fmt: pTxt, cls: (x) => sigClass(x.p_value) },
    { key: 'net_cents_ci', label: '95% CI net ¢/contract', fmt: (v) => (v ? `${v[0].toFixed(1)} to ${v[1].toFixed(1)}` : 'n/a') },
  ], r.strategies);
}
function strategyNotes(r) {
  const best = [...r.strategies].filter((s) => s.trades >= 10).sort((a, b) => (b.net_profit ?? -1e9) - (a.net_profit ?? -1e9))[0];
  const items = [];
  if (best) {
    const sig = best.p_value != null && best.p_value < 0.05 && best.net_profit > 0;
    items.push(`Best rule by net profit: “${best.name}”, ${usd(best.net_profit)} on ${best.trades} trades (ROI ${fmt.num(best.roi_pct, 2)}%). ${sig ? 'Its mean per-trade profit is significantly above zero (p < 0.05), still one of several rules tried, so treat it with suspicion.' : 'Its per-trade profit is not distinguishable from zero.'}`);
  }
  items.push('A “Buy No” trade wins when the market settles No; it only profits long-run if the win rate exceeds the break-even rate (entry price + fee). That is the “Break-even win rate” column.');
  return h('div', { class: 'callout' }, h('ul', { class: 'warnlist', style: 'margin:0' }, items.map((t) => h('li', {}, t))));
}

// ------------------------------------------------------------------ charts
function drawCalibration(div, r) {
  const colors = { all: seriesColor(0), upside: seriesColor(1), downside: seriesColor(2) };
  const traces = [{ x: [0, 100], y: [0, 100], mode: 'lines', name: 'Fair value (45° line)', line: { color: cssVar('--ink-3'), dash: 'dash', width: 1.5 }, hoverinfo: 'skip' }];
  for (const split of ['all', 'upside', 'downside']) {
    const rows = r.calibration[split].rows.filter((x) => x.count);
    if (!rows.length) continue;
    traces.push({
      x: rows.map((x) => x.avg_yes), y: rows.map((x) => x.actual_pct), mode: 'lines+markers', type: 'scatter',
      name: `${split === 'all' ? 'All' : split[0].toUpperCase() + split.slice(1)} (n=${rows.reduce((a, x) => a + x.count, 0)})`,
      line: { color: colors[split], width: 2 }, marker: { size: 8 },
      error_y: { type: 'data', symmetric: false, array: rows.map((x) => x.ci_hi - x.actual_pct), arrayminus: rows.map((x) => x.actual_pct - x.ci_lo), color: colors[split], thickness: 1, width: 3 },
      customdata: rows.map((x) => [x.bin, x.count, x.gap, x.p_value]),
      hovertemplate: '%{customdata[0]}<br>avg Yes %{x:.1f}¢ to won %{y:.1f}%<br>n=%{customdata[1]}, gap %{customdata[2]:+.1f} pp<br>p=%{customdata[3]:.3f}<extra></extra>',
      visible: split === 'all' || true,
    });
  }
  draw(div, traces, merge(base(), {
    height: 520, title: title('Yes price vs actual win rate: below the line means Yes is overpriced'),
    xaxis: { title: { text: 'Average Yes price (implied probability, ¢)' }, range: [0, 100] },
    yaxis: { title: { text: 'Actual Yes win rate (%)' }, range: [0, 100] }, legend: { orientation: 'h', y: -0.15 },
  }));
}
function drawEquity(div, r) {
  const names = Object.keys(r.equity);
  const traces = names.map((n, i) => ({ x: r.equity[n].t, y: r.equity[n].cum, mode: 'lines', type: 'scatter', name: n, line: { color: seriesColor(i), width: 2 }, hovertemplate: '%{x}<br>cumulative net $%{y:.2f}<extra></extra>' }));
  if (!traces.length) { div.innerHTML = '<p class="note" style="padding:20px">No rules selected.</p>'; return; }
  draw(div, traces, merge(base(), { height: 340, title: title('Cumulative net profit after fees ($)'), yaxis: { title: { text: 'Cumulative net PnL ($)' }, tickprefix: '$' }, legend: { orientation: 'h', y: -0.3 },
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: cssVar('--ink-3'), width: 1 } }] }));
}
function drawHourly(div, r) {
  const rows = r.hourly;
  draw(div, [{ type: 'bar', x: rows.map((x) => x.hour), y: rows.map((x) => x.gap), marker: { color: seriesColor(0), line: { color: cssVar('--surface'), width: 1 } },
    customdata: rows.map((x) => [x.count, x.avg_yes, x.actual_pct]), hovertemplate: 'hour %{x}:00 UTC<br>gap %{y:+.1f} pp<br>n=%{customdata[0]}, avg Yes %{customdata[1]:.1f}¢, won %{customdata[2]:.1f}%<extra></extra>' }],
  merge(base(), { height: 320, title: title('Overpricing gap by UTC hour of expiry (pp, positive = Yes overpriced)'), xaxis: { title: { text: 'Hour (UTC)' }, dtick: 1 }, yaxis: { title: { text: 'Gap (pp)' } }, showlegend: false,
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: cssVar('--ink-3'), width: 1 } }] }));
}

// ------------------------------------------------------------------ console
function buildConsole() {
  const ex = S.meta.examples, names = Object.keys(ex);
  const area = h('textarea', { id: 'k-code', class: 'code', spellcheck: 'false', rows: 16 });
  area.value = ex[names[0]];
  area.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') { e.preventDefault(); const s = area.selectionStart; area.setRangeText('    ', s, area.selectionEnd, 'end'); }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); runCode(); }
  });
  const out = h('div', { id: 'k-out', class: 'console-out' }, h('span', { class: 'note' }, 'Output appears here.'));
  const run = h('button', { class: 'btn primary', type: 'button', id: 'k-code-run', onclick: runCode }, 'Run ▶');
  clear(el('k-console')).append(
    h('div', { class: 'block' }, h('h2', {}, 'Python console'),
      h('p', { class: 'sub' }, 'Real Python running in your browser. Edit the code and press Run (Ctrl/⌘ + Enter). The variables below always hold the data from your latest “Run study”.'),
      h('div', { class: 'vars' }, ['raw', 'frame', 'params', 'trades', 'pd', 'np', 'kalshi_data', 'calibration', 'backtest', 'kstats'].map((v) => h('code', { class: 'pill' }, v))),
      h('div', { class: 'toolrow', style: 'margin-top:10px' },
        h('div', {}, h('label', {}, 'Examples'), h('select', { id: 'k-ex', onchange: (e) => { area.value = ex[e.target.value]; } }, names.map((n) => h('option', { value: n }, n)))),
        run, h('button', { class: 'btn', type: 'button', onclick: async () => { try { await engine.call('reset_console', {}); out.textContent = 'Namespace reset.'; } catch (e) { out.textContent = e.message; } } }, 'Reset namespace'),
        h('button', { class: 'btn', type: 'button', onclick: () => { tab('results'); runStudy(); } }, 'Re-run study first')),
      area, out,
      h('p', { class: 'note' }, 'Packages such as matplotlib load automatically the first time you import them. Network calls go through the site’s data proxy; the console has no access to your files or accounts.')));
}
async function runCode() {
  const out = clear(el('k-out')), btn = el('k-code-run');
  if (!S.ranStudy) {
    out.append(h('div', { class: 'callout warn' }, 'No study has been run yet, so `raw` and `frame` are empty. Run the study first (Results tab), or use the “Synthetic” source for a quick start.'));
  }
  btn.disabled = true;
  out.append(h('div', {}, h('span', { class: 'spinner' }), 'Running…'));
  try {
    const r = await engine.call('run_code', { code: el('k-code').value });
    clear(out);
    if (r.stdout) out.append(h('pre', {}, r.stdout));
    if (r.error) out.append(h('pre', { class: 'err' }, r.error));
    r.images.forEach((b64) => out.append(h('img', { class: 'fig', src: `data:image/png;base64,${b64}`, alt: 'matplotlib figure' })));
    if (!r.stdout && !r.error && !r.images.length) out.append(h('span', { class: 'note' }, 'Ran with no output (use print(...) to show values).'));
  } catch (e) { clear(out).append(h('pre', { class: 'err' }, e.message)); } finally { btn.disabled = false; }
}

// ------------------------------------------------------------------ notes
function buildNotes() {
  clear(el('k-notes')).append(h('div', { class: 'method', html: NOTES }));
}
function typeset(root, tries = 0) {
  if (window.renderMathInElement) window.renderMathInElement(root, { delimiters: [{ left: '$$', right: '$$', display: true }, { left: '$', right: '$', display: false }], throwOnError: false });
  else if (tries < 40) setTimeout(() => typeset(root, tries + 1), 150);
}

const NOTES = `
<h2>The hypothesis</h2>
<p>Kalshi's 15-minute crypto contracts ask “will the price be at or above where it started in 15 minutes?”. If retail traders are systematically optimistic, “Yes” would trade above its true probability, and buying “No” on every contract would be profitable even after fees. The lab tests three things: <b>overpricing</b> (calibration), <b>asymmetry</b> (is the bias stronger on upside strikes?) and a <b>strategy</b> (simply buy No).</p>

<h2>What the data is</h2>
<ul>
<li><b>Contracts:</b> settled markets of a series (e.g. <code>KXBTC15M</code>) from Kalshi's public API: strike, open/close time, and the result (Yes = 1, No = 0).</li>
<li><b>Prices at checkpoints:</b> Kalshi's 1-minute quote candles. At “N minutes before expiry” we take the latest known last-trade price, and the bid and ask, at that moment (forward-filled, discarded if older than 3 minutes).</li>
<li><b>Spot:</b> Coinbase 1-minute closes, used only to decide whether a strike is above or below spot. Kalshi settles on the CF Benchmarks BRTI index, which differs from Coinbase by small amounts.</li>
<li><b>Synthetic mode:</b> a simulated market whose Yes price is the model-fair probability plus an <i>assumed</i> optimism premium. It exists to test the pipeline (a premium of 0 is a calibrated null). Nothing about its overpricing is evidence about the real market.</li>
</ul>

<h2>Calibration</h2>
<p>Contracts are grouped by Yes price into bins. In each bin the <i>implied probability</i> is the mean Yes price $\\bar P$ and the <i>realised rate</i> is the share of contracts that resolved Yes, $\\hat p$.</p>
<div class="eq">$$\\text{gap} = \\bar P - 100\\,\\hat p \\qquad(\\text{positive} \\Rightarrow \\text{Yes overpriced})$$</div>
<p>p-values test whether $\\hat p$ equals $\\bar P/100$. Three tests are offered: the <b>two-proportion z-test</b> (the form the study specifies; it treats the implied rate as a second sample of the same size, which inflates the variance and makes it conservative), an <b>exact binomial test</b>, and a <b>Poisson-binomial z-test</b> that holds each contract to its own price and is the most powerful: $z=\\dfrac{\\sum_i y_i-\\sum_i p_i}{\\sqrt{\\sum_i p_i(1-p_i)}}$. Realised-rate error bars are Wilson intervals.</p>

<h2>Upside vs downside strikes</h2>
<p>In the live KXBTC15M series the strike <i>is</i> the BTC reference price at market open, so “strike vs spot at open” is essentially noise. The default therefore compares the strike with spot at the <b>entry checkpoint</b>: an <b>upside</b> strike ($K>S$) needs further gains to resolve Yes; a <b>downside</b> strike ($K<S$) is currently in the money. Because upside strikes are nearly always cheap Yes contracts and downside ones expensive, the raw comparison is confounded with the favourite–longshot bias; the <b>price-matched</b> comparison keeps only contracts priced 40–60¢. Per contract the overpricing residual is $r_i = P_i/100 - y_i$ and the groups' mean residuals are compared with Welch's t-test.</p>

<h2>The Buy-No backtest</h2>
<p>Entry: buy one No at $100 - P_{\\text{yes}}$ cents at the checkpoint (or, with “executable” pricing, at its ask $100-\\text{bid}_{\\text{yes}}$, which includes the spread). Payout: 100¢ if the market settles No, otherwise 0. Kalshi's taker fee is charged on entry:</p>
<div class="eq">$$\\text{fee} = \\left\\lceil 0.07 \\times C \\times P(1-P) \\right\\rceil \\text{ dollars (rounded up to the next cent)},\\quad P\\in[0,1]$$</div>
<p>so one contract at 50¢ costs $\\lceil 0.07\\times0.25\\times100\\rceil = 2$¢. The fee is symmetric in $P$, hence a No bought at $100-P$ pays the same fee as the Yes at $P$. A trade profits only if the win rate exceeds the break-even rate $(\\text{entry}+\\text{fee})/100$.</p>
<ul>
<li><b>ROI</b> = net profit ÷ capital deployed (entry cost + fees). <b>Profit factor</b> = gross winning trades ÷ gross losing trades (after fees).</li>
<li><b>Max drawdown</b> = largest peak-to-trough fall of cumulative net profit. <b>Sharpe</b> uses daily profit and $\\sqrt{365}$ (the market never closes).</li>
<li>The p-value is a one-sample t-test of mean net profit per trade against 0; the interval is a day-cluster bootstrap (whole days resampled, because trades within a day are dependent).</li>
</ul>

<h2>Read this before believing a result</h2>
<ul>
<li><b>Small samples.</b> A week is about 670 contracts spread over bins and splits. A bin with 25 contracts has a ±20 pp interval; apparent overpricing there is mostly noise. Use more days.</li>
<li><b>Many tests.</b> Splits, bins and rules multiply the chances of a false positive. Do not tune the price range, checkpoint and rule until something works; that overfits.</li>
<li><b>Execution.</b> Trading at a last-trade price ignores that you would pay the ask; try “executable”. Also ignored: your own market impact and queue position.</li>
<li><b>Regime.</b> A few days of crypto data say little about other regimes. Overlapping quotes and a single path of BTC make days far from independent.</li>
<li><b>Not advice.</b> This is a research tool. It is not financial advice and not a trading system.</li>
</ul>
`;
