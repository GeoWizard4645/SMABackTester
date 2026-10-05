"""Rehearse production: serve ONLY dist/index.html plus the data proxy.

Any other file (static/, py/, ...) answers 404 and there is no /api/analyze, so this proves the single-file
build works on its own and runs the analysis with in-browser Python, exactly like Cloudflare will.

    python build_static.py && python serve_dist.py                    # http://127.0.0.1:5001/
    python serve_dist.py --prefix /FinanceProjectTests                # http://127.0.0.1:5001/FinanceProjectTests/
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, abort, redirect, send_from_directory

import app as dev_app

DIST = Path(__file__).resolve().parent / "dist"


def make_app(prefix: str) -> Flask:
    site = Flask(__name__, static_folder=None)
    if prefix:
        site.add_url_rule(prefix, "bare", lambda: redirect(prefix + "/", 301))  # what Cloudflare Pages does
    site.add_url_rule(prefix + "/", "home", lambda: send_from_directory(DIST, "index.html"))
    site.add_url_rule(prefix + "/<path:rel>", "other", lambda rel: abort(404))
    site.add_url_rule(prefix + "/api/proxy/yahoo", "yahoo", dev_app.proxy_yahoo)
    site.add_url_rule(prefix + "/api/proxy/<name>/<path:rest>", "proxy", dev_app.proxy_generic)
    return site


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--prefix", default="", help="optional sub-path, e.g. /FinanceProjectTests")
    args = ap.parse_args()
    prefix = args.prefix.rstrip("/")
    print(f"Serving {DIST / 'index.html'} at http://127.0.0.1:{args.port}{prefix}/")
    make_app(prefix).run(port=args.port, threaded=True)


if __name__ == "__main__":
    main()
