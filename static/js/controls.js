// Sidebar: builds the settings UI, and converts it to / from a config object.

import { $, $$, h, clear, seriesColor } from './util.js';

const S = { tickers: [], controls: [], ends: [], horizons: new Set(), meta: null };
const HORIZON_PRESETS = [1, 2, 3, 5, 10, 20, 30];
const MAX_TICKERS = 8, MAX_CONTROLS = 8;
const TICKER_RE = /^[A-Za-z0-9^.=\-]{1,20}$/;
let changeHandler = () => {};

const ERA_MODE_HELP = {
  smart: 'Splits the history into 1950–1990, 1991–2007 and 2008 onward (or into equal thirds for assets that are newer than 1980, like Bitcoin).',
  custom: 'You pick the last year of each period, for example one per decade. A period an asset has no data for shows n/a.',
  equal: 'Cuts each asset’s history into equal-length periods.',
};

export function initControls(meta, onChange) {
  S.meta = meta;
  changeHandler = onChange || (() => {});
  buildPresets();
  wireAssets();
  wireLines();
  wireEras();
  wireHorizons();
  applyConfig(meta.defaults);
}

// ------------------------------------------------------------------ assets
function normTicker(t) {
  t = t.trim();
  if (t.toLowerCase() === 'synthetic') return 'SYNTHETIC';
  return t.startsWith('^') || /[=\-.]/.test(t) || t === t.toUpperCase() ? t.toUpperCase() : t.toUpperCase();
}
export function addTicker(raw) {
  for (const part of raw.split(/[\s,;]+/).filter(Boolean)) {
    const t = normTicker(part);
    if (!TICKER_RE.test(t)) { toast(`“${part}” is not a valid symbol`); continue; }
    if (S.tickers.includes(t)) continue;
    if (S.tickers.length >= MAX_TICKERS) { toast(`At most ${MAX_TICKERS} assets per run`); break; }
    S.tickers.push(t);
  }
  renderTickers();
}
function removeTicker(t) { S.tickers = S.tickers.filter((x) => x !== t); renderTickers(); }
function renderTickers() {
  const box = clear($('#ticker-chips'));
  S.tickers.forEach((t) => box.append(h('span', { class: 'chip' }, label(t),
    h('button', { type: 'button', 'aria-label': `Remove ${t}`, onclick: () => removeTicker(t) }, '×'))));
  $$('.pbtn').forEach((b) => b.classList.toggle('on', S.tickers.includes(b.dataset.t)));
}
const label = (t) => (t === 'SYNTHETIC' ? 'Synthetic (null)' : t);

function buildPresets() {
  const root = clear($('#preset-groups'));
  for (const g of S.meta.presets) {
    root.append(h('div', { class: 'pgroup' }, h('h4', {}, g.group),
      h('div', { class: 'pbtns' }, g.items.map((it) => h('button', {
        class: 'pbtn', type: 'button', title: it.n, dataset: { t: it.t },
        onclick: () => (S.tickers.includes(it.t) ? removeTicker(it.t) : addTicker(it.t)),
      }, it.t === 'SYNTHETIC' ? 'Synthetic null' : `${it.t}, ${it.n.split(' ').slice(0, 2).join(' ')}`)))));
  }
}

function wireAssets() {
  const input = $('#ticker-input');
  const add = () => { addTicker(input.value); input.value = ''; };
  $('#ticker-add').addEventListener('click', add);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  $$('[data-range]').forEach((b) => b.addEventListener('click', () => {
    const r = b.dataset.range, today = new Date();
    $('#end').value = '';
    if (r === 'max') $('#start').value = '1950-01-01';
    else if (r === '10y') { today.setFullYear(today.getFullYear() - 10); $('#start').value = today.toISOString().slice(0, 10); }
    else $('#start').value = `${r}-01-01`;
    refreshEraUI();
  }));
  ['start', 'end'].forEach((id) => $('#' + id).addEventListener('change', refreshEraUI));
}

// ------------------------------------------------------------------ lines
function addControl(w) {
  w = parseInt(w, 10);
  if (!Number.isFinite(w) || w < 2 || w > 1000) { toast('Enter a window between 2 and 1000'); return; }
  if (w === parseInt($('#target').value, 10)) { toast('That is the target line'); return; }
  if (S.controls.includes(w)) return;
  if (S.controls.length >= MAX_CONTROLS) { toast(`At most ${MAX_CONTROLS} control lines`); return; }
  S.controls.push(w);
  renderControls();
}
function renderControls() {
  const box = clear($('#control-chips'));
  S.controls.forEach((w, i) => box.append(h('span', { class: 'chip' },
    h('span', { class: 'dot', style: `background:${seriesColor(i + 1)}` }), `${w}`,
    h('button', { type: 'button', 'aria-label': `Remove ${w}`, onclick: () => { S.controls = S.controls.filter((x) => x !== w); renderControls(); } }, '×'))));
}
function wireLines() {
  const input = $('#control-input');
  const add = () => { addControl(input.value); input.value = ''; };
  $('#control-add').addEventListener('click', add);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  $$('[data-control]').forEach((b) => b.addEventListener('click', () => addControl(b.dataset.control)));
  $('#control-clear').addEventListener('click', () => { S.controls = []; renderControls(); });
  $('#control-random').addEventListener('click', () => {
    const target = parseInt($('#target').value, 10) || 200;
    for (let i = 0; i < 80; i++) {
      const w = 50 + Math.floor(Math.random() * 351);
      if (Math.abs(w - target) <= 10 || S.controls.some((c) => Math.abs(c - w) <= 3)) continue;
      addControl(w);
      return;
    }
  });
  $('#target').addEventListener('change', () => { S.controls = S.controls.filter((c) => c !== parseInt($('#target').value, 10)); renderControls(); });
}

