"""JSON dispatch layer used by the browser worker: one string in, one string out."""

from __future__ import annotations

import json
import traceback

import data
import service
from kalshi_lab import kalshi_data, web


def configure(proxy_base: str, progress=None) -> None:
    """Point every network call at the same-origin proxy (the browser cannot call APIs directly)."""
    base = proxy_base.rstrip("/")
    data.PROXY_BASE = base
    kalshi_data.configure(kalshi=f"{base}/kalshi", coinbase=f"{base}/coinbase", progress=progress)


def call(fn: str, payload: str) -> str:
    args = json.loads(payload) if payload else {}
    try:
        if fn == "analyze":
            out = service.analyze(args.get("config"))
        elif fn == "event_window":
            out = service.event_window(args.get("config") or {}, str(args["ticker"]), int(args["ma"]), str(args["date"]),
                                       str(args.get("direction", "support")), args.get("before", 40), args.get("after", 25))
        elif fn == "scan":
            out = service.scan(args.get("config") or {}, str(args["ticker"]), args.get("min", 20), args.get("max", 400),
                               args.get("step", 5))
        elif fn == "register_csv":
            out = {"ticker": data.register_upload(str(args["name"]), str(args["text"]))}
        elif fn == "lab_run":
            out = web.run_lab(args.get("params"))
        elif fn == "run_code":
            out = web.run_code(str(args.get("code", "")))
        elif fn == "reset_console":
            web.reset_console()
            out = {"ok": True}
        else:
            return json.dumps({"__error": f"unknown function {fn!r}"})
        return json.dumps(out)
    except (service.ConfigError, ValueError, kalshi_data.DataError, KeyError) as exc:
        return json.dumps({"__error": str(exc) or type(exc).__name__})
    except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the page
        return json.dumps({"__error": f"internal error: {exc}", "__trace": traceback.format_exc()[-1500:]})
