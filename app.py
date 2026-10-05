"""Flask web app: an interactive lab for the SMA support/resistance research pipeline.

    python app.py                 # http://127.0.0.1:5000
    python app.py --port 8080 --host 0.0.0.0

For a hosted deployment use ONE worker with threads, because analyses share
process-global era state and are serialised by a lock:
    gunicorn -w 1 --threads 4 --timeout 300 app:app
"""

from __future__ import annotations

import argparse
import traceback

from flask import Flask, jsonify, request, send_from_directory

import service

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.json.sort_keys = False

PRESETS = [
    {
        "group": "US indices",
        "items": [
            {"t": "^GSPC", "n": "S&P 500"}, {"t": "^IXIC", "n": "Nasdaq Composite"},
            {"t": "^DJI", "n": "Dow Jones"}, {"t": "^RUT", "n": "Russell 2000"},
            {"t": "^NDX", "n": "Nasdaq 100"},
        ],
    },
    {
        "group": "World indices",
        "items": [
            {"t": "^FTSE", "n": "FTSE 100"}, {"t": "^GDAXI", "n": "DAX"},
            {"t": "^N225", "n": "Nikkei 225"}, {"t": "^HSI", "n": "Hang Seng"},
            {"t": "^STOXX50E", "n": "Euro Stoxx 50"},
        ],
    },
    {
        "group": "ETFs & commodities",
        "items": [
            {"t": "SPY", "n": "SPDR S&P 500"}, {"t": "QQQ", "n": "Invesco QQQ"},
            {"t": "IWM", "n": "iShares Russell 2000"}, {"t": "GLD", "n": "Gold ETF"},
            {"t": "TLT", "n": "20+yr Treasuries"}, {"t": "GC=F", "n": "Gold futures"},
            {"t": "CL=F", "n": "Crude oil futures"},
        ],
    },
    {
        "group": "Stocks",
        "items": [
            {"t": "AAPL", "n": "Apple"}, {"t": "MSFT", "n": "Microsoft"},
            {"t": "NVDA", "n": "Nvidia"}, {"t": "AMZN", "n": "Amazon"},
            {"t": "GOOGL", "n": "Alphabet"}, {"t": "META", "n": "Meta"},
            {"t": "TSLA", "n": "Tesla"}, {"t": "JPM", "n": "JPMorgan"},
            {"t": "XOM", "n": "Exxon Mobil"}, {"t": "KO", "n": "Coca-Cola"},
        ],
    },
    {
        "group": "Crypto",
        "items": [
            {"t": "BTC-USD", "n": "Bitcoin"}, {"t": "ETH-USD", "n": "Ethereum"},
            {"t": "SOL-USD", "n": "Solana"}, {"t": "XRP-USD", "n": "XRP"},
            {"t": "DOGE-USD", "n": "Dogecoin"}, {"t": "BNB-USD", "n": "BNB"},
            {"t": "ADA-USD", "n": "Cardano"}, {"t": "LTC-USD", "n": "Litecoin"},
        ],
    },
    {
        "group": "Sanity check",
        "items": [{"t": service.SYNTHETIC, "n": "Synthetic random walk (no effect by construction)"}],
    },
]


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/meta")
def meta():
    return jsonify({"presets": PRESETS, "defaults": service.DEFAULTS, "limits": service.LIMITS})


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise service.ConfigError("request body must be a JSON object")
    return body


@app.post("/api/analyze")
def api_analyze():
    return jsonify(service.analyze(_json_body().get("config")))


@app.post("/api/event_window")
def api_event_window():
    b = _json_body()
    try:
        return jsonify(
            service.event_window(
                b.get("config") or {}, str(b["ticker"]), int(b["ma"]), str(b["date"]),
                str(b.get("direction", "support")), b.get("before", 40), b.get("after", 25),
            )
        )
    except KeyError as exc:
        raise service.ConfigError(f"missing field {exc}") from None


@app.post("/api/scan")
def api_scan():
    b = _json_body()
    try:
        return jsonify(
            service.scan(
                b.get("config") or {}, str(b["ticker"]), b.get("min", 20), b.get("max", 400),
                b.get("step", 5),
            )
        )
    except KeyError as exc:
        raise service.ConfigError(f"missing field {exc}") from None


@app.errorhandler(service.ConfigError)
def handle_config_error(exc):
    return jsonify({"error": str(exc)}), 400


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc()
    return jsonify({"error": f"internal error: {exc}"}), 500


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the SMA research web app.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    print(f"SMA Lab running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
