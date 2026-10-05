"""Build the website.

    python build_static.py              # -> public/index.html   (ONE self-contained file; commit it)
    python build_static.py --no-snapshot  # skip the saved live Kalshi run (offline / faster)

`public/index.html` has the styles, the JavaScript, the Python sources and the maths page inlined, so
publishing that single file is enough: nothing can be left behind. It needs only the data proxy
(cloudflare/worker.js, deployed with the repo-root wrangler.toml) at  <site>/api/proxy/...  and the public CDNs for Plotly, KaTeX and Pyodide.

    python build_static.py --multi      # also write the multi-file layout to dist/site/ (not needed for Cloudflare)

Bundling the JavaScript needs Node (npx esbuild). Without Node, use --multi.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import appmeta
import service
from kalshi_lab import kalshi_data, web

ROOT = Path(__file__).resolve().parent
ESBUILD = "esbuild@0.24.0"


def meta_dict() -> dict:
    return {
        "presets": appmeta.PRESETS,
        "defaults": service.DEFAULTS,
        "limits": service.LIMITS,
        "kalshi": {
            "defaults": {**web.DEFAULTS, "fee_choice": "taker", "fee_custom": 0.07, "rules": ["r1", "r2", "r3"]},
            "series": {k: v[1] for k, v in kalshi_data.SERIES.items()},
            "examples": web.EXAMPLES,
        },
    }


def write_meta(dest: Path) -> None:
    dest.write_text(json.dumps(meta_dict(), indent=1, ensure_ascii=False), encoding="utf-8")


def _safe_json(obj) -> str:
    """JSON that is safe inside an HTML <script> element."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def kalshi_snapshot(days: float) -> dict | None:
    """Run the default Kalshi study on LIVE data now, so the page opens with the main breakdown already on screen."""
    print(f"computing the saved Kalshi run ({days:g} days of live data; about a minute)...")
    try:
        result = web.run_lab({**web.DEFAULTS, "source": "live", "days": days})
    except Exception as exc:  # no network, API down, rate limited ...
        print(f"  skipped: {exc}\n  (the page will open on an empty Kalshi tab; press Run there)")
        return None
    result["snapshot_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return result


def bundle_js() -> str:
    cmd = ["npx", "--yes", ESBUILD, str(ROOT / "static/js/main.js"), "--bundle", "--format=esm", "--minify",
           "--target=es2020", "--log-level=warning"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=ROOT)
    except FileNotFoundError:
        raise SystemExit("Node.js (npx) is required to bundle the JavaScript. Install Node, or use --multi.") from None
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"esbuild failed:\n{exc.stderr}") from None
    return res.stdout.replace("</script", "<\\/script")


def build_single(out: Path, snapshot: dict | None = None) -> Path:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    method = (ROOT / "static/method.html").read_text(encoding="utf-8")
    worker = (ROOT / "static/js/pyworker.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    files = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in appmeta.PY_FILES}

    link = '<link rel="stylesheet" href="static/style.css">'
    entry = '<script type="module" src="static/js/main.js"></script>'
    if link not in html or entry not in html:
        raise SystemExit("static/index.html no longer has the expected stylesheet / script tags")
    html = html.replace(link, f"<style>\n{css}\n</style>")
    snap = [f'<script type="application/json" id="kalshi-snapshot">{_safe_json(snapshot)}</script>'] if snapshot else []
    inline = "\n".join(snap + [
        f'<script type="application/json" id="meta-json">{_safe_json(meta_dict())}</script>',
        f'<script type="application/json" id="py-files">{_safe_json(files)}</script>',
        f'<script type="text/plain" id="pyworker-src">{worker}</script>',
        f'<template id="method-html">{method}</template>',
        f'<script type="module">\n{bundle_js()}\n</script>',
    ])
    html = html.replace(entry, inline)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "index.html"
    dest.write_text(html, encoding="utf-8")
    return dest


def build_multi(out: Path) -> Path:
    site = out / "site"
    if site.exists():
        shutil.rmtree(site)
    (site / "static").mkdir(parents=True)
    shutil.copy(ROOT / "static/index.html", site / "index.html")
    for item in ("style.css", "method.html"):
        shutil.copy(ROOT / "static" / item, site / "static" / item)
    shutil.copytree(ROOT / "static/js", site / "static/js")
    write_meta(site / "static/meta.json")
    for rel in appmeta.PY_FILES:
        dest = site / "py" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, dest)
    (site / "py/manifest.json").write_text(json.dumps({"files": appmeta.PY_FILES}), encoding="utf-8")
    return site


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="public", help="folder Cloudflare serves (wrangler.toml points at ./public)")
    ap.add_argument("--multi", action="store_true", help="also write the multi-file layout to dist/site/")
    ap.add_argument("--meta-only", action="store_true", help="only refresh static/meta.json (local Flask server)")
    ap.add_argument("--no-snapshot", action="store_true", help="skip the saved live Kalshi run (faster, works offline)")
    ap.add_argument("--snapshot-days", type=float, default=14, help="days of live data in the saved Kalshi run")
    ap.add_argument("--reuse-snapshot", action="store_true", help="embed the previous saved Kalshi run instead of recomputing it")
    args = ap.parse_args()
    write_meta(ROOT / "static/meta.json")
    if args.meta_only:
        print("wrote static/meta.json")
        return
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for stale in ("cloudflare", "functions", "FinanceProjectTests"):  # leftovers from older builds
        shutil.rmtree(out / stale, ignore_errors=True)
    snap_file = ROOT / "static/kalshi_snapshot.json"  # lets the local Flask server show the same saved run
    if args.reuse_snapshot and snap_file.exists():
        snapshot = json.loads(snap_file.read_text(encoding="utf-8"))
    else:
        snapshot = None if args.no_snapshot else kalshi_snapshot(args.snapshot_days)
    if snapshot:
        snap_file.write_text(json.dumps(snapshot), encoding="utf-8")
    else:
        snap_file.unlink(missing_ok=True)
    page = build_single(out, snapshot)
    print(f"built {page}  ({page.stat().st_size / 1024:.0f} KB, single file, saved Kalshi run: {'yes' if snapshot else 'no'})")
    if args.multi:
        print(f"built {build_multi(Path('dist'))}  (multi-file layout)")


if __name__ == "__main__":
    main()
