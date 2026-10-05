"""Serve dist/FinanceProjectTests exactly like production: static files under a sub-path,
plus ONLY the data proxy (no /api/analyze, no /api/health), so the page must use in-browser Python.

    python build_static.py && python serve_dist.py        # http://127.0.0.1:5001/FinanceProjectTests/
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, abort, redirect, send_from_directory

import app as dev_app

PREFIX = "/FinanceProjectTests"
ROOT = Path(__file__).resolve().parent / "dist" / "FinanceProjectTests"

site = Flask(__name__, static_folder=None)


@site.get(PREFIX)
def bare():
    return redirect(PREFIX + "/", 301)  # what Cloudflare Pages does for a directory


@site.get(PREFIX + "/")
def home():
    return send_from_directory(ROOT, "index.html")


@site.get(PREFIX + "/<path:rel>")
def files(rel: str):
    if rel.startswith("api/"):
        abort(404)
    return send_from_directory(ROOT, rel)


site.add_url_rule(PREFIX + "/api/proxy/yahoo", view_func=dev_app.proxy_yahoo)
site.add_url_rule(PREFIX + "/api/proxy/<name>/<path:rest>", view_func=dev_app.proxy_generic)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5001)
    args = ap.parse_args()
    print(f"Serving {ROOT} at http://127.0.0.1:{args.port}{PREFIX}/")
    site.run(port=args.port, threaded=True)


if __name__ == "__main__":
    main()
