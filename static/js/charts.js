// Plotly renderers. Every function draws into a given <div> and reads theme colours at call time.

import { cssVar, seriesColor, rgba, fmt, quantile } from './util.js';

const CONFIG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] };

function base(extra = {}) {
  const ink2 = cssVar('--ink-2'), grid = cssVar('--line');
  const axis = { gridcolor: grid, zerolinecolor: grid, linecolor: grid, tickfont: { color: ink2 }, automargin: true };
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif', color: ink2, size: 12 },
    margin: { l: 58, r: 16, t: 34, b: 44 },
    xaxis: { ...axis }, yaxis: { ...axis },
    legend: { orientation: 'h', y: -0.2, font: { color: ink2 } },
    hoverlabel: { bgcolor: cssVar('--surface'), font: { color: cssVar('--ink') }, bordercolor: grid },
    ...extra,
  };
}
const merge = (a, b) => ({ ...a, ...b, xaxis: { ...a.xaxis, ...(b.xaxis || {}) }, yaxis: { ...a.yaxis, ...(b.yaxis || {}) } });
const draw = (div, traces, layout) => Plotly.react(div, traces, layout, CONFIG);
export const resizeAll = () => document.querySelectorAll('.js-plotly-plot').forEach((d) => Plotly.Plots.resize(d));

export function maColor(ma, mas) { return seriesColor(Math.max(0, mas.indexOf(ma))); }
const title = (text) => ({ text, x: 0, xanchor: 'left', font: { size: 13, color: cssVar('--ink') } });

// ------------------------------------------------------------------ price + events
export function plotPrice(div, res, opts) {
  const { log, hideLines = new Set(), hideEvents = new Set() } = opts;
  const mas = res.mas, p = res.price;
  const traces = [{
    x: p.dates, y: p.close, type: 'scattergl', mode: 'lines', name: 'Close', hoverinfo: 'x+y',
    line: { color: cssVar('--ink-3'), width: 1 },
  }];
  for (const ma of mas) {
    traces.push({
      x: p.dates, y: p.lines[ma], type: 'scattergl', mode: 'lines', name: `${ma}-bar line`,
      line: { color: maColor(ma, mas), width: ma === mas[0] ? 2 : 1.4 },
      visible: hideLines.has(ma) ? 'legendonly' : true, hovertemplate: `%{y:,.2f}<extra>${ma}</extra>`,
    });
  }
  for (const ma of mas) {
    for (const dir of ['support', 'resistance']) {
      const ev = res.events.filter((e) => e.ma === ma && e.direction === dir);
      traces.push({
        x: ev.map((e) => e.date), y: ev.map((e) => e.close), type: 'scatter', mode: 'markers',
        name: `${ma} ${dir}`, legendgroup: `ev${ma}`,
        marker: { symbol: dir === 'support' ? 'triangle-up' : 'triangle-down', size: 8, color: maColor(ma, mas), line: { color: cssVar('--surface'), width: 1 } },
        visible: hideEvents.has(ma) ? 'legendonly' : true,
        customdata: ev.map((e) => [e.era, e.dist_atr, e.atr_ratio]),
        hovertemplate: `<b>${ma} ${dir} test</b><br>%{x}<br>close %{y:,.2f}<br>%{customdata[0]} · ${'%{customdata[1]:.2f}'} ATR from line<extra></extra>`,
      });
    }
  }
  const shapes = [], annotations = [];
  const first = parseInt(p.dates[0].slice(0, 4), 10);
  const bounds = [first, ...res.era_ends.map((e) => e + 1)];
  res.era_ends.forEach((e) => shapes.push({ type: 'line', x0: `${e + 1}-01-01`, x1: `${e + 1}-01-01`, yref: 'paper', y0: 0, y1: 1, line: { color: cssVar('--ink-3'), width: 1, dash: 'dot' } }));
  res.eras.forEach((er, i) => {
    const x = i === 0 ? p.dates[0] : `${bounds[i]}-01-01`;
    annotations.push({ x, y: 1, yref: 'paper', xanchor: 'left', yanchor: 'bottom', text: er.name, showarrow: false, font: { size: 11, color: cssVar('--ink-3') } });
  });
  const layout = merge(base(), {
    height: 520, margin: { l: 62, r: 16, t: 28, b: 40 }, shapes, annotations,
    xaxis: { rangeslider: { visible: true, thickness: 0.07 }, type: 'date' },
    yaxis: { type: log ? 'log' : 'linear', title: { text: log ? 'Price (log)' : 'Price' } },
    legend: { orientation: 'h', y: 1.1, x: 0 }, hovermode: 'x unified',
  });
  draw(div, traces, layout);
}

