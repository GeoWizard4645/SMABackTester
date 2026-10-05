// Kalshi 15-minute lab: parameter form, results, and an editable in-browser Python console.

import { $, $$, h, clear, fmt, sigClass, stars, download, toCSV, seriesColor, cssVar, loadJson } from './util.js';
import * as engine from './engine.js';
import { base, merge, draw, title } from './charts.js';
import { dataTable } from './tables.js';

const STORE = 'smalab.kalshi.v1';
const ALL_CPS = [14, 12, 10, 8, 6, 5, 4, 3, 2, 1];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const FEE_PRESETS = { taker: 0.07, maker: 0.0175, half: 0.035, none: 0 };

const S = { meta: null, root: null, cps: new Set([14, 12, 10, 8, 6, 5, 4, 3, 2, 1]), days: new Set(), result: null, split: 'all', rawSplit: 'all', tab: 'results', ranStudy: false };
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
  showSnapshot();
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
    h('h3', {}, 'Fair-value benchmark (removes BTC’s trend)'),
    h('p', { class: 'help' }, 'Fair value is the chance “Yes” should have from the BTC price, the strike, the minutes left and recent volatility, with no trend assumed. The gap between the Yes price and fair value is the behavioral part.'),
    h('div', { class: 'form-grid' },
      field('Volatility window (minutes)', num('k-volwin', 10, 240, 5)),
      field('Volatility multiplier', num('k-volscale', 0.3, 3, 0.05), 'blank = fit the model automatically')),
    h('label', { class: 'cb-line' }, h('input', { id: 'k-basis', type: 'checkbox' }), ' Align Coinbase prices to Kalshi’s index (uses recent contracts only)'),
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
      field('Price noise (¢)', num('k-noise', 0, 20, 'any')), field('Random seed', num('k-seed', 0, 2147483647, 1)),
      field('BTC trend (% per day)', num('k-trend', -20, 20, 'any'), 'moves outcomes, not prices')),
  ];
}

const intro = () => h('div', { class: 'empty' },
  h('h2', {}, 'No results yet'),
  h('p', {}, 'This loads finished 15-minute contracts, checks how often “Yes” really won at each price, then tests a plain “buy No” strategy after Kalshi’s fees.'),
  h('p', { class: 'note' }, 'The first run downloads a Python engine (about 30 MB, then cached). Change any number above and run again.'));

