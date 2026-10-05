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
  let kind = 'null', headline = 'No real difference between the two lines';
  if (none(b) && none(c)) { kind = 'na'; headline = 'Not enough data to tell'; }
  else if ((pos(b) || pos(c)) && !(neg(b) || neg(c))) { kind = 'pos'; headline = 'The line you are testing reacts more than the comparison line'; }
  else if ((neg(b) || neg(c)) && !(pos(b) || pos(c))) { kind = 'neg'; headline = 'The line you are testing reacts LESS than the comparison line (the opposite of the theory)'; }
  else if ((pos(b) || pos(c)) && (neg(b) || neg(c))) { kind = 'mixed'; headline = 'Mixed: one measure favours the tested line, the other the comparison line'; }
  const grew = (r) => r && r.boot_p != null && r.boot_p < 0.05 && r.did > 0;
  const shrank = (r) => r && r.boot_p != null && r.boot_p < 0.05 && r.did < 0;
  let era = 'The difference between the two lines did not change clearly from the early period to the late one.';
  if (grew(e) || grew(eb)) era = `The difference between the lines grew from ${res.base_era} to ${res.late_era}.`;
  else if (shrank(e) || shrank(eb)) era = `The difference between the lines shrank from ${res.base_era} to ${res.late_era}.`;
  else if (!e || e.boot_p == null) era = `Early-vs-late comparison unavailable (too few touches, or fewer than 5 years in ${res.base_era} / ${res.late_era}).`;
  return { kind, headline, era, b, c, e, eb };
}

/** Plain-English evidence lines for one target-vs-control verdict. */
export function plainLines(v, horizon, res, control) {
  if (!v) return null;
  const t = `${res.mas[0]}-day`, c = `${control}-day`;
  const pTxt = (p) => (p == null ? 'not enough data for a test' : `p = ${fmt.p(p)}${p < 0.05 ? ', unlikely to be luck' : ''}`);
  const line = (text, p) => h('div', { class: 'evline' }, text, ' ', h('span', { class: 'ptag ' + sigClass(p) }, pTxt(p)));
  const out = [];
  if (v.b) out.push(line(`After touching the line, price bounced away ${fmt.pct(v.b.mean_target, 0)} of the time for the ${t} line vs ${fmt.pct(v.b.mean_control, 0)} for the ${c} line (difference ${fmt.pp(v.b.diff)}).`, v.b.boot_p));
  if (v.c) out.push(line(`Average move over the next ${horizon} days, in the direction a floor or ceiling would predict: ${fmt.spct(v.c.mean_target)} vs ${fmt.spct(v.c.mean_control)} (difference ${fmt.spct(v.c.diff)}).`, v.c.boot_p));
  return out;
}

/** Scoreboard: assets × controls. */
export function scoreboard(results, horizon) {
  const controls = [...new Set(results.flatMap((r) => r.mas.slice(1)))];
  const head = h('tr', {}, h('th', { class: 'l' }, 'Asset'), controls.map((c) => h('th', {}, `vs ${c}-day line`)));
  const rows = results.map((res) => h('tr', {}, h('td', { class: 'l' }, res.label), controls.map((c) => {
    const v = verdict(res, String(c), horizon);
    if (!v) return h('td', {}, '–');
    const worst = Math.min(v.b && v.b.boot_p != null ? v.b.boot_p : 1, v.c && v.c.boot_p != null ? v.c.boot_p : 1);
    return h('td', { class: sigClass(worst) }, h('span', { class: 'cell2' },
      `move ${fmt.spct(v.c && v.c.diff)}`, h('small', {}, `bounce ${fmt.pp(v.b && v.b.diff)}`)));
  })));
  return h('div', { class: 'tablewrap' }, h('table', { class: 'dt score' }, h('thead', {}, head), h('tbody', {}, rows)));
}

export const seriesDot = (i) => h('span', { class: 'dot', style: `display:inline-block;width:9px;height:9px;border-radius:50%;background:${seriesColor(i)};margin-right:6px` });
