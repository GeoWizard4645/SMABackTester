"""Browser-facing entry points for the Kalshi lab (called from the Pyodide worker).

``run_lab(params)`` does the whole study and returns JSON-safe dicts for the page to draw.
``run_code(code)`` executes user-edited Python in a persistent namespace, capturing stdout,
errors and matplotlib figures, so the page works as a small Python notebook.
"""

from __future__ import annotations

import base64
import contextlib
import io
import math
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from kalshi_lab import backtest, calibration, kalshi_data, stats

STATE: dict = {"raw": None, "frame": None, "params": None, "result": None, "trades": None}

DEFAULTS = {
    "series": "KXBTC15M", "source": "auto", "days": 7, "start": None, "end": None,
    "checkpoints": [14, 12, 10, 8, 6, 5, 4, 3, 2, 1], "entry_checkpoint": 5,
    "price_source": "trade", "spot_ref": "checkpoint", "min_price": 20, "max_price": 50,
    "bin_width": 10, "tails": False, "p_test": "twoprop", "hours": None, "weekdays": None,
    "contracts": 1, "fee_rate": 0.07, "capital": 1000, "seed": 0, "bias": 3.0, "upside_extra": 2.0,
    "noise": 2.0, "max_markets": 1500, "rules": ["r1", "r2", "r3"],
    "vol_window": 60, "vol_scale": None, "basis_adjust": True, "trend": 0.0,
    "custom": {"enabled": False, "side": "no", "direction": "", "min": 0, "max": 100},
}


