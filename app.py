"""Flask app: local development server for the SMA Lab / Kalshi Lab web page.

    python app.py                 # http://127.0.0.1:5050

What it provides:
  * the static page (identical files to the Cloudflare deployment)
  * /api/analyze, /api/scan, /api/event_window - native-Python engine for the SMA Lab (fast)
  * /api/proxy/...  - the same-origin data proxy the in-browser Python needs (Yahoo, Kalshi, Coinbase)
  * /py/...         - the Python sources the in-browser engine loads

The production site (vivaanshahani.com/FinanceProjectTests) needs none of the /api/analyze routes:
it runs everything in the browser and only needs the proxy, implemented by cloudflare/worker.js.

For a hosted Flask deployment use ONE worker with threads, because analyses share process-global
era state and are serialised by a lock:
    gunicorn -w 1 --threads 4 --timeout 300 app:app
"""

from __future__ import annotations

import argparse
import re
import traceback
from pathlib import Path

import requests
from flask import Flask, Response, abort, jsonify, request, send_from_directory

import appmeta
import service

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.json.sort_keys = False
UA = {"User-Agent": "Mozilla/5.0 (compatible; sma-lab-proxy/1.0)", "Accept": "application/json"}

KALSHI_PATH = re.compile(r"^(markets|series|events|historical)(/[A-Za-z0-9_.\-]+)*$")
COINBASE_PATH = re.compile(r"^products/[A-Za-z0-9\-]{3,15}/candles$")
SYMBOL = re.compile(r"^[A-Za-z0-9^.=\-]{1,20}$")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "engine": "flask"})


@app.get("/api/meta")
def meta():
    return jsonify({"presets": appmeta.PRESETS, "defaults": service.DEFAULTS, "limits": service.LIMITS})


# ------------------------------------------------------------------ in-browser Python sources
@app.get("/py/manifest.json")
def py_manifest():
    return jsonify({"files": appmeta.PY_FILES})


@app.get("/py/<path:rel>")
def py_file(rel: str):
    if rel not in appmeta.PY_FILES:
        abort(404)
    return send_from_directory(ROOT, rel, mimetype="text/x-python")


# ------------------------------------------------------------------ data proxy (mirrors cloudflare/worker.js)
def _forward(url: str, ttl: int) -> Response:
    try:
        r = requests.get(url, headers=UA, timeout=40)
    except requests.RequestException as exc:
        return jsonify({"error": f"upstream unreachable: {exc}"}), 502
    resp = Response(r.content, status=r.status_code, mimetype="application/json")
    resp.headers["Cache-Control"] = f"public, max-age={ttl}"
    return resp


@app.get("/api/proxy/yahoo")
def proxy_yahoo():
    symbol = request.args.get("symbol", "")
    if not SYMBOL.match(symbol):
        return jsonify({"error": "invalid symbol"}), 400
    try:
        p1, p2 = int(request.args["period1"]), int(request.args["period2"])
    except (KeyError, ValueError):
        return jsonify({"error": "period1 and period2 (unix seconds) are required"}), 400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol, safe='')}"
           f"?period1={p1}&period2={p2}&interval=1d&includeAdjustedClose=true&events=div%2Csplit")
    return _forward(url, 3600)


@app.get("/api/proxy/<name>/<path:rest>")
def proxy_generic(name: str, rest: str):
    if name == "kalshi" and KALSHI_PATH.match(rest):
        ttl = 60
    elif name == "coinbase" and COINBASE_PATH.match(rest):
        ttl = 300
    else:
        return jsonify({"error": "path not allowed"}), 403
    qs = request.query_string.decode()
    if len(qs) > 6000:
        return jsonify({"error": "query too long"}), 414
    return _forward(f"{appmeta.UPSTREAMS[name]}/{rest}" + (f"?{qs}" if qs else ""), ttl)


# ------------------------------------------------------------------ native analysis API
def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise service.ConfigError("request body must be a JSON object")
    return body


@app.post("/api/analyze")
def api_analyze():
    return jsonify(service.analyze(_json_body().get("config")))


@app.post("/api/register_csv")
def api_register_csv():
    import data

    b = _json_body()
    try:
        return jsonify({"ticker": data.register_upload(str(b["name"]), str(b["text"]))})
    except (KeyError, ValueError) as exc:
        raise service.ConfigError(str(exc)) from None


@app.post("/api/event_window")
def api_event_window():
    b = _json_body()
    try:
        return jsonify(service.event_window(
            b.get("config") or {}, str(b["ticker"]), int(b["ma"]), str(b["date"]),
            str(b.get("direction", "support")), b.get("before", 40), b.get("after", 25)))
    except KeyError as exc:
        raise service.ConfigError(f"missing field {exc}") from None


@app.post("/api/scan")
def api_scan():
    b = _json_body()
    try:
        return jsonify(service.scan(b.get("config") or {}, str(b["ticker"]), b.get("min", 20), b.get("max", 400), b.get("step", 5)))
    except KeyError as exc:
        raise service.ConfigError(f"missing field {exc}") from None


@app.errorhandler(service.ConfigError)
def handle_config_error(exc):
    return jsonify({"error": str(exc)}), 400


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if getattr(exc, "code", None) and isinstance(exc.code, int) and exc.code < 500:  # HTTP errors (404 ...)
        return jsonify({"error": getattr(exc, "description", str(exc))}), exc.code
    traceback.print_exc()
    return jsonify({"error": f"internal error: {exc}"}), 500


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the SMA Lab web app locally.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    print(f"SMA Lab running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
