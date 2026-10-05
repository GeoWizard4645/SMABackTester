"""Publication-quality figures: event-study trajectories and era comparisons."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from events import cum_col  # noqa: E402
from stats import ERA_ALL, ERA_DESC, ERA_ORDER, wilson_ci, mean_ci  # noqa: E402

# Validated adjacent-pair categorical slots 1 and 2 (blue, orange) of the reference palette.
COLOR_TARGET = "#2a78d6"
COLOR_CONTROL = "#eb6834"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
DPI = 300


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "text.color": INK,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.axisbelow": True,
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "legend.frameon": False,
        }
    )


def _color(ma: int, target: int) -> str:
    return COLOR_TARGET if ma == target else COLOR_CONTROL


def _path_stats(sub: pd.DataFrame, offsets: Sequence[int], signed: bool) -> tuple[np.ndarray, np.ndarray]:
    m = sub[[cum_col(j) for j in offsets]].to_numpy(dtype=float)
    if signed:
        m = m * sub["sign"].to_numpy()[:, None]
    mean = np.nanmean(m, axis=0)
    cnt = np.sum(~np.isnan(m), axis=0)
    with np.errstate(all="ignore"):
        se = np.nanstd(m, axis=0, ddof=1) / np.sqrt(cnt)
    return mean, se


def plot_event_study(
    events: pd.DataFrame,
    target: int,
    control: int,
    pre: int,
    post: int,
    path: str | Path,
) -> Path:
    """event_study_car.png: mean abnormal cumulative return from t-pre to t+post."""
    _style()
    offsets = list(range(-pre, post + 1))
    panels = [
        ("Support tests (approach from above)", "support", False),
        ("Resistance tests (approach from below)", "resistance", False),
        ("Pooled, direction-adjusted", None, True),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), sharex=True)
    for ax, (title, direction, signed) in zip(axes, panels):
        for ma in (target, control):
            sub = events[events["ma"] == ma]
            if direction:
                sub = sub[sub["direction"] == direction]
            if len(sub) < 2:
                continue
            mean, se = _path_stats(sub, offsets, signed)
            col = _color(ma, target)
            ax.fill_between(offsets, 100 * (mean - 1.96 * se), 100 * (mean + 1.96 * se),
                            color=col, alpha=0.15, linewidth=0)
            ax.plot(offsets, 100 * mean, color=col, linewidth=2, marker="o", markersize=4,
                    label=f"{ma}d SMA (n={len(sub)})")
        ax.axvline(0, color=INK_2, linewidth=1, linestyle="--")
        ax.axhline(0, color=INK_2, linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel("Trading days relative to touch (t = 0)")
        ax.set_xticks(offsets[:: max(1, len(offsets) // 8)])
        ax.legend(loc="best")
    axes[0].set_ylabel(f"Abnormal cumulative return from t-{pre} (%)")
    fig.suptitle(
        f"Event study around {target}d vs {control}d SMA touches  "
        "(abnormal = minus unconditional era return; bands = 95% CI of the mean; "
        "positive in panel 3 = reaction consistent with S/R)",
        x=0.01, ha="left", fontsize=10, color=INK_2,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path = Path(path)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def plot_era_comparison(
    events: pd.DataFrame,
    comp: pd.DataFrame,
    target: int,
    control: int,
    horizon: int,
    path: str | Path,
) -> Path:
    """era_comparison.png: bounce rate and CAR by era, plus the target-minus-control gap."""
    _style()
    eras = ERA_ORDER
    x = np.arange(len(eras))
    w = 0.36
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    (ax_b, ax_c), (ax_db, ax_dc) = axes

    for off, ma in ((-w / 2, target), (w / 2, control)):
        col = _color(ma, target)
        b_val, b_err, c_val, c_err = [], [], [], []
        for era in eras:
            sub = events[(events["ma"] == ma) & (events["era"] == era)]
            b = sub[f"bounce_{horizon}"].dropna().to_numpy()
            c = sub[f"car_{horizon}"].dropna().to_numpy()
            lo, hi = wilson_ci(b.sum(), len(b))
            clo, chi = mean_ci(c)
            bm = b.mean() if len(b) else np.nan
            cm = c.mean() if len(c) else np.nan
            b_val.append(100 * bm)
            b_err.append([100 * (bm - lo), 100 * (hi - bm)] if len(b) else [np.nan, np.nan])
            c_val.append(100 * cm)
            c_err.append([100 * (cm - clo), 100 * (chi - cm)] if len(c) > 1 else [np.nan, np.nan])
        kw = dict(width=w, color=col, edgecolor=SURFACE, linewidth=1.5, label=f"{ma}d SMA")
        ax_b.bar(x + off, b_val, yerr=np.array(b_err).T, error_kw=dict(ecolor=INK_2, lw=1, capsize=3), **kw)
        ax_c.bar(x + off, c_val, yerr=np.array(c_err).T, error_kw=dict(ecolor=INK_2, lw=1, capsize=3), **kw)

    ax_b.axhline(50, color=INK_2, linewidth=0.8, linestyle="--")
    ax_b.set_ylabel("Bounce rate (%)")
    ax_b.set_title(f"Bounce rate at {horizon}d (Wilson 95% CI)")
    ax_c.axhline(0, color=INK_2, linewidth=0.8)
    ax_c.set_ylabel("Mean direction-adjusted CAR (%)")
    ax_c.set_title(f"Forward CAR at {horizon}d (95% CI of the mean)")

    # Target - control gap with bootstrap CI.
    for ax, metric, ylabel, title in (
        (ax_db, "bounce", "Bounce-rate gap (pp)", f"{target}d minus {control}d: bounce rate at {horizon}d"),
        (ax_dc, "car", "CAR gap (pp)", f"{target}d minus {control}d: CAR at {horizon}d"),
    ):
        c = comp[(comp.metric == metric) & (comp.horizon == horizon)].set_index("era")
        vals = [100 * c.loc[e, "diff"] if e in c.index else np.nan for e in eras]
        lo = [100 * c.loc[e, "boot_lo"] if e in c.index else np.nan for e in eras]
        hi = [100 * c.loc[e, "boot_hi"] if e in c.index else np.nan for e in eras]
        err = np.array([np.array(vals) - np.array(lo), np.array(hi) - np.array(vals)])
        ax.bar(x, vals, width=0.5, color=COLOR_TARGET, edgecolor=SURFACE, linewidth=1.5,
               yerr=err, error_kw=dict(ecolor=INK_2, lw=1, capsize=3))
        ax.axhline(0, color=INK_2, linewidth=0.8)
        ax.set_ylabel(ylabel)
        ax.set_title(title + " (year-cluster bootstrap 95% CI)")

    for ax in axes.ravel():
        ax.set_xticks(x)
        ax.set_xticklabels([f"{e}\n{ERA_DESC[e]}" for e in eras])
    for ax in (ax_b, ax_c):
        ax.legend(loc="best")
    fig.suptitle(
        f"Reactivity by market era: {target}d SMA vs {control}d control SMA",
        x=0.01, ha="left", fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path = Path(path)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path
