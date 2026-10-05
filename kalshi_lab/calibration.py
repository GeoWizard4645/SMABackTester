"""Is "Yes" overpriced? Calibration of Yes prices against realised outcomes."""

from __future__ import annotations

import numpy as np
import pandas as pd

from kalshi_lab import stats

SPLITS = ("all", "upside", "downside")


def bin_edges(width: int = 10, lo: int = 10, hi: int = 90, tails: bool = False) -> list[int]:
    edges = list(range(lo, hi + 1, width))
    if edges[-1] != hi:
        edges.append(hi)
    return ([0] + edges + [100]) if tails else edges


def _label(a: int, b: int) -> str:
    return f"{max(a, 1)}-{min(b, 99)}¢"


def calibrate(frame: pd.DataFrame, split: str = "all", width: int = 10, lo: int = 10, hi: int = 90,
              tails: bool = False, p_test: str = "twoprop", conf: float = 0.95) -> dict:
    """Calibration table for one split.

    For each Yes-price bin: contract count, average Yes price (the implied probability, in cents),
    realised Yes rate, ``gap = implied - realised`` in percentage points (positive = Yes is
    overpriced), a p-value for H0 'calibrated', and a Wilson CI for the realised rate.
    """
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    f = frame if split == "all" else frame[frame["direction"] == split]
    edges = bin_edges(width, lo, hi, tails)
    price = f["yes_price"].to_numpy(dtype=float)
    out = f["result"].to_numpy(dtype=float)
    rows = []
    for i in range(len(edges) - 1):
        a, b = edges[i], edges[i + 1]
        if i == 0 and tails and a == 0:
            mask = price < b
        elif i == len(edges) - 2 and tails and b == 100:
            mask = price > a
        elif b == hi:
            mask = (price >= a) & (price <= b)
        else:
            mask = (price >= a) & (price < b)
        rows.append(_row(_label(a, b), a, b, price[mask], out[mask], p_test, conf))
    in_range = (price >= lo) & (price <= hi) if not tails else np.ones(len(price), dtype=bool)
    overall = _row("ALL", lo, hi, price[in_range], out[in_range], p_test, conf)
    return {"split": split, "rows": rows, "overall": overall, "p_test": p_test}


def _row(label: str, a: int, b: int, price: np.ndarray, out: np.ndarray, p_test: str, conf: float) -> dict:
    n = len(out)
    if n == 0:
        return {"bin": label, "lo": a, "hi": b, "count": 0, "avg_yes": None, "actual_pct": None, "gap": None,
                "p_value": None, "ci_lo": None, "ci_hi": None}
    wins = float(out.sum())
    ci_lo, ci_hi = stats.wilson_ci(wins, n, conf)
    return {
        "bin": label, "lo": a, "hi": b, "count": n,
        "avg_yes": float(price.mean()), "actual_pct": 100 * wins / n,
        "gap": float(price.mean() - 100 * wins / n),
        "p_value": stats.implied_vs_realized_p(price, out, p_test) if n >= 2 else None,
        "ci_lo": 100 * ci_lo, "ci_hi": 100 * ci_hi,
    }


def by_hour(frame: pd.DataFrame) -> list[dict]:
    """Overpricing gap by UTC hour of expiry (pooled over all price levels)."""
    rows = []
    for hr, g in frame.groupby("hour"):
        n = len(g)
        rows.append({"hour": int(hr), "count": n, "avg_yes": float(g["yes_price"].mean()),
                     "actual_pct": float(100 * g["result"].mean()),
                     "gap": float(g["yes_price"].mean() - 100 * g["result"].mean())})
    return rows


def calibration_report(frame: pd.DataFrame, **kw) -> dict[str, dict]:
    """The three standard splits: all / upside / downside strikes."""
    return {s: calibrate(frame, s, **kw) for s in SPLITS}