// ------------------------------------------------------------------ event study
function pathTraces(block, offsets, color, name, group) {
  if (!block || !block.mean) return [];
  const x = offsets, m = block.mean.map((v) => (v == null ? null : 100 * v));
  const hi = block.mean.map((v, i) => (v == null || block.se[i] == null ? null : 100 * (v + 1.96 * block.se[i])));
  const lo = block.mean.map((v, i) => (v == null || block.se[i] == null ? null : 100 * (v - 1.96 * block.se[i])));
  return [
    { x, y: lo, mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, legendgroup: group, type: 'scatter' },
    { x, y: hi, mode: 'lines', line: { width: 0 }, fill: 'tonexty', fillcolor: rgba(color, 0.14), hoverinfo: 'skip', showlegend: false, legendgroup: group, type: 'scatter' },
    { x, y: m, mode: 'lines+markers', name: `${name} (n=${block.n})`, legendgroup: group, type: 'scatter',
      line: { color, width: 2 }, marker: { size: 5 }, hovertemplate: `t%{x:+d}: %{y:.2f}%<extra>${name}</extra>` },
  ];
}
function pathLayout(res, titleText, yText) {
  return merge(base(), {
    height: 360, title: title(titleText), margin: { l: 58, r: 12, t: 38, b: 70 },
    xaxis: { title: { text: 'Bars relative to touch (t = 0)' }, dtick: 1, zeroline: false },
    yaxis: { title: { text: yText }, ticksuffix: '%' },
    shapes: [{ type: 'line', x0: 0, x1: 0, yref: 'paper', y0: 0, y1: 1, line: { color: cssVar('--ink-3'), dash: 'dash', width: 1 } }],
    legend: { orientation: 'h', y: -0.28 },
  });
}
export function plotStudy(divs, res, pre) {
  const { offsets, series } = res.paths, mas = res.mas;
  const yText = `Abnormal cumulative return from t−${pre}`;
  [['support', 'Support tests (approach from above)'], ['resistance', 'Resistance tests (approach from below)'], ['pooled', 'Pooled, direction-adjusted (up = reacts as S/R predicts)']]
    .forEach(([key, t], i) => {
      const traces = mas.flatMap((ma) => pathTraces(series[ma][key], offsets, maColor(ma, mas), `${ma}`, `m${ma}`));
      if (!traces.length) { divs[i].innerHTML = '<p class="note" style="padding:20px">No events in this group.</p>'; return; }
      draw(divs[i], traces, pathLayout(res, t, yText));
    });
}
export function plotStudyByEra(div, res, ma, pre) {
  const { offsets, series } = res.paths;
  const traces = res.eras.flatMap((er, i) => pathTraces(series[ma].era[er.name], offsets, seriesColor(i), `${er.name} ${er.desc}`, `e${i}`));
  if (!traces.length) { div.innerHTML = '<p class="note" style="padding:20px">No events.</p>'; return; }
  draw(div, traces, pathLayout(res, `${ma}-bar line, pooled and direction-adjusted, by era`, `Abnormal cumulative return from t−${pre}`));
}

// ------------------------------------------------------------------ eras
function eraCats(res) { return [...res.eras.map((e) => e.name), 'All']; }
function eraTick(res) { return eraCats(res).map((n) => (n === 'All' ? 'All' : `${n}<br>${res.eras.find((e) => e.name === n).desc}`)); }