// ------------------------------------------------------------------ saved run (auto-loaded breakdown)
async function showSnapshot() {
  let snap = null;
  try { snap = await loadJson('kalshi-snapshot', 'static/kalshi_snapshot.json'); } catch { /* none saved: show the intro */ }
  if (!snap || !snap.summary || S.result) return;
  apply({ ...S.meta.defaults, ...snap.summary.params });
  S.result = snap;
  renderResults();
  setStatus('Showing a saved run. Press Run to recompute.');
}

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
    trend: n('k-trend'), vol_window: parseInt(v('k-volwin'), 10), vol_scale: v('k-volscale') === '' ? null : n('k-volscale'), basis_adjust: el('k-basis').checked,
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
  set('k-trend', p.trend ?? 0); set('k-volwin', p.vol_window ?? 60); el('k-volscale').value = p.vol_scale == null ? '' : String(p.vol_scale); el('k-volscale').placeholder = 'auto'; el('k-basis').checked = p.basis_adjust !== false;
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
const gapTxt = (g) => (g == null ? 'n/a' : `${g >= 0 ? '+' : '−'}${Math.abs(g).toFixed(1)} pts`);
const cents = (x, d = 1) => (x == null ? 'n/a' : `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(d)}¢`);
const pTxt = (p) => (p == null ? 'n/a' : fmt.p(p) + stars(p));
const usd = (x) => (x == null ? 'n/a' : `${x < 0 ? '−' : ''}$${Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const SPLIT_NAME = { all: 'All contracts', upside: 'Strike above spot', downside: 'Strike below spot' };

function splitSwitch(key, onPick) {
  return h('div', { class: 'seg small', style: 'margin:10px 0' }, ['all', 'upside', 'downside'].map((k) =>
    h('button', { type: 'button', class: S[key] === k ? 'on' : '', onclick: () => { S[key] = k; onPick(); } }, SPLIT_NAME[k])));
}

function renderResults() {
  const r = S.result, root = clear(el('k-results')), s = r.summary;
  const live = s.source === 'live';
  const fairChart = h('div', { class: 'plot', style: 'min-height:470px' });
  const fairHost = h('div');
  const eqChart = h('div', { class: 'plot short' });
  const hrChart = h('div', { class: 'plot short' });
  const rawChart = h('div', { class: 'plot', style: 'min-height:470px' });
  const rawHost = h('div');
  const checkChart = h('div', { class: 'plot short' });

  // ---- what was run
  root.append(h('div', { class: 'block' },
    h('h2', {}, `${s.series}: ${S.meta.series[s.series]} 15-minute contracts`),
    h('p', { class: 'sub' }, h('span', { class: 'badge ' + (live ? 'live' : 'syn') }, live ? 'LIVE DATA' : 'SIMULATED DATA'),
      `${s.markets.toLocaleString()} settled contracts, ${s.priced.toLocaleString()} with a ${s.entry_checkpoint}-minute price, ${s.start} to ${s.end} UTC`),
    r.snapshot_at ? h('div', { class: 'callout' }, h('b', {}, 'Saved run. '), `This is the default setup on live data, computed ${r.snapshot_at} UTC so the page opens with results. Change any setting and press Run to recompute.`) : null,
    s.notes.length ? h('div', { class: 'callout warn' }, h('ul', { class: 'warnlist' }, s.notes.map((n) => h('li', {}, n)))) : null));

  // ---- 1. main breakdown: trend-free premium
  root.append(h('div', { class: 'block' },
    h('h2', {}, '1. Is “Yes” overpriced? (BTC’s trend removed)'),
    headlineBlock(r),
    r.fair ? [fairChart, splitSwitch('split', () => { fairHost.replaceChildren(fairTable(r.fair[S.split])); drawFair(fairChart, r); }), fairHost, h('p', { class: 'note' }, 'Each point is a group of contracts with similar fair value. Above the dotted line, Yes cost more than it was worth. Whiskers are 95% intervals that resample whole days.')] : null));

  // ---- 2. asymmetry (trend-free when possible)
  const asym = r.asymmetry_fair || r.asymmetry;
  root.append(h('div', { class: 'block' }, h('h2', {}, '2. Is the bias stronger when the strike is above spot?'),
    asymmetryBlock(asym, !!r.asymmetry_fair)));

  // ---- 3. strategies: behavior vs luck
  root.append(h('div', { class: 'block' }, h('h2', {}, '3. Would buying “No” have paid?'),
    h('p', { class: 'sub' }, 'Net profit is split into the part that comes from mispricing (what the strategy earns if the fair-value model is right) and the part that comes from luck and BTC’s trend. Only the first part says anything about trader behavior.'),
    strategyTable(r), eqChart, strategyNotes(r)));

  // ---- 4. timing
  root.append(h('div', { class: 'block' }, h('h2', {}, '4. Does it depend on the time of day?'), hrChart,
    h('p', { class: 'note' }, `Each bar pools every price level for contracts expiring in that UTC hour (${r.fair ? 'premium over fair value' : 'raw gap'}). Hours with few contracts are noisy: look for stable patterns, not single bars.`)));

  // ---- 5. raw numbers and model check, folded away
  const rawDet = h('details', { class: 'adv' }, h('summary', {}, 'Raw numbers without the trend adjustment (price vs what actually happened)'),
    h('div', { class: 'adv-body' },
      h('p', { class: 'sub' }, 'These compare the Yes price with how often Yes really won. They include BTC’s trend and plain luck, so treat them as the unadjusted version of section 1.'),
      rawChart, splitSwitch('rawSplit', () => { rawHost.replaceChildren(calTable(r.calibration[S.rawSplit])); drawCalibration(rawChart, r); }), rawHost, interpretCal(r)));
  rawDet.addEventListener('toggle', () => { if (rawDet.open) { rawHost.replaceChildren(calTable(r.calibration[S.rawSplit])); drawCalibration(rawChart, r); } });
  root.append(rawDet);
  if (r.fair) {
    const chkDet = h('details', { class: 'adv' }, h('summary', {}, 'Check the fair-value model itself'),
      h('div', { class: 'adv-body' },
        h('p', { class: 'sub' }, 'If the model is sound, contracts it prices at 30% should win about 30% of the time. Points near the line mean the benchmark is sound.'),
        checkChart,
        r.headline && r.headline.score_market != null ? h('div', { class: 'callout' }, `Prediction score (log-likelihood, higher is better): Kalshi’s own prices ${r.headline.score_market.toFixed(0)}, the fair-value model ${r.headline.score_model.toFixed(0)}. ${r.headline.score_market > r.headline.score_model ? 'The market predicted outcomes better than a model built only from the BTC price, the strike, the time left and volatility. So part of any gap between price and model can be information the market has and the model lacks, not behavior. Treat the overall average gap as more reliable than individual bins.' : 'The model predicted outcomes at least as well as the market.'}`) : null));
    chkDet.addEventListener('toggle', () => { if (chkDet.open) drawModelCheck(checkChart, r); });
    root.append(chkDet);
  }
  root.append(h('div', { class: 'toolrow', style: 'margin-top:18px' },
    h('button', { class: 'btn', type: 'button', onclick: () => download(`kalshi-${s.series}-contracts.csv`, toCSV(r.contracts)) }, 'Download contracts (CSV)'),
    h('button', { class: 'btn', type: 'button', onclick: () => download('kalshi-lab-results.json', JSON.stringify(r), 'application/json') }, 'Download results (JSON)'),
    h('button', { class: 'btn', type: 'button', onclick: () => tab('console') }, 'Open in the Python console')));

  if (r.fair) { fairHost.append(fairTable(r.fair[S.split])); drawFair(fairChart, r); }
  drawEquity(eqChart, r);
  drawHourly(hrChart, r);
}

function headlineBlock(r) {
  const h0 = r.headline;
  if (!h0) return h('div', { class: 'callout warn' }, 'The fair-value benchmark needs BTC spot prices, which are not available for this run, so only the raw numbers (at the bottom) can be shown.');
  const rows = [
    ['Average “Yes” price', `${h0.mean_price.toFixed(1)}¢`],
    ['Fair value from the model (no trend)', `${h0.mean_fair.toFixed(1)}¢`],
    ['Mispricing: price minus fair value', `${cents(h0.premium)}${h0.premium_lo == null ? '' : `  (95% range ${cents(h0.premium_lo)} to ${cents(h0.premium_hi)}, p = ${fmt.p(h0.premium_p)})`}`],
    ['How often “Yes” actually won', `${h0.yes_rate.toFixed(1)}%  (the model expected ${h0.mean_fair.toFixed(1)}%)`],
    ['How the model was set', h0.vol_scale_auto ? `volatility ×${h0.vol_scale.toFixed(2)}, tail shape ${h0.fair_shape.toFixed(2)} (fitted to the sample; the fit is symmetric, so it cannot absorb a trend)` : `volatility ×${h0.vol_scale.toFixed(2)} (set by you)`],
    ['Left over: BTC’s trend and luck', `${gapTxt(h0.luck_gap)}${h0.btc_change_pct == null ? '' : `  (BTC moved ${h0.btc_change_pct >= 0 ? '+' : '−'}${Math.abs(h0.btc_change_pct).toFixed(1)}% over the sample)`}`],
  ];
  const sig = h0.premium_p != null && h0.premium_p < 0.05;
  const withTrades = r.strategies.filter((x) => x.trades > 0);
  const fee = withTrades.length ? (100 * withTrades[0].fees) / withTrades[0].trades / (r.summary.params.contracts || 1) : null;
  const size = fee == null ? '' : ` That is ${Math.abs(h0.premium).toFixed(1)}¢ per contract against about ${fee.toFixed(1)}¢ in fees per contract, so ${h0.premium > fee ? 'it is large enough to cover the fee.' : 'it is too small to cover the fee.'}`;
  const verdict = h0.premium_p == null ? 'There are too few days of data for a reliable interval.'
    : sig ? (h0.premium > 0 ? `Yes was priced above its fair value by a statistically reliable margin, which is the direction the optimism theory predicts.${size}` : `Yes was priced BELOW fair value, the opposite of the optimism theory.${size}`)
      : `The gap between price and fair value is small enough to be chance.${size}`;
  return h('div', {},
    h('div', { class: 'tablewrap' }, h('table', { class: 'dt' }, h('tbody', {}, rows.map(([a, b]) => h('tr', {}, h('td', { class: 'l' }, a), h('td', { style: 'text-align:left;font-weight:700' }, b)))))),
    h('div', { class: 'callout' }, verdict, ' ', h('span', { class: 'note' }, 'Only the mispricing line is about behavior. The “left over” line is what BTC did beyond what its price implied, so it is kept out of the answer.')));
}

function fairTable(t) {
  const rows = [...t.rows.filter((x) => x.count), { ...t.overall, bin: 'ALL' }];
  return dataTable([
    { key: 'bin', label: 'Fair value of Yes', left: true }, { key: 'count', label: 'Contracts' },
    { key: 'avg_fair', label: 'Fair value', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(1)}¢`) },
    { key: 'avg_price', label: 'Yes price', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(1)}¢`) },
    { key: 'premium', label: 'Mispricing', fmt: (v) => cents(v) },
    { key: 'ci_lo', label: '95% range', fmt: (v, r) => (v == null ? 'n/a' : `${cents(v)} to ${cents(r.ci_hi)}`) },
    { key: 'p_value', label: 'p-value', fmt: pTxt, cls: (r) => sigClass(r.p_value) },
  ], rows, { selected: (r) => r.bin === 'ALL' });
}

function calTable(t) {
  const rows = [...t.rows, { ...t.overall, bin: 'ALL (binned range)' }];
  return dataTable([
    { key: 'bin', label: 'Price bin', left: true }, { key: 'count', label: 'Count' },
    { key: 'avg_yes', label: 'Avg Yes price', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(1)}¢`) },
    { key: 'actual_pct', label: 'Actual Yes win %', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(1)}%`) },
    { key: 'gap', label: 'Overpricing gap', fmt: gapTxt },
    { key: 'p_value', label: `p-value (${t.p_test})`, fmt: pTxt, cls: (r) => sigClass(r.p_value) },
    { key: 'ci_lo', label: '95% CI of actual', fmt: (v, r) => (v == null ? 'n/a' : `${v.toFixed(1)} to ${r.ci_hi.toFixed(1)}%`) },
  ], rows, { selected: (r) => r.bin.startsWith('ALL') });
}

function interpretCal(r) {
  const o = r.calibration.all.overall;
  if (!o.count) return h('p', { class: 'note' }, 'No contracts fall inside the binned price range.');
  return h('div', { class: 'callout' },
    `Across ${o.count.toLocaleString()} contracts priced ${o.lo} to ${o.hi}¢, the average Yes price was ${o.avg_yes.toFixed(1)}¢ and Yes won ${o.actual_pct.toFixed(1)}% of the time (gap ${gapTxt(o.gap)}, p = ${fmt.p(o.p_value)}). `,
    h('span', { class: 'note' }, 'With 20 to 40 contracts per bin the noise is ±10 points or more, so single bins can look dramatic by luck.'));
}

function asymmetryBlock(a, trendFree) {
  const row = (label, g) => h('tr', {}, h('td', { class: 'l' }, label), h('td', {}, g.n_upside), h('td', {}, g.gap_upside == null ? 'n/a' : cents(100 * g.gap_upside)),
    h('td', {}, g.n_downside), h('td', {}, g.gap_downside == null ? 'n/a' : cents(100 * g.gap_downside)),
    h('td', {}, g.diff == null ? 'n/a' : cents(100 * g.diff)), h('td', {}, g.ci_lo == null ? 'n/a' : `${cents(100 * g.ci_lo)} to ${cents(100 * g.ci_hi)}`),
    h('td', { class: sigClass(g.welch_p) }, pTxt(g.welch_p)));
  return h('div', {},
    h('p', { class: 'sub' }, `“Above spot” means BTC must still rise for Yes to win; “below spot” means it is already ahead. ${trendFree ? 'Mispricing here is the Yes price minus fair value, so BTC’s trend is out of it.' : 'Mispricing here is the Yes price minus what happened (includes trend and luck).'}`),
    h('div', { class: 'tablewrap' }, h('table', { class: 'dt' }, h('thead', {}, h('tr', {}, ['Comparison', 'n above', 'Mispricing above', 'n below', 'Mispricing below', 'Difference', '95% range', 'p-value'].map((t, i) => h('th', { class: i === 0 ? 'l' : '' }, t)))),
      h('tbody', {}, row('All prices', a), row(`Matched prices (${a.overlap[0]} to ${a.overlap[1]}¢ only)`, a.matched)))),
    h('div', { class: 'callout warn' }, h('b', {}, 'Careful: '), 'when the strike is above spot, Yes is nearly always cheap, and when it is below, Yes is expensive. So the “all prices” row mixes direction with the known favorite-longshot bias. The matched row only compares contracts priced between 40 and 60¢, where both kinds trade, and is the fairer test.'));
}

function strategyTable(r) {
  const fair = r.strategies.some((x) => x.edge_net_profit != null);
  const cols = [
    { key: 'name', label: 'Strategy', left: true }, { key: 'trades', label: 'Trades' },
    { key: 'win_rate', label: 'Win rate', fmt: (v) => (v == null ? 'n/a' : `${(100 * v).toFixed(1)}%`) },
    { key: 'net_profit', label: 'Net profit (what happened)', fmt: usd },
  ];
  if (fair) cols.push(
    { key: 'edge_net_profit', label: 'From mispricing', fmt: usd, title: 'Expected profit after fees if the fair-value model is right: the behavioral part' },
    { key: 'luck', label: 'From luck and trend', fmt: usd, title: 'Realised minus expected payout' },
    { key: 'edge_cents', label: 'Mispricing edge per contract', fmt: (v, x) => (v == null ? 'n/a' : `${cents(v)}${x.edge_ci ? ` (${cents(x.edge_ci[0])} to ${cents(x.edge_ci[1])})` : ''}`) },
    { key: 'edge_p', label: 'p-value', fmt: pTxt, cls: (x) => sigClass(x.edge_p) });
  cols.push({ key: 'roi_pct', label: 'ROI', fmt: (v) => (v == null ? 'n/a' : `${v.toFixed(2)}%`) },
    { key: 'max_drawdown', label: 'Max drawdown', fmt: usd }, { key: 'fees', label: 'Fees paid', fmt: usd });
  return dataTable(cols, r.strategies);
}
function strategyNotes(r) {
  const withEdge = r.strategies.filter((x) => x.edge_net_profit != null && x.trades >= 10);
  const items = [];
  if (withEdge.length) {
    const best = [...withEdge].sort((a, b) => b.edge_net_profit - a.edge_net_profit)[0];
    const sig = best.edge_p != null && best.edge_p < 0.05 && best.edge_net_profit > 0;
    items.push(`Largest mispricing edge: “${best.name}”, ${usd(best.edge_net_profit)} after fees on ${best.trades} trades, while the real result was ${usd(best.net_profit)} (the difference, ${usd(best.luck)}, is luck and BTC’s trend). ${sig ? 'The edge is statistically above zero, but it is one of several rules tried, so be careful.' : 'The edge is not distinguishable from zero.'}`);
  }
  items.push('A “Buy No” trade pays only if the mispricing it captures is bigger than the fee. Fees cost roughly 1 to 2¢ per contract, so a small premium is usually eaten.');
  return h('div', { class: 'callout' }, h('ul', { class: 'warnlist', style: 'margin:0' }, items.map((t) => h('li', {}, t))));
}

// ------------------------------------------------------------------ charts
const SPLIT_COLOR = () => ({ all: seriesColor(0), upside: seriesColor(1), downside: seriesColor(2) });

function drawFair(div, r) {
  const colors = SPLIT_COLOR();
  const traces = [{ x: [0, 100], y: [0, 100], mode: 'lines', name: 'Fair value', line: { color: cssVar('--ink-3'), dash: 'dot', width: 1.5 }, hoverinfo: 'skip' }];
  for (const split of ['all', 'upside', 'downside']) {
    const rows = r.fair[split].rows.filter((x) => x.count >= 5);
    if (!rows.length) continue;
    traces.push({
      x: rows.map((x) => x.avg_fair), y: rows.map((x) => x.avg_price), mode: 'lines+markers', type: 'scatter',
      name: `${SPLIT_NAME[split]} (n=${rows.reduce((a, x) => a + x.count, 0)})`, line: { color: colors[split], width: 2 }, marker: { size: 8 },
      error_y: { type: 'data', symmetric: false, array: rows.map((x) => (x.ci_hi == null ? 0 : x.ci_hi - x.premium)), arrayminus: rows.map((x) => (x.ci_lo == null ? 0 : x.premium - x.ci_lo)), color: colors[split], thickness: 1, width: 3 },
      customdata: rows.map((x) => [x.bin, x.count, x.premium, x.p_value]),
      hovertemplate: 'fair %{x:.1f}¢, Yes price %{y:.1f}¢<br>mispricing %{customdata[2]:+.1f}¢, n=%{customdata[1]}, p=%{customdata[3]:.3f}<extra>%{customdata[0]}</extra>',
    });
  }
  draw(div, traces, merge(base(), {
    height: 470, title: title('Yes price vs fair value (above the dotted line = Yes overpriced)'),
    xaxis: { title: { text: 'Fair value of Yes from the model (¢)' }, range: [0, 100] },
    yaxis: { title: { text: 'What Yes actually cost (¢)' }, range: [0, 100] }, legend: { orientation: 'h', y: -0.18 },
  }));
}
function drawModelCheck(div, r) {
  const rows = r.fair.all.rows.filter((x) => x.count >= 5);
  draw(div, [
    { x: [0, 100], y: [0, 100], mode: 'lines', name: 'Perfect', line: { color: cssVar('--ink-3'), dash: 'dot' }, hoverinfo: 'skip' },
    { x: rows.map((x) => x.avg_fair), y: rows.map((x) => x.realized_pct), mode: 'lines+markers', name: 'How often Yes really won', line: { color: seriesColor(0) }, marker: { size: 8 },
      error_y: { type: 'data', symmetric: false, array: rows.map((x) => x.real_hi - x.realized_pct), arrayminus: rows.map((x) => x.realized_pct - x.real_lo), color: seriesColor(0), thickness: 1, width: 3 },
      customdata: rows.map((x) => x.count), hovertemplate: 'model %{x:.1f}%, actual %{y:.1f}%, n=%{customdata}<extra></extra>' },
  ], merge(base(), { height: 300, title: title('Model probability vs how often Yes actually won'), xaxis: { title: { text: 'Model probability (%)' }, range: [0, 100] }, yaxis: { title: { text: 'Actual Yes rate (%)' }, range: [0, 100] }, legend: { orientation: 'h', y: -0.3 } }));
}
function drawCalibration(div, r) {
  const colors = SPLIT_COLOR();
  const traces = [{ x: [0, 100], y: [0, 100], mode: 'lines', name: 'Fair value (45° line)', line: { color: cssVar('--ink-3'), dash: 'dot', width: 1.5 }, hoverinfo: 'skip' }];
  for (const split of ['all', 'upside', 'downside']) {
    const rows = r.calibration[split].rows.filter((x) => x.count);
    if (!rows.length) continue;
    traces.push({
      x: rows.map((x) => x.avg_yes), y: rows.map((x) => x.actual_pct), mode: 'lines+markers', type: 'scatter',
      name: `${SPLIT_NAME[split]} (n=${rows.reduce((a, x) => a + x.count, 0)})`, line: { color: colors[split], width: 2 }, marker: { size: 8 },
      error_y: { type: 'data', symmetric: false, array: rows.map((x) => x.ci_hi - x.actual_pct), arrayminus: rows.map((x) => x.actual_pct - x.ci_lo), color: colors[split], thickness: 1, width: 3 },
      customdata: rows.map((x) => [x.bin, x.count, x.gap, x.p_value]),
      hovertemplate: '%{customdata[0]}<br>avg Yes %{x:.1f}¢ won %{y:.1f}%<br>n=%{customdata[1]}, gap %{customdata[2]:+.1f} pts<extra></extra>',
    });
  }
  draw(div, traces, merge(base(), {
    height: 470, title: title('Yes price vs actual win rate (includes BTC’s trend and luck)'),
    xaxis: { title: { text: 'Average Yes price (¢)' }, range: [0, 100] }, yaxis: { title: { text: 'Actual Yes win rate (%)' }, range: [0, 100] }, legend: { orientation: 'h', y: -0.18 },
  }));
}
function drawEquity(div, r) {
  const names = Object.keys(r.equity);
  const traces = [];
  names.forEach((n, i) => {
    const c = seriesColor(i), e = r.equity[n];
    traces.push({ x: e.t, y: e.cum, mode: 'lines', type: 'scatter', name: `${n} (what happened)`, legendgroup: n, line: { color: c, width: 2 }, hovertemplate: '%{x}<br>net $%{y:.2f}<extra></extra>' });
    if (e.cum_edge && e.cum_edge.some((v) => v != null)) traces.push({ x: e.t, y: e.cum_edge, mode: 'lines', type: 'scatter', name: `${n} (mispricing only)`, legendgroup: n, line: { color: c, width: 2, dash: 'dot' }, hovertemplate: '%{x}<br>expected from mispricing $%{y:.2f}<extra></extra>' });
  });
  if (!traces.length) { div.innerHTML = '<p class="note" style="padding:20px">No strategies selected.</p>'; return; }
  draw(div, traces, merge(base(), { height: 360, title: title('Cumulative profit after fees: solid = what happened, dotted = the mispricing part'), yaxis: { title: { text: 'Cumulative profit ($)' }, tickprefix: '$' }, legend: { orientation: 'h', y: -0.3 },
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: cssVar('--ink-3'), width: 1 } }] }));
}
function drawHourly(div, r) {
  const rows = r.hourly, key = rows.some((x) => x.premium != null) ? 'premium' : 'gap';
  const unit = key === 'premium' ? 'Mispricing over fair value (¢)' : 'Raw gap (points)';
  draw(div, [{ type: 'bar', x: rows.map((x) => x.hour), y: rows.map((x) => x[key]), marker: { color: seriesColor(0) },
    customdata: rows.map((x) => [x.count, x.avg_yes]), hovertemplate: 'hour %{x}:00 UTC<br>%{y:+.1f}<br>n=%{customdata[0]}, avg Yes %{customdata[1]:.1f}¢<extra></extra>' }],
  merge(base(), { height: 320, title: title(`${unit} by UTC hour of expiry`), xaxis: { title: { text: 'Hour (UTC)' }, dtick: 1 }, yaxis: { title: { text: unit } }, showlegend: false,
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

<h2>Removing BTC's trend: the fair-value benchmark</h2>
<p>If you simply compare the Yes price with how often Yes won, three things get mixed together: <b>mispricing</b> (the behavioral part), <b>BTC's drift</b> during your sample, and <b>luck</b>. A week in which BTC happened to rise makes Yes look cheap; a week in which it fell makes it look expensive. To isolate behavior, the lab compares the Yes price with a <i>fair value</i> built only from what was known at the moment of the price: the BTC price $S$, the strike $K$, the minutes left $m$ and the recent per-minute volatility $v$ (measured from the previous hour of 1-minute Coinbase data), with <b>no drift</b>:</p>
<div class="eq">$$\\text{fair}=\\Phi\\!\\left(\\frac{\\ln(S/K)}{v\\sqrt{m-\\tfrac23}}\\right)$$</div>
<p>The $\\tfrac23$ accounts for settlement using the average of the last 60 seconds of the index. Nothing in this formula looks at what BTC did afterwards, so it contains neither trend nor luck. The <b>mispricing</b> of a contract is then $P_{\\text{yes}}-100\\cdot\\text{fair}$ (in cents). It is also far less noisy than comparing with a 0/1 outcome.</p>
<p>Profit is split the same way. If fair value were the truth, buying a No at cost $c$ would earn an expected $100(1-\\text{fair})-c$ before fees: that is the <b>edge from mispricing</b>. The rest, realised payout minus expected payout, is <b>luck and trend</b>. The two add up to the actual net profit, trade by trade.</p>
<p>On simulated data this works as intended: with no planted bias the mispricing is about 0; with a 4¢ bias it is detected; and with BTC trending +8% per day the raw gap swings to −4¢ (wrongly saying Yes is cheap) while the mispricing stays near 0. The benchmark rests on a model, so the page includes a check of the model against realised outcomes. Its two settings (a volatility multiplier and a tail-shape exponent) are fitted to the sample by maximum likelihood; the family is symmetric around the strike, so the fit can stretch or flatten the probabilities but can never tilt them up or down, which means it cannot absorb a trend. Kalshi's prices usually score better than any model built from these inputs alone, because the market also sees order flow and other venues. That is why the overall average gap is more trustworthy than the gap in any single bin.</p>

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
