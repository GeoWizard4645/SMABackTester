"""Matplotlib charts for the command-line run (the web app draws its own with Plotly)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


COLORS = {"all": "#2a78d6", "upside": "#eb6834", "downside": "#1baf7a"}


def calibration_chart(tables: dict, path: str | Path, title: str = "Kalshi 15-minute contracts: calibration") -> Path:
    """Yes price vs realised Yes rate for each split, against the 45-degree fair-value line."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    ax.plot([0, 100], [0, 100], color="#85847f", linestyle="--", linewidth=1.3, label="Fair value (45° line)")
    for split, t in tables.items():
        rows = [r for r in t["rows"] if r["count"]]
        if not rows:
            continue
        x = np.array([r["avg_yes"] for r in rows])
        y = np.array([r["actual_pct"] for r in rows])
        lo = y - np.array([r["ci_lo"] for r in rows])
        hi = np.array([r["ci_hi"] for r in rows]) - y
        ax.errorbar(x, y, yerr=[lo, hi], fmt="o-", color=COLORS.get(split), capsize=3, linewidth=1.8,
                    markersize=6, label=f"{split.title()} strikes (n={sum(r['count'] for r in rows)})")
    ax.set_xlim(0, 100), ax.set_ylim(0, 100)
    ax.set_xlabel("Average Yes price (implied probability, ¢)")
    ax.set_ylabel("Actual Yes win rate (%)")
    ax.set_title(title + "\nbelow the line = Yes overpriced", fontsize=11)
    ax.grid(color="#e2e1dc"), ax.legend(loc="upper left", frameon=False)
    ax.set_aspect("equal")
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def equity_curve(trades_by_rule: dict, path: str | Path, title: str = "Cumulative net PnL after fees") -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 5.2))
    palette = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
    for i, (name, t) in enumerate(trades_by_rule.items()):
        if len(t):
            ax.plot(t["time"], t["cum_net"], color=palette[i % len(palette)], linewidth=1.8, label=f"{name} ({len(t)} trades)")
    ax.axhline(0, color="#85847f", linewidth=1)
    ax.set_ylabel("Cumulative net PnL ($)")
    ax.set_title(title)
    ax.grid(color="#e2e1dc"), ax.legend(frameon=False, fontsize=8, loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path