function barTraces(res, horizon, kind) {
  const cats = eraCats(res), mas = res.mas;
  return mas.map((ma) => {
    const rows = cats.map((c) => res.summary.find((r) => r.ma === ma && r.era === c && r.horizon === horizon));
    const v = rows.map((r) => (r && r[kind + (kind === 'bounce' ? '_rate' : '_mean')] != null ? 100 * r[kind + (kind === 'bounce' ? '_rate' : '_mean')] : null));
    const hi = rows.map((r, i) => (r && r[kind + '_hi'] != null && v[i] != null ? 100 * r[kind + '_hi'] - v[i] : null));
    const lo = rows.map((r, i) => (r && r[kind + '_lo'] != null && v[i] != null ? v[i] - 100 * r[kind + '_lo'] : null));
    return {
      type: 'bar', name: `${ma}`, x: eraTick(res), y: v, marker: { color: maColor(ma, mas), line: { color: cssVar('--surface'), width: 1.5 } },
      error_y: { type: 'data', symmetric: false, array: hi, arrayminus: lo, color: cssVar('--ink-2'), thickness: 1, width: 3 },
      customdata: rows.map((r) => (r ? r.n : 0)),
      hovertemplate: `%{x}<br>${ma}: %{y:.2f}%<br>n=%{customdata}<extra></extra>`,
    };
  });
}
export function plotEraBars(divs, res, control, horizon) {
  const lay = (t, y, extra = {}) => merge(base(), { height: 340, title: title(t), barmode: 'group', bargap: 0.25, yaxis: { title: { text: y }, ticksuffix: '%' }, ...extra });
  draw(divs.bounce, barTraces(res, horizon, 'bounce'), lay(`Bounce rate at ${horizon} bars (Wilson 95% CI)`, 'Bounce rate', {
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 50, y1: 50, line: { color: cssVar('--ink-3'), dash: 'dash', width: 1 } }] }));
  draw(divs.car, barTraces(res, horizon, 'car'), lay(`Direction-adjusted CAR at ${horizon} bars (95% CI of mean)`, 'Mean CAR'));
  const comp = res.comparisons[control];
  for (const [key, kind, t] of [['gapBounce', 'bounce', 'Bounce-rate gap'], ['gapCar', 'car', 'CAR gap']]) {
    if (!comp) { divs[key].innerHTML = '<p class="note" style="padding:20px">Add a control line to compare.</p>'; continue; }
    const rows = eraCats(res).map((c) => comp.find((r) => r.era === c && r.metric === kind && r.horizon === horizon));
    const y = rows.map((r) => (r && r.diff != null ? 100 * r.diff : null));
    const up = rows.map((r, i) => (r && r.boot_hi != null && y[i] != null ? 100 * r.boot_hi - y[i] : null));
    const dn = rows.map((r, i) => (r && r.boot_lo != null && y[i] != null ? y[i] - 100 * r.boot_lo : null));
    draw(divs[key], [{
      type: 'bar', x: eraTick(res), y, marker: { color: seriesColor(0), line: { color: cssVar('--surface'), width: 1.5 } },
      error_y: { type: 'data', symmetric: false, array: up, arrayminus: dn, color: cssVar('--ink-2'), thickness: 1, width: 3 },
      customdata: rows.map((r) => (r ? [r.boot_p, r.welch_p, r.mwu_p, r.n_target, r.n_control] : [])),
      hovertemplate: '%{x}<br>gap %{y:.2f} pp<br>bootstrap p=%{customdata[0]:.4f}<br>Welch p=%{customdata[1]:.4f} · MWU p=%{customdata[2]:.4f}<br>n %{customdata[3]} vs %{customdata[4]}<extra></extra>',
    }], merge(base(), { height: 340, title: title(`${res.mas[0]} minus ${control}: ${t} at ${horizon} bars (year-cluster bootstrap 95% CI)`), yaxis: { title: { text: `${t} (pp)` } }, showlegend: false,
      shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: cssVar('--ink-3'), width: 1 } }] }));
  }
}

