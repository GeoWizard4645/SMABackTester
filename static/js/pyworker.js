/* Module Web Worker: runs the project's real Python modules in the browser with Pyodide.
 * Messages in : {id, type:'init', baseUrl, proxyBase} | {id, type:'call', fn, args}
 * Messages out: {id, type:'result', data} | {id, type:'error', message} | {type:'status'|'progress', text}
 */
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const INDEX_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';

let pyodide = null;
let bridge = null;
let currentId = null;
const status = (text) => postMessage({ type: 'status', text });

async function init({ baseUrl, proxyBase }) {
  status('Downloading the Python runtime…');
  pyodide = await loadPyodide({ indexURL: INDEX_URL });
  status('Loading numpy, pandas and scipy (first visit only, ~30 MB)…');
  await pyodide.loadPackage(['numpy', 'pandas', 'scipy']);
  status('Loading the analysis code…');
  const manifest = await (await fetch(new URL('py/manifest.json', baseUrl))).json();
  pyodide.FS.mkdirTree('/home/pyodide/app/kalshi_lab');
  for (const file of manifest.files) {
    const res = await fetch(new URL(`py/${file}`, baseUrl));
    if (!res.ok) throw new Error(`could not load py/${file} (${res.status})`);
    pyodide.FS.writeFile(`/home/pyodide/app/${file}`, await res.text());
  }
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
  bridge = pyodide.pyimport('bridge');
  bridge.configure(proxyBase, (text) => postMessage({ type: 'progress', id: currentId, text: String(text) }));
  status('Python ready.');
}

async function call(id, fn, args) {
  currentId = id;
  if (fn === 'run_code') await pyodide.loadPackagesFromImports(args.code || '');
  const raw = bridge.call(fn, JSON.stringify(args || {})); // blocks this worker; network is sync XHR
  const out = JSON.parse(raw);
  if (out && out.__error) {
    const err = new Error(out.__error);
    if (out.__trace) err.trace = out.__trace;
    throw err;
  }
  return out;
}

onmessage = async (e) => {
  const { id, type } = e.data;
  try {
    if (type === 'init') {
      await init(e.data);
      postMessage({ id, type: 'result', data: { ready: true } });
    } else if (type === 'call') {
      postMessage({ id, type: 'result', data: await call(id, e.data.fn, e.data.args) });
    }
  } catch (err) {
    postMessage({ id, type: 'error', message: err && err.message ? err.message : String(err), trace: err && err.trace });
  }
};
