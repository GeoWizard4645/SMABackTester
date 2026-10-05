// Chooses where analyses run:
//   server  - a local Flask process (fast, native Python)           -> only for the SMA Lab
//   browser - Python in a Web Worker (Pyodide); works on static hosting such as Cloudflare Pages
// Everything uses relative URLs so the app works under any sub-path (e.g. /FinanceProjectTests/).

const APP_BASE = new URL('.', location.href).href;
const SERVER_FNS = new Set(['analyze', 'event_window', 'scan', 'register_csv']);

let serverMode = null;
let worker = null;
let ready = null;
let seq = 0;
const pending = new Map();
const statusListeners = new Set();

export const onStatus = (fn) => statusListeners.add(fn);
const emit = (text) => statusListeners.forEach((fn) => fn(text));

export async function detect() {
  if (serverMode !== null) return serverMode ? 'server' : 'browser';
  const forced = new URLSearchParams(location.search).get('engine');
  if (forced === 'browser') serverMode = false;
  else {
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 2500);
      const res = await fetch('api/health', { cache: 'no-store', signal: ctl.signal });
      clearTimeout(timer);
      serverMode = res.ok && (await res.json()).ok === true;
    } catch {
      serverMode = false;
    }
  }
  return serverMode ? 'server' : 'browser';
}

function startWorker() {
  if (ready) return ready;
  worker = new Worker(new URL('./pyworker.js', import.meta.url), { type: 'module' });
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.type === 'status') { emit(m.text); return; }
    if (m.type === 'progress') { const p = pending.get(m.id); if (p && p.onProgress) p.onProgress(m.text); emit(m.text); return; }
    const p = pending.get(m.id);
    if (!p) return;
    pending.delete(m.id);
    if (m.type === 'result') p.resolve(m.data);
    else p.reject(Object.assign(new Error(m.message), { trace: m.trace }));
  };
  worker.onerror = (e) => emit(`Python worker error: ${e.message}`);
  ready = send({ type: 'init', baseUrl: APP_BASE, proxyBase: new URL('api/proxy', APP_BASE).href });
  ready.catch(() => { ready = null; worker = null; });
  return ready;
}

function send(msg, onProgress) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject, onProgress });
    worker.postMessage({ ...msg, id });
  });
}

async function callServer(fn, args) {
  const res = await fetch(`api/${fn}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args) });
  let json = null;
  try { json = await res.json(); } catch { /* ignore */ }
  if (!res.ok) throw new Error((json && json.error) || `Request failed (${res.status})`);
  return json;
}

/** Run a named function. Returns the parsed JSON result; rejects with an Error on failure. */
export async function call(fn, args = {}, { onProgress } = {}) {
  if (SERVER_FNS.has(fn) && (await detect()) === 'server') return callServer(fn, args);
  await startWorker();
  const done = send({ type: 'call', fn, args }, onProgress);
  return done;
}

export const warmUp = () => startWorker();
export const engineName = () => (serverMode === null ? 'unknown' : serverMode ? 'server' : 'browser');