// ------------------------------------------------------------------ line scan
/** Returns {stats} for the caption; draws scatter + histogram. */
export function plotScan(divLine, divHist, scan, o) {
  const { metric, horizon, era, minN, exclude } = o;
  const rows = scan.metrics[era];
  const pts = scan.windows.map((w, i) => ({ w, n: rows[i].n, v: rows[i][metric][horizon] })).filter((p) => p.v != null);
  const ok = pts.filter((p) => p.n >= minN);
  const tgt = ok.find((p) => p.w === scan.target);
  const others = ok.filter((p) => p.w !== scan.target && Math.abs(p.w - scan.target) > exclude);
  const vals = others.map((p) => p.v).sort((a, b) => a - b);
  const scale = 100, yText = metric === 'bounce' ? 'Bounce rate (%)' : 'Mean direction-adjusted CAR (%)';
  const traces = [
    { x: pts.filter((p) => p.n < minN).map((p) => p.w), y: pts.filter((p) => p.n < minN).map((p) => scale * p.v), type: 'scatter', mode: 'markers', name: `n < ${minN} (excluded)`, marker: { size: 5, color: cssVar('--ink-3'), opacity: 0.4 }, hovertemplate: 'line %{x}: %{y:.2f}%<extra>few events</extra>' },
    { x: others.map((p) => p.w), y: others.map((p) => scale * p.v), type: 'scatter', mode: 'lines+markers', name: 'Other lines', line: { color: cssVar('--ink-3'), width: 1 }, marker: { size: 5, color: cssVar('--ink-2') },
      customdata: others.map((p) => p.n), hovertemplate: 'line %{x}: %{y:.2f}%<br>n=%{customdata}<extra></extra>' },
  ];
  const ctl = ok.filter((p) => scan.controls.includes(p.w));
  if (ctl.length) traces.push({ x: ctl.map((p) => p.w), y: ctl.map((p) => scale * p.v), type: 'scatter', mode: 'markers', name: 'Your control lines', marker: { size: 11, color: seriesColor(1), symbol: 'diamond', line: { color: cssVar('--surface'), width: 1.5 } }, hovertemplate: 'control %{x}: %{y:.2f}%<extra></extra>' });
  if (tgt) traces.push({ x: [tgt.w], y: [scale * tgt.v], type: 'scatter', mode: 'markers', name: `Target (${scan.target})`, marker: { size: 15, color: seriesColor(0), line: { color: cssVar('--surface'), width: 2 } }, hovertemplate: `target %{x}: %{y:.2f}%<extra></extra>` });
  const shapes = [];
  if (vals.length >= 5) {
    const q05 = scale * quantile(vals, 0.05), q95 = scale * quantile(vals, 0.95), med = scale * quantile(vals, 0.5);
    shapes.push({ type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: q05, y1: q95, fillcolor: rgba(cssVar('--ink-3').startsWith('#') ? cssVar('--ink-3') : '#85847f', 0.12), line: { width: 0 }, layer: 'below' });
    shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: med, y1: med, line: { color: cssVar('--ink-3'), dash: 'dash', width: 1 } });
  }
  shapes.push({ type: 'rect', x0: scan.target - exclude, x1: scan.target + exclude, yref: 'paper', y0: 0, y1: 1, fillcolor: rgba('#2a78d6', 0.06), line: { width: 0 }, layer: 'below' });
  draw(divLine, traces, merge(base(), { height: 420, title: title(`${yText} by line length — ${era === 'All' ? 'full sample' : era}, ${horizon}-bar horizon`), xaxis: { title: { text: 'Line length (bars)' } }, yaxis: { title: { text: yText }, ticksuffix: '%' }, shapes, legend: { orientation: 'h', y: -0.22 } }));

  // histogram of other lines with target marked
  const histTraces = [{ x: vals.map((v) => scale * v), type: 'histogram', name: 'Other lines', marker: { color: cssVar('--ink-3') }, opacity: 0.75, nbinsx: 24, hovertemplate: '%{x:.2f}%: %{y} lines<extra></extra>' }];
  const hshapes = tgt ? [{ type: 'line', x0: scale * tgt.v, x1: scale * tgt.v, yref: 'paper', y0: 0, y1: 1, line: { color: seriesColor(0), width: 3 } }] : [];
  draw(divHist, histTraces, merge(base(), { height: 300, title: title('Where the target falls among all other lines'), xaxis: { title: { text: yText }, ticksuffix: '%' }, yaxis: { title: { text: 'Number of lines' } }, shapes: hshapes, showlegend: false,
    annotations: tgt ? [{ x: scale * tgt.v, y: 1, yref: 'paper', text: `target ${scan.target}`, showarrow: false, xanchor: 'left', yanchor: 'top', font: { color: seriesColor(0), size: 12 } }] : [] }));

  if (!tgt) return { error: `The target line has fewer than ${minN} events here (or no data).` };
  const above = vals.filter((v) => v >= tgt.v).length, below = vals.filter((v) => v <= tgt.v).length;
  const m = vals.length;
  return {
    m, target: tgt.v, n: tgt.n,
    pctBelow: m ? (100 * vals.filter((v) => v < tgt.v).length) / m : null,
    pUp: (1 + above) / (m + 1), pDown: (1 + below) / (m + 1), pTwo: Math.min(1, 2 * Math.min((1 + above) / (m + 1), (1 + below) / (m + 1))),
    median: quantile(vals, 0.5), q05: quantile(vals, 0.05), q95: quantile(vals, 0.95),
  };
}

