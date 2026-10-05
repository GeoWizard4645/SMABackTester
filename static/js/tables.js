// Table rendering, CSV export and the plain-language verdict logic.

import { h, fmt, sigClass, stars, toCSV, download, seriesColor } from './util.js';

/**
 * columns: [{key, label, fmt?, cls?(row)=>string, left?, sortable?}]
 * opts: {csv: 'file.csv', groupKey, onRowClick, selected, sort:{key,dir}, onSort}
 */
export function dataTable(columns, rows, opts = {}) {
  const head = h('tr', {}, columns.map((c) => h('th', {
    class: [c.left ? 'l' : '', opts.onSort && c.sortable ? 'sortable' : ''].join(' ').trim(),
    onclick: opts.onSort && c.sortable ? () => opts.onSort(c.key) : null,
    title: c.title || null,
  }, c.label + (opts.sort && opts.sort.key === c.key ? (opts.sort.dir > 0 ? ' ▲' : ' ▼') : ''))));
  let prev = null;
  const body = rows.map((r, idx) => {
    const g = opts.groupKey ? r[opts.groupKey] : null;
    const cls = [];
    if (opts.groupKey && prev !== null && g !== prev) cls.push('group-top');
    if (opts.onRowClick) cls.push('clickable');
    if (opts.selected && opts.selected(r)) cls.push('sel');
    prev = g;
    return h('tr', { class: cls.join(' '), onclick: opts.onRowClick ? () => opts.onRowClick(r, idx) : null },
      columns.map((c) => {
        const raw = r[c.key];
        const txt = c.fmt ? c.fmt(raw, r) : raw == null ? 'n/a' : raw;
        return h('td', { class: [c.left ? 'l' : '', c.cls ? c.cls(r) : ''].join(' ').trim() }, txt);
      }));
  });
  const table = h('table', { class: 'dt' }, h('thead', {}, head), h('tbody', {}, body));
  return h('div', { class: 'tablewrap' }, table);
}

export function tableBlock(titleText, columns, rows, opts = {}) {
  const head = h('div', { class: 'tbl-head' }, h('h3', {}, titleText),
    opts.csv ? h('button', { class: 'btn tiny', type: 'button', onclick: () => download(opts.csv, toCSV(rows, columns.map((c) => c.key))) }, 'Download CSV') : null);
  return h('div', {}, head, opts.note ? h('p', { class: 'note' }, opts.note) : null, dataTable(columns, rows, opts));
}

export const pCell = (key) => ({ key, label: key === 'boot_p' ? 'Boot p' : key, fmt: (v) => fmt.p(v) + stars(v), cls: (r) => sigClass(r[key]) });

// ------------------------------------------------------------------ verdicts
/** Classify the full-sample gap between the target and one control. */
export function verdict(res, control, horizon) {
  const comp = res.comparisons[control];
  if (!comp) return null;
  const get = (metric, era = 'All') => comp.find((r) => r.era === era && r.metric === metric && r.horizon === horizon);
  const b = get('bounce'), c = get('car');
  const e = (res.expansion[control] || []).find((r) => r.metric === 'car' && r.horizon === horizon);
  const eb = (res.expansion[control] || []).find((r) => r.metric === 'bounce' && r.horizon === horizon);
  const pos = (r) => r && r.boot_p != null && r.boot_p < 0.05 && r.diff > 0;
  const neg = (r) => r && r.boot_p != null && r.boot_p < 0.05 && r.diff < 0;
  const none = (r) => !r || r.boot_p == null;
  let kind = 'null', headline = 'No statistically distinguishable difference';
  if (none(b) && none(c)) { kind = 'na'; headline = 'Not enough data for inference'; }
  else if ((pos(b) || pos(c)) && !(neg(b) || neg(c))) { kind = 'pos'; headline = 'Target reacts more than the control (nominal p < 0.05)'; }
  else if ((neg(b) || neg(c)) && !(pos(b) || pos(c))) { kind = 'neg'; headline = 'Target reacts LESS than the control — opposite of the hypothesis'; }
  else if ((pos(b) || pos(c)) && (neg(b) || neg(c))) { kind = 'mixed'; headline = 'Mixed signals: one metric favours the target, the other the control'; }
  const grew = (r) => r && r.boot_p != null && r.boot_p < 0.05 && r.did > 0;
  const shrank = (r) => r && r.boot_p != null && r.boot_p < 0.05 && r.did < 0;
  let era = 'No clear change in the target-vs-control gap between the early and late era.';
  if (grew(e) || grew(eb)) era = `The gap grew from ${res.base_era} to ${res.late_era} (nominal p < 0.05).`;
  else if (shrank(e) || shrank(eb)) era = `The gap shrank from ${res.base_era} to ${res.late_era} (nominal p < 0.05).`;
  else if (!e || e.boot_p == null) era = `Era comparison unavailable (too few events or fewer than 5 years in ${res.base_era} / ${res.late_era}).`;
  return { kind, headline, era, b, c, e, eb };
}

export function gapPills(v, horizon) {
  if (!v) return null;
  const pill = (label, val, p) => h('span', { class: 'pill ' + sigClass(p), title: p == null ? 'no bootstrap inference' : `bootstrap p = ${fmt.p(p)}` }, `${label} ${val}${p == null ? '' : ' (p ' + fmt.p(p) + stars(p) + ')'}`);
  return [
    pill(`bounce gap ${horizon}b`, fmt.pp(v.b && v.b.diff), v.b && v.b.boot_p),
    pill(`CAR gap ${horizon}b`, fmt.spct(v.c && v.c.diff), v.c && v.c.boot_p),
    v.e ? pill('era-change CAR', fmt.spct(v.e.did), v.e.boot_p) : null,
  ];
}

/** Scoreboard: assets × controls. */
export function scoreboard(results, horizon) {
  const controls = [...new Set(results.flatMap((r) => r.mas.slice(1)))];
  const head = h('tr', {}, h('th', { class: 'l' }, 'Asset'), controls.map((c) => h('th', {}, `vs ${c}`)));
  const rows = results.map((res) => h('tr', {}, h('td', { class: 'l' }, res.label), controls.map((c) => {
    const v = verdict(res, String(c), horizon);
    if (!v) return h('td', {}, '–');
    const worst = Math.min(v.b && v.b.boot_p != null ? v.b.boot_p : 1, v.c && v.c.boot_p != null ? v.c.boot_p : 1);
    return h('td', { class: sigClass(worst) }, h('span', { class: 'cell2' },
      `CAR ${fmt.spct(v.c && v.c.diff)}`, h('small', {}, `bounce ${fmt.pp(v.b && v.b.diff)}`)));
  })));
  return h('div', { class: 'tablewrap' }, h('table', { class: 'dt score' }, h('thead', {}, head), h('tbody', {}, rows)));
}

export const seriesDot = (i) => h('span', { class: 'dot', style: `display:inline-block;width:9px;height:9px;border-radius:50%;background:${seriesColor(i)};margin-right:6px` });
