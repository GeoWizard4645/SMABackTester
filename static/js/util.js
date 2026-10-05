// Small shared helpers: DOM, formatting, colours, API, CSV.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Hyperscript: h('div', {class:'x', onclick: fn}, 'text', childNode, ...) */
export function h(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export const clear = (node) => { node.replaceChildren(); return node; };

// ------------------------------------------------------------------ formatting
const nz = (x) => x === null || x === undefined || Number.isNaN(x);
export const fmt = {
  pct: (x, d = 1) => (nz(x) ? 'n/a' : (100 * x).toFixed(d) + '%'),
  spct: (x, d = 2) => (nz(x) ? 'n/a' : (x >= 0 ? '+' : '') + (100 * x).toFixed(d) + '%'),
  pp: (x, d = 1) => (nz(x) ? 'n/a' : (x >= 0 ? '+' : '') + (100 * x).toFixed(d) + ' pp'),
  p: (x) => (nz(x) ? 'n/a' : x < 0.0001 ? '<0.0001' : x.toFixed(4)),
  num: (x, d = 2) => (nz(x) ? 'n/a' : Number(x).toFixed(d)),
  int: (x) => (nz(x) ? 'n/a' : Number(x).toLocaleString()),
  money: (x) => (nz(x) ? 'n/a' : Number(x).toLocaleString(undefined, { maximumFractionDigits: 2 })),
};
export const sigClass = (p) => (nz(p) ? '' : p < 0.01 ? 'sig2' : p < 0.05 ? 'sig1' : '');
export const stars = (p) => (nz(p) ? '' : p < 0.01 ? '**' : p < 0.05 ? '*' : '');

// ------------------------------------------------------------------ colours
// Categorical slots in fixed order (validated adjacent-pair palette); target = slot 1.
const SERIES = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948', '#7a7974'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767', '#a8a79d'],
};
export function isDark() { return false; }
export const seriesColor = (i) => SERIES[isDark() ? 'dark' : 'light'][i % 9];
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export function rgba(hex, a) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// ------------------------------------------------------------------ assets (inlined in the single-file build)
/** Text of an inlined <script>/<template> with this id, else fetched from `url`. */
export async function loadText(id, url) {
  const el = document.getElementById(id);
  if (el) return el.tagName === 'TEMPLATE' ? el.innerHTML : el.textContent;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`could not load ${url} (${res.status})`);
  return res.text();
}
export const loadJson = async (id, url) => JSON.parse(await loadText(id, url));

// ------------------------------------------------------------------ network
export async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let json = null;
  try { json = await res.json(); } catch { /* non-JSON error */ }
  if (!res.ok) throw new Error((json && json.error) || `Request failed (${res.status})`);
  return json;
}

// ------------------------------------------------------------------ files
export function toCSV(rows, cols) {
  const esc = (v) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const keys = cols || (rows[0] ? Object.keys(rows[0]) : []);
  return [keys.join(','), ...rows.map((r) => keys.map((k) => esc(r[k])).join(','))].join('\n');
}
export function download(name, text, mime = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = h('a', { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ------------------------------------------------------------------ stats helpers (scan tab)
export function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}