// ------------------------------------------------------------------ event explorer
export function plotEventWindow(div, win, ev, direction, horizons, cfg) {
  const x = win.dates, i0 = win.event_index, dark = cssVar('--ink-2');
  const traces = [
    { x, y: win.upper, type: 'scatter', mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { x, y: win.lower, type: 'scatter', mode: 'lines', line: { width: 0 }, fill: 'tonexty', fillcolor: rgba('#2a78d6', 0.16), name: `Touch band (±${cfg.band} ATR)`, hoverinfo: 'skip' },
    { x, open: win.open, high: win.high, low: win.low, close: win.close, type: 'candlestick', name: 'Price',
      increasing: { line: { color: dark }, fillcolor: cssVar('--surface') }, decreasing: { line: { color: dark }, fillcolor: dark } },
    { x, y: win.sma, type: 'scatter', mode: 'lines', name: `${ev.ma}-bar line`, line: { color: seriesColor(0), width: 2.2 } },
    { x, y: win.breach, type: 'scatter', mode: 'lines', name: `Failure level (${direction === 'support' ? '−' : '+'}${cfg.breach} ATR)`, line: { color: seriesColor(1), width: 1.5, dash: 'dash' } },
  ];
  const marks = horizons.filter((k) => i0 + k < x.length);
  traces.push({ x: marks.map((k) => x[i0 + k]), y: marks.map((k) => win.close[i0 + k]), type: 'scatter', mode: 'markers+text', text: marks.map((k) => `t+${k}`), textposition: 'top center', name: 'Outcome closes', marker: { size: 9, color: seriesColor(2), symbol: 'circle', line: { color: cssVar('--surface'), width: 1.5 } }, hovertemplate: '%{text}: close %{y:,.2f}<extra></extra>' });
  traces.push({ x: [x[i0]], y: [win.close[i0]], type: 'scatter', mode: 'markers', name: 'Entry (close of touch day)', marker: { size: 13, color: seriesColor(3), symbol: 'star', line: { color: cssVar('--surface'), width: 1.5 } } });
  const maxH = Math.max(...horizons.filter((k) => i0 + k < x.length), 0);
  const layout = merge(base(), {
    height: 520, margin: { l: 62, r: 16, t: 28, b: 60 },
    xaxis: { type: 'category', rangeslider: { visible: false }, nticks: 12, tickangle: -35 },
    yaxis: { title: { text: 'Price' } },
    shapes: [
      { type: 'rect', x0: x[i0], x1: x[Math.min(x.length - 1, i0 + maxH)], yref: 'paper', y0: 0, y1: 1, fillcolor: rgba('#2a78d6', 0.05), line: { width: 0 }, layer: 'below' },
      { type: 'line', x0: x[i0], x1: x[i0], yref: 'paper', y0: 0, y1: 1, line: { color: cssVar('--ink-3'), dash: 'dot', width: 1 } },
    ],
    legend: { orientation: 'h', y: 1.12, x: 0 },
  });
  draw(div, traces, layout);
}