// ------------------------------------------------------------------ eras
const eraMode = () => $('input[name=era-mode]:checked').value;
function eraCount() {
  const m = eraMode();
  if (m === 'custom') return S.ends.length + 1;
  if (m === 'equal') return Math.max(2, Math.min(8, parseInt($('#era-n').value, 10) || 3));
  return 3;
}
function renderEnds() {
  const box = clear($('#era-ends'));
  S.ends.forEach((y, i) => box.append(h('span', { class: 'era-end' },
    h('input', { type: 'number', min: 1900, max: 2200, value: y, 'aria-label': `Era ${i + 1} last year`,
      onchange: (e) => { S.ends[i] = parseInt(e.target.value, 10) || y; S.ends = [...new Set(S.ends)].sort((a, b) => a - b); renderEnds(); refreshEraUI(); } }),
    h('button', { type: 'button', 'aria-label': 'Remove boundary', onclick: () => { S.ends.splice(i, 1); renderEnds(); refreshEraUI(); } }, '×'))));
}
function populateEraSelects() {
  const n = eraCount();
  const base = $('#base-era'), late = $('#late-era');
  const keepB = base.value, keepL = late.value;
  clear(base); clear(late);
  for (let i = 1; i <= n; i++) {
    base.append(h('option', { value: i === 1 ? '' : String(i) }, i === 1 ? 'Era 1 (first)' : `Era ${i}`));
    late.append(h('option', { value: i === n ? '' : String(i) }, i === n ? `Era ${n} (last)` : `Era ${i}`));
  }
  if ([...base.options].some((o) => o.value === keepB)) base.value = keepB;
  if ([...late.options].some((o) => o.value === keepL)) late.value = keepL;
}
function renderTimeline() {
  const box = clear($('#era-timeline'));
  const m = eraMode();
  const startYear = parseInt(($('#start').value || '1950').slice(0, 4), 10);
  const endYear = $('#end').value ? parseInt($('#end').value.slice(0, 4), 10) : new Date().getFullYear();
  let ends;
  if (m === 'smart') ends = [1990, 2007];
  else if (m === 'custom') ends = S.ends;
  else { const n = eraCount(); ends = Array.from({ length: n - 1 }, (_, i) => Math.floor(startYear + ((endYear - startYear) * (i + 1)) / n)); }
  const bounds = [startYear - 1, ...ends.map((e) => Math.max(startYear - 1, Math.min(endYear, e))), endYear];
  const total = Math.max(1, endYear - startYear + 1);
  for (let i = 0; i < bounds.length - 1; i++) {
    const w = Math.max(0, bounds[i + 1] - bounds[i]);
    box.append(h('div', { class: 'seg-era', style: `flex:${Math.max(w, 0.0001)} 1 0`, title: `Era ${i + 1}: ${bounds[i] + 1}–${bounds[i + 1]}` }, w / total > 0.07 ? `Era ${i + 1}` : ''));
  }
}
function refreshEraUI() {
  const m = eraMode();
  $('#era-custom').hidden = m !== 'custom';
  $('#era-equal').hidden = m !== 'equal';
  $('#era-mode-help').textContent = ERA_MODE_HELP[m];
  populateEraSelects();
  renderTimeline();
}
function wireEras() {
  $$('input[name=era-mode]').forEach((r) => r.addEventListener('change', () => { if (eraMode() === 'custom' && !S.ends.length) { S.ends = [1990, 2007]; renderEnds(); } refreshEraUI(); }));
  $('#era-add').addEventListener('click', () => {
    const last = S.ends.length ? S.ends[S.ends.length - 1] : 1999;
    if (S.ends.length >= 7) { toast('At most 8 eras'); return; }
    S.ends.push(Math.min(2200, last + 5));
    renderEnds(); refreshEraUI();
  });
  $$('.era-preset').forEach((b) => b.addEventListener('click', () => { S.ends = b.dataset.ends.split(',').map(Number); renderEnds(); refreshEraUI(); }));
  $('#era-n').addEventListener('change', refreshEraUI);
}