def to_py(obj):
    """Recursively convert numpy/pandas values to JSON-safe Python (NaN/inf -> None)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (pd.Timestamp, np.datetime64, datetime)):
        return pd.Timestamp(obj).strftime("%Y-%m-%d %H:%M")
    if isinstance(obj, pd.DataFrame):
        return to_py(obj.to_dict("records"))
    if isinstance(obj, (pd.Series, np.ndarray, pd.Index)):
        return [to_py(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): to_py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_py(v) for v in obj]
    return str(obj)


def _num(p, key, lo, hi, integer=False):
    v = p.get(key, DEFAULTS.get(key))
    try:
        v = int(v) if integer else float(v)
    except (TypeError, ValueError):
        raise ValueError(f"'{key}' must be a number") from None
    if not lo <= v <= hi:
        raise ValueError(f"'{key}' must be between {lo} and {hi}")
    return v


def parse_params(raw: dict | None) -> dict:
    p = {**DEFAULTS, **(raw or {})}
    out = dict(p)
    if p["series"] not in kalshi_data.SERIES:
        raise ValueError(f"unknown series {p['series']!r}")
    if p["source"] not in ("auto", "live", "synthetic"):
        raise ValueError("source must be auto, live or synthetic")
    out["days"] = _num(p, "days", 0.25, 90)
    cps = sorted({int(c) for c in p["checkpoints"]}, reverse=True)
    if not cps or any(not 1 <= c <= 14 for c in cps):
        raise ValueError("checkpoints must be minutes between 1 and 14 before expiry")
    out["entry_checkpoint"] = int(p["entry_checkpoint"])
    if out["entry_checkpoint"] not in cps:
        cps = sorted({*cps, out["entry_checkpoint"]}, reverse=True)
    if not 1 <= out["entry_checkpoint"] <= 14:
        raise ValueError("entry checkpoint must be 1-14 minutes before expiry")
    out["checkpoints"] = cps
    for k, lo, hi, i in (("min_price", 0, 100, False), ("max_price", 0, 100, False), ("bin_width", 2, 50, True),
                         ("contracts", 1, 10000, True), ("fee_rate", 0, 1, False), ("capital", 1, 1e9, False),
                         ("seed", 0, 2**31 - 1, True), ("bias", -20, 20, False), ("upside_extra", -20, 20, False),
                         ("noise", 0, 20, False), ("max_markets", 50, 3000, True), ("vol_window", 10, 240, True),
                         ("trend", -20, 20, False)):
        out[k] = _num(p, k, lo, hi, i)
    if out["min_price"] > out["max_price"]:
        raise ValueError("min price must not exceed max price")
    if p["price_source"] not in ("trade", "mid", "executable"):
        raise ValueError("price_source must be trade, mid or executable")
    if p["spot_ref"] not in ("checkpoint", "open"):
        raise ValueError("spot_ref must be checkpoint or open")
    if p["p_test"] not in stats.P_TESTS:
        raise ValueError(f"p_test must be one of {stats.P_TESTS}")
    out["tails"] = bool(p["tails"])
    out["basis_adjust"] = bool(p["basis_adjust"])
    vs = p.get("vol_scale")
    if vs in (None, "", "auto"):
        out["vol_scale"] = None
    else:
        out["vol_scale"] = _num({"vol_scale": vs}, "vol_scale", 0.3, 3.0)
    if p.get("hours"):
        out["hours"] = (int(p["hours"][0]), int(p["hours"][1]))
        if not all(0 <= h <= 23 for h in out["hours"]):
            raise ValueError("hours must be 0-23 (UTC)")
    else:
        out["hours"] = None
    out["weekdays"] = [int(d) for d in p["weekdays"]] if p.get("weekdays") else None
    return out


def _dt(s):
    return datetime.fromisoformat(str(s).replace("Z", "")) if s else None


def build_rules(p: dict) -> list[backtest.Rule]:
    rules = backtest.default_rules(p["min_price"], p["max_price"])
    chosen = {"r1": rules[0], "r2": rules[1], "r3": rules[2]}
    out = [chosen[k] for k in p["rules"] if k in chosen]
    c = p["custom"]
    if c.get("enabled"):
        direction = c.get("direction") or None
        label = f"Custom: Buy {c.get('side', 'no').title()}" + (f" {direction}" if direction else "") + f" {c.get('min', 0):g}-{c.get('max', 100):g}¢"
        out.append(backtest.Rule(label, c.get("side", "no"), direction, float(c.get("min", 0)), float(c.get("max", 100))))
    return out


def run_lab(params: dict | None = None, progress=None) -> dict:
    """Run the full study with ``params`` and return JSON-safe results."""
    p = parse_params(params)
    if progress is not None:
        kalshi_data.configure(progress=progress)
    end = _dt(p["end"]) or datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    start = _dt(p["start"]) or end - timedelta(days=p["days"])
    raw = kalshi_data.load_contracts(p["series"], p["days"], end, start, p["checkpoints"], p["source"], p["seed"],
                                     p["bias"], p["upside_extra"], p["noise"], p["max_markets"],
                                     trend=p["trend"], vol_window=p["vol_window"])
    frame = kalshi_data.analysis_frame(raw, p["entry_checkpoint"], p["price_source"], p["spot_ref"], p["hours"], p["weekdays"],
                                       vol_scale=p["vol_scale"], basis_adjust=p["basis_adjust"])
    if frame.empty:
        raise ValueError("no contracts have a usable price at that checkpoint with these filters")
    tables = calibration.calibration_report(frame, width=p["bin_width"], tails=p["tails"], p_test=p["p_test"])
    have_fair = bool(frame["fair"].notna().any())
    fair_tabs = calibration.fair_report(frame, width=10, seed=p["seed"]) if have_fair else None
    rules = build_rules(p)
    trades = backtest.run_rules(frame, rules, price_source=p["price_source"], contracts=p["contracts"], fee_rate=p["fee_rate"])
    strategies = []
    for name, t in trades.items():
        m = stats.strategy_metrics(t, p["capital"])
        if len(t) >= 5:
            lo, hi = stats.day_cluster_bootstrap_mean(t["net"].to_numpy(), pd.to_datetime(t["time"]).dt.date.to_numpy(), 1500, p["seed"])
            m["net_cents_ci"] = [lo / p["contracts"], hi / p["contracts"]]
        strategies.append({"name": name, **m})
    equity = {}
    for name, t in trades.items():
        step = max(1, len(t) // 3000)
        equity[name] = {"t": to_py(t["time"].iloc[::step]), "cum": to_py(t["cum_net"].iloc[::step]),
                        "cum_edge": to_py(t["cum_edge"].iloc[::step])}

    notes = list(raw.attrs.get("notes", []))
    n_dir = frame["direction"].value_counts().to_dict()
    if n_dir.get("unknown", 0) == len(frame):
        notes.append("No spot prices, so the upside/downside split is empty.")
    if not have_fair:
        notes.append("No spot prices or volatility, so the trend-free fair-value benchmark is unavailable. Only the raw results are shown.")
    elif frame["fair"].isna().any():
        k = int(frame["fair"].isna().sum())
        notes.append(f"{k} contract{'s' if k != 1 else ''} at the start of the sample had too little price history for a volatility estimate and {'are' if k != 1 else 'is'} left out of the fair-value results.")
    if len(frame) < 300:
        notes.append(f"Only {len(frame)} contracts: most bins are very noisy. Try more days.")

    headline = None
    if have_fair:
        f = frame[frame["fair"].notna()]
        test = stats.cluster_mean_test(f["premium"].to_numpy(), pd.to_datetime(f["close_time"]).dt.date.to_numpy(), 2000, p["seed"])
        spots = raw["spot_open"].dropna()
        headline = {
            "n": int(len(f)), "mean_price": float(f["yes_price"].mean()), "mean_fair": float(100 * f["fair"].mean()),
            "yes_rate": float(100 * f["result"].mean()), "premium": test["mean"], "premium_lo": test["lo"],
            "premium_hi": test["hi"], "premium_p": test["p"],
            "luck_gap": float(100 * f["result"].mean() - 100 * f["fair"].mean()),
            "btc_change_pct": float(100 * (spots.iloc[-1] / spots.iloc[0] - 1)) if len(spots) > 1 else None,
            "vol_scale": float(f["vol_scale"].iloc[0]), "fair_shape": float(f["fair_shape"].iloc[0]),
            "vol_scale_auto": p["vol_scale"] is None,
        }
        # how well each probability predicted the outcomes (log-likelihood; higher is better)
        yv = f["result"].to_numpy(dtype=float)
        score = lambda q: float((yv * np.log(np.clip(q, 1e-4, 1 - 1e-4)) + (1 - yv) * np.log(1 - np.clip(q, 1e-4, 1 - 1e-4))).sum())
        headline["score_model"] = score(f["fair"].to_numpy(dtype=float))
        headline["score_market"] = score(f["yes_price"].to_numpy(dtype=float) / 100)
    result = {
        "summary": {
            "source": raw.attrs.get("source"), "series": p["series"], "markets": len(raw), "priced": len(frame),
            "start": raw["close_time"].min(), "end": raw["close_time"].max(), "entry_checkpoint": p["entry_checkpoint"],
            "price_source": p["price_source"], "spot_ref": p["spot_ref"], "directions": n_dir,
            "overall_yes_rate": float(frame["result"].mean()), "overall_avg_yes": float(frame["yes_price"].mean()),
            "notes": notes, "params": {k: v for k, v in p.items() if k != "custom"},
        },
        "calibration": tables,
        "headline": headline,
        "fair": fair_tabs,
        "asymmetry": stats.asymmetry_test(frame),
        "asymmetry_fair": stats.asymmetry_test(frame, measure="fair") if have_fair else None,
        "strategies": strategies,
        "equity": equity,
        "hourly": calibration.by_hour(frame),
        "contracts": frame[["ticker", "close_time", "strike", "result", "yes_price", "yes_bid", "yes_ask", "direction", "fair", "premium"]].tail(6000),
    }
    STATE.update(raw=raw, frame=frame, params=p, trades=trades, result=result)
    return to_py(result)


# ------------------------------------------------------------------ console ("Python notebook")
_NS: dict = {}


def _fresh_namespace() -> dict:
    import kalshi_lab

    ns = {"__name__": "__console__", "pd": pd, "np": np, "kalshi_data": kalshi_data, "calibration": calibration,
          "backtest": backtest, "kstats": stats, "STATE": STATE, "lab": sys.modules[__name__]}
    return ns


def reset_console() -> None:
    _NS.clear()
    _NS.update(_fresh_namespace())


def run_code(code: str) -> dict:
    """Execute ``code`` in the persistent console namespace.

    ``raw`` and ``frame`` always point at the data from the most recent run_lab call.
    """
    if not _NS:
        reset_console()
    _NS.update(raw=STATE["raw"], frame=STATE["frame"], params=STATE["params"], trades=STATE["trades"])
    os.environ["MPLBACKEND"] = "Agg"
    out, err = io.StringIO(), ""
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            exec(compile(code, "<console>", "exec"), _NS)
        except BaseException:  # noqa: BLE001 - show the user's traceback, hide our frames
            tb = traceback.format_exc().splitlines()
            keep = [l for i, l in enumerate(tb) if i == 0 or "<console>" in l or i >= len(tb) - 1 or (i > 0 and "<console>" in tb[i - 1])]
            err = "\n".join(keep)
    images = []
    if "matplotlib.pyplot" in sys.modules:
        plt = sys.modules["matplotlib.pyplot"]
        for num in plt.get_fignums():
            buf = io.BytesIO()
            plt.figure(num).savefig(buf, format="png", dpi=110, bbox_inches="tight")
            images.append(base64.b64encode(buf.getvalue()).decode())
        plt.close("all")
    return {"stdout": out.getvalue(), "error": err, "images": images}


EXAMPLES = {
    "1 · Sweep entry time: when is the overpricing biggest?": '''# Calibration gap and Buy-No result for every checkpoint you extracted.
rows = []
for m in params["checkpoints"]:
    f = kalshi_data.analysis_frame(raw, m, params["price_source"], params["spot_ref"])
    t = backtest.run_rule(f, backtest.Rule("No on all", "no"), params["price_source"], 1, params["fee_rate"])
    s = kstats.strategy_metrics(t)
    rows.append(dict(minutes_before_expiry=m, n=len(f), avg_yes=f.yes_price.mean(),
                     yes_rate_pct=100 * f.result.mean(), gap_pp=f.yes_price.mean() - 100 * f.result.mean(),
                     net_usd=s["net_profit"], roi_pct=s["roi_pct"]))
print(pd.DataFrame(rows).round(2).to_string(index=False))
''',
    "2 · Trend-free premium by hour of day (UTC)": '''# premium = Yes price minus model fair value, so BTC's trend and luck are out of it
g = frame.dropna(subset=["fair"]).groupby("hour").apply(lambda d: pd.Series({
    "n": len(d), "avg_price": d.yes_price.mean(), "avg_fair_pct": 100 * d.fair.mean(),
    "premium_c": d.premium.mean(), "raw_gap_pp": d.yes_price.mean() - 100 * d.result.mean()}), include_groups=False)
print(g.round(2).to_string())
''',
    "3 · Fees: how much of the edge do they eat?": '''for rate in [0, 0.0175, 0.035, 0.07]:       # none, maker-like, half, taker
    t = backtest.run_rule(frame, backtest.Rule("No on all", "no"), params["price_source"], 1, rate)
    s = kstats.strategy_metrics(t)
    print(f"fee rate {rate:<7} net ${s['net_profit']:>8.2f}   fees ${s['fees']:>7.2f}   ROI {s['roi_pct']:.2f}%")
print("\\nFee per contract at each price (cents):")
print({p: backtest.kalshi_fee_cents(p) for p in (5, 10, 25, 50, 75, 90, 95)})
''',
    "4 · Day-cluster bootstrap CI of the Buy-No edge": '''t = backtest.run_rule(frame, backtest.Rule("No on all", "no"), params["price_source"], 1, params["fee_rate"])
days = pd.to_datetime(t.time).dt.date.to_numpy()
lo, hi = kstats.day_cluster_bootstrap_mean(t.net.to_numpy(), days, 5000, seed=1)
print(f"mean net per contract: {t.net.mean():.2f}c   95% CI by day-bootstrap: [{lo:.2f}c, {hi:.2f}c]")
print("Edge is statistically distinguishable from zero" if lo > 0 or hi < 0 else "CI includes zero: no reliable edge")
''',
    "5 · Is the fair-value model itself calibrated?": '''# If this table is close to the diagonal, the benchmark (and so the premium) can be trusted.
tab = calibration.fair_table(frame, "all")
print(pd.DataFrame([r for r in tab["rows"] if r["count"]])[["bin", "count", "avg_fair", "realized_pct", "avg_price", "premium"]].round(1).to_string(index=False))
''',
    "6 · Matplotlib: calibration scatter": '''import matplotlib.pyplot as plt
cal = calibration.calibrate(frame, "all", width=5, lo=5, hi=95)
rows = [r for r in cal["rows"] if r["count"]]
plt.figure(figsize=(5.5, 5.5))
plt.plot([0, 100], [0, 100], "--", color="gray", label="fair value")
plt.errorbar([r["avg_yes"] for r in rows], [r["actual_pct"] for r in rows],
             yerr=[[r["actual_pct"] - r["ci_lo"] for r in rows], [r["ci_hi"] - r["actual_pct"] for r in rows]], fmt="o-", capsize=3, label="5¢ bins")
plt.xlabel("Yes price (¢)"); plt.ylabel("actual Yes rate (%)"); plt.legend(); plt.grid(alpha=.3)
''',
    "7 · Your own rule: Buy Yes on cheap upside strikes": '''rule = backtest.Rule("Buy Yes, upside, 10-30c", side="yes", direction="upside", min_price=10, max_price=30)
t = backtest.run_rule(frame, rule, params["price_source"], 1, params["fee_rate"])
print(kstats.strategy_metrics(t))
''',
}
