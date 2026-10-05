"""Build the static site for Cloudflare (or any static host).

    python build_static.py                 # -> dist/FinanceProjectTests/  (+ dist/cloudflare/)
    python build_static.py --out site --folder FinanceProjectTests

The output folder is self-contained: index.html, static/ (css, js, meta.json), py/ (the Python the
browser runs). Every URL is relative, so it works under any sub-path. Copy the folder into your
website, then deploy cloudflare/worker.js as the data proxy (see README).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import appmeta
import service
from kalshi_lab import kalshi_data, web

ROOT = Path(__file__).resolve().parent


def write_meta(dest: Path) -> None:
    meta = {
        "presets": appmeta.PRESETS,
        "defaults": service.DEFAULTS,
        "limits": service.LIMITS,
        "kalshi": {
            "defaults": {**web.DEFAULTS, "fee_choice": "taker", "fee_custom": 0.07, "rules": ["r1", "r2", "r3"]},
            "series": {k: v[1] for k, v in kalshi_data.SERIES.items()},
            "examples": web.EXAMPLES,
        },
    }
    dest.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")


def build(out: Path, folder: str) -> Path:
    site = out / folder
    if site.exists():
        shutil.rmtree(site)
    (site / "static").mkdir(parents=True)
    # page + assets (index.html lives at the folder root; everything else under static/)
    shutil.copy(ROOT / "static" / "index.html", site / "index.html")
    for item in ("style.css", "method.html"):
        shutil.copy(ROOT / "static" / item, site / "static" / item)
    shutil.copytree(ROOT / "static" / "js", site / "static" / "js")
    write_meta(site / "static" / "meta.json")
    # python sources for the in-browser runtime
    for rel in appmeta.PY_FILES:
        dest = site / "py" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, dest)
    (site / "py" / "manifest.json").write_text(json.dumps({"files": appmeta.PY_FILES}), encoding="utf-8")
    # worker for the data proxy
    shutil.copytree(ROOT / "cloudflare", out / "cloudflare", dirs_exist_ok=True)
    # alternative: the same proxy as a Cloudflare Pages Function (drop `functions/` into the Pages project root)
    fn_dir = out / "functions" / folder / "api" / "proxy"
    fn_dir.mkdir(parents=True, exist_ok=True)
    src = (ROOT / "cloudflare" / "worker.js").read_text(encoding="utf-8").replace(
        'const BASE = "/FinanceProjectTests/api/proxy";', f'const BASE = "/{folder}/api/proxy";')
    (fn_dir / "_proxy.js").write_text(src, encoding="utf-8")
    (fn_dir / "[[path]].js").write_text(
        'import { handle } from "./_proxy.js";\n\nexport const onRequest = ({ request, waitUntil }) => handle(request, { waitUntil });\n',
        encoding="utf-8")
    return site


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--folder", default="FinanceProjectTests")
    ap.add_argument("--meta-only", action="store_true", help="only refresh static/meta.json (used by the local Flask server)")
    args = ap.parse_args()
    if args.meta_only:
        write_meta(ROOT / "static" / "meta.json")
        print("wrote static/meta.json")
        return
    write_meta(ROOT / "static" / "meta.json")
    site = build(Path(args.out), args.folder)
    n = sum(1 for p in site.rglob("*") if p.is_file())
    print(f"built {site} ({n} files)")


if __name__ == "__main__":
    main()