// ------------------------------------------------------------------ horizons
function renderHorizons() {
  const box = clear($('#horizon-chips'));
  const all = [...new Set([...HORIZON_PRESETS, ...S.horizons])].sort((a, b) => a - b);
  all.forEach((k) => box.append(h('span', {
    class: 'tchip' + (S.horizons.has(k) ? ' on' : ''), role: 'button', tabindex: 0, 'aria-pressed': S.horizons.has(k),
    onclick: () => toggleHorizon(k),
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleHorizon(k); } },
  }, `${k}d`)));
}
function toggleHorizon(k) {
  if (S.horizons.has(k)) { if (S.horizons.size > 1) S.horizons.delete(k); else toast('Keep at least one horizon'); }
  else if (S.horizons.size >= 8) toast('At most 8 horizons');
  else S.horizons.add(k);
  renderHorizons();
}
function wireHorizons() {
  $('#horizon-add').addEventListener('click', () => {
    const k = parseInt($('#horizon-custom').value, 10);
    if (!Number.isFinite(k) || k < 1 || k > 60) { toast('Horizon must be 1–60'); return; }
    if (S.horizons.size < 8) S.horizons.add(k); else toast('At most 8 horizons');
    $('#horizon-custom').value = '';
    renderHorizons();
  });
}

// ------------------------------------------------------------------ config <-> UI
const num = (id, d) => { const v = parseFloat($('#' + id).value); return Number.isFinite(v) ? v : d; };

export function collectConfig() {
  const mode = eraMode();
  return {
    tickers: [...S.tickers],
    start: $('#start').value || '1950-01-01',
    end: $('#end').value || null,
    target: parseInt($('#target').value, 10) || 200,
    controls: [...S.controls],
    ma_type: $('#ma-type').value,
    eras: { mode, ends: [...S.ends], n: eraCount() },
    base_era: $('#base-era').value ? parseInt($('#base-era').value, 10) : null,
    late_era: $('#late-era').value ? parseInt($('#late-era').value, 10) : null,
    band: num('band', 0.5), breach: num('breach', 1.5),
    approach: parseInt($('#approach').value, 10) || 5,
    refractory: Number.isFinite(parseInt($('#refractory').value, 10)) ? parseInt($('#refractory').value, 10) : 10,
    atr_window: parseInt($('#atr-window').value, 10) || 14,
    pre: parseInt($('#pre').value, 10) || 5, post: parseInt($('#post').value, 10) || 10,
    horizons: [...S.horizons].sort((a, b) => a - b),
    breach_basis: $('#breach-basis').value,
    direction: $('#direction').value,
    bootstrap: parseInt($('#bootstrap').value, 10) || 2000,
    seed: parseInt($('#seed').value, 10) || 0,
  };
}

export function applyConfig(c) {
  S.tickers = [...(c.tickers || [])];
  S.controls = [...(c.controls || [])];
  S.ends = [...((c.eras && c.eras.ends) || [1990, 2007])];
  S.horizons = new Set(c.horizons || [1, 3, 5, 10]);
  $('#start').value = c.start || '1950-01-01';
  $('#end').value = c.end || '';
  $('#target').value = c.target ?? 200;
  $('#ma-type').value = c.ma_type || 'sma';
  const eras = c.eras || { mode: 'smart', n: 3 };
  $(`input[name=era-mode][value=${eras.mode || 'smart'}]`).checked = true;
  $('#era-n').value = eras.n || 3;
  $('#band').value = c.band ?? 0.5; $('#breach').value = c.breach ?? 1.5;
  $('#approach').value = c.approach ?? 5; $('#refractory').value = c.refractory ?? 10;
  $('#atr-window').value = c.atr_window ?? 14; $('#pre').value = c.pre ?? 5; $('#post').value = c.post ?? 10;
  $('#breach-basis').value = c.breach_basis || 'close';
  $('#direction').value = c.direction || 'both';
  $('#bootstrap').value = String(c.bootstrap ?? 2000);
  if (![...$('#bootstrap').options].some((o) => o.value === $('#bootstrap').value)) $('#bootstrap').append(h('option', { value: $('#bootstrap').value }, $('#bootstrap').value));
  $('#bootstrap').value = String(c.bootstrap ?? 2000);
  $('#seed').value = c.seed ?? 42;
  renderTickers(); renderControls(); renderEnds(); renderHorizons();
  refreshEraUI();
  $('#base-era').value = c.base_era ? String(c.base_era) : '';
  $('#late-era').value = c.late_era ? String(c.late_era) : '';
}

// ------------------------------------------------------------------ status / toast
export function setStatus(msg, kind = '') {
  const el = $('#status');
  el.className = 'status ' + kind;
  clear(el);
  if (kind === 'busy') el.append(h('span', { class: 'spinner' }));
  el.append(msg);
}
let toastTimer;
export function toast(msg) {
  const el = $('#status');
  el.className = 'status err';
  el.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { if (el.textContent === msg) { el.textContent = ''; el.className = 'status'; } }, 4000);
}
