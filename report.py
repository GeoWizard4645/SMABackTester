"""ASCII console report."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from stats import ERA_ALL, ERA_DESC, ERA_ORDER

ERAS = ERA_ORDER + [ERA_ALL]


def format_table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], title: str | None = None
) -> str:
    """Render a boxed ASCII table. The first two columns are left-aligned."""
    cells = [[str(c) for c in r] for r in rows]
    widths = [
        max(len(str(h)), *(len(r[i]) for r in cells)) if cells else len(str(h))
        for i, h in enumerate(headers)
    ]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def line(vals: Sequence[str]) -> str:
        parts = [
            f" {v:<{w}} " if i < 2 else f" {v:>{w}} "
            for i, (v, w) in enumerate(zip(vals, widths))
        ]
        return "|" + "|".join(parts) + "|"

    out = []
    if title:
        out += ["", title]
    out += [sep, line(headers), sep]
    prev = None
    for r in cells:
        if prev is not None and r[0] != prev:
            out.append(sep)
        out.append(line(r))
        prev = r[0]
    out.append(sep)
    return "\n".join(out)


def _pct(x: float, d: int = 1) -> str:
    return "n/a" if pd.isna(x) else f"{100 * x:.{d}f}%"


def _spct(x: float, d: int = 2) -> str:
    return "n/a" if pd.isna(x) else f"{100 * x:+.{d}f}%"


def _p(x: float) -> str:
    if pd.isna(x):
        return "n/a"
    star = "**" if x < 0.01 else "*" if x < 0.05 else ""
    return f"{x:.4f}{star}"


def _era_label(era: str) -> str:
    return f"{era} ({ERA_DESC[era]})"


def print_event_counts(counts: pd.DataFrame) -> None:
    rows = [
        [f"{r.ma}d SMA", _era_label(r.era), r.total, r.support, r.resistance]
        for r in counts.itertuples()
    ]
    print(
        format_table(
            ["MA", "Era", "Events", "Support tests", "Resistance tests"],
            rows,
            "1. EVENTS DETECTED (isolated touches after 10-day de-clustering)",
        )
    )


def print_bounce_table(summary: pd.DataFrame, mas: Sequence[int], horizons: Sequence[int]) -> None:
    rows = []
    for ma in mas:
        for era in ERAS:
            s = summary[(summary.ma == ma) & (summary.era == era)].set_index("horizon")
            row = [f"{ma}d SMA", _era_label(era)]
            for k in horizons:
                r = s.loc[k]
                row.append(
                    f"{_pct(r.bounce_rate)} [{_pct(r.bounce_lo, 0)}-{_pct(r.bounce_hi, 0)}] n={int(r.n)}"
                )
            rows.append(row)
    print(
        format_table(
            ["MA", "Era"] + [f"{k}d bounce [95% CI]" for k in horizons],
            rows,
            "2. BOUNCE RATE  (support: higher close w/o breaching 1.5xATR below SMA; "
            "resistance mirrored; Wilson 95% CI)",
        )
    )


def print_car_table(summary: pd.DataFrame, mas: Sequence[int], horizons: Sequence[int]) -> None:
    rows = []
    for ma in mas:
        for era in ERAS:
            s = summary[(summary.ma == ma) & (summary.era == era)].set_index("horizon")
            row = [f"{ma}d SMA", _era_label(era)]
            for k in horizons:
                r = s.loc[k]
                row.append(f"{_spct(r.car_mean)} (sd {_pct(r.car_std, 2)})")
            rows.append(row)
    print(
        format_table(
            ["MA", "Era"] + [f"{k}d mean CAR (sd)" for k in horizons],
            rows,
            "3. DIRECTION-ADJUSTED FORWARD CAR vs. unconditional era return "
            "(positive = reacted as S/R predicts)",
        )
    )


def print_comparison(comp: pd.DataFrame, target: int, control: int) -> None:
    rows = []
    for era in ERAS:
        for metric, label in (("bounce", "bounce"), ("car", "CAR")):
            for r in comp[(comp.era == era) & (comp.metric == metric)].itertuples():
                fmt = _pct if metric == "bounce" else _spct
                rows.append(
                    [
                        _era_label(era),
                        f"{label} {r.horizon}d",
                        f"{r.n_target}/{r.n_control}",
                        fmt(r.mean_target),
                        fmt(r.mean_control),
                        fmt(r.diff),
                        _p(r.t_p),
                        _p(r.welch_p),
                        _p(r.mwu_p),
                        _p(r.boot_p),
                    ]
                )
    print(
        format_table(
            [
                "Era", "Metric", "n (tgt/ctl)", f"{target}d", f"{control}d",
                "Diff", "t-test p", "Welch p", "MWU p", "Boot p",
            ],
            rows,
            f"4. {target}d SMA vs {control}d CONTROL  (two-sided p; * <0.05, ** <0.01; "
            "Boot = year-cluster bootstrap)",
        )
    )


def print_range_expansion(
    events: pd.DataFrame, comp: pd.DataFrame, mas: Sequence[int], target: int, control: int
) -> None:
    rows = []
    for era in ERAS:
        c = comp[(comp.era == era) & (comp.metric == "tr_ratio")]
        p_txt = _p(c.mwu_p.iloc[0]) if len(c) else "n/a"
        for i, ma in enumerate(mas):
            sub = events[events.ma == ma]
            if era != ERA_ALL:
                sub = sub[sub.era == era]
            rows.append(
                [
                    _era_label(era),
                    f"{ma}d SMA",
                    len(sub),
                    f"{sub.atr_ratio.mean():.3f}" if len(sub) else "n/a",
                    f"{sub.tr_ratio.mean():.3f}" if len(sub) else "n/a",
                    f"{100 * sub.dist_pct.abs().mean():.2f}%" if len(sub) else "n/a",
                    p_txt if i == len(mas) - 1 else "",
                ]
            )
    print(
        format_table(
            ["Era", "MA", "Events", "ATR/ATR20", "TR/TR20", "|dist to MA|", f"MWU p (TR {target} vs {control})"],
            rows,
            "5. LOCAL VOLATILITY / RANGE EXPANSION on event day (ratio to prior-20-day mean; 1.0 = normal)",
        )
    )


def print_expansion(exp: pd.DataFrame, target: int, control: int) -> None:
    rows = []
    for metric, label in (("bounce", "bounce"), ("car", "CAR")):
        fmt = _pct if metric == "bounce" else _spct
        for r in exp[exp.metric == metric].itertuples():
            ci = f"[{fmt(r.boot_lo)}, {fmt(r.boot_hi)}]"
            rows.append(
                [
                    label,
                    f"{r.horizon}d",
                    fmt(r.diff_base),
                    fmt(r.diff_late),
                    fmt(r.did),
                    ci,
                    _p(r.boot_p),
                    fmt(r.reg_coef),
                    _p(r.reg_p),
                ]
            )
    print(
        format_table(
            [
                "Metric", "Horizon", "Diff Era 1", "Diff Era 3", "Era3-Era1",
                "Boot 95% CI", "Boot p", "OLS coef", "OLS p (clustered)",
            ],
            rows,
            f"6. HAS THE ({target}d - {control}d) GAP EXPANDED IN ERA 3 vs ERA 1?  (difference-in-differences)",
        )
    )


def print_cross_asset(rows: Sequence[dict], target: int, control: int, horizon: int) -> None:
    """One-line-per-asset roll-up (full sample, ``horizon``-day metrics)."""
    table = []
    for r in rows:
        table.append(
            [
                r["ticker"],
                r["span"],
                f"{r['n_target']}/{r['n_control']}",
                _pct(r["bounce_diff"]),
                _p(r["bounce_p"]),
                _spct(r["car_diff"]),
                _p(r["car_p"]),
                _p(r["did_car_p"]),
            ]
        )
    print(
        format_table(
            [
                "Asset", "History", "Events (tgt/ctl)", f"Bounce gap {horizon}d",
                "Boot p", f"CAR gap {horizon}d", "Boot p", "Era3-Era1 CAR p",
            ],
            table,
            f"CROSS-ASSET SUMMARY: {target}d minus {control}d, full sample "
            "(positive gap = target reacts more; Boot = year-cluster bootstrap)",
        )
    )


def print_notes(n_tests: int, ticker: str = "^GSPC", n_years: int = 99) -> None:
    print(
        "\nNotes:\n"
        "  * t / Welch / MWU p-values assume the two event samples are independent. They are not:\n"
        "    both SMAs are tested against the same price path and share many events, which makes\n"
        "    these tests overly conservative (~1% false-positive rate at a nominal 5% on simulated\n"
        "    null data). The year-cluster bootstrap and clustered OLS account for this; the\n"
        "    bootstrap runs slightly liberal (5-9% on null data) when an era has few years.\n"
        f"  * ~{n_tests} tests are reported with no multiple-comparison correction; expect a few\n"
        "    p<0.05 by chance alone. Treat isolated hits with suspicion.\n"
        "  * Bounce rates sit above 50% for support tests partly because of equity drift; only\n"
        "    the target-minus-control differences speak to the S/R hypothesis.",
        end="",
    )
    if n_years < 20:
        print(
            f"\n  * WARNING: only {n_years} calendar years of history. Each era then has just a few\n"
            "    year-clusters, so the cluster bootstrap and clustered OLS are unreliable and can\n"
            "    report spuriously small p-values. Treat every result here as exploratory.",
            end="",
        )
    if ticker == "^GSPC":
        print(
            "\n  * ^GSPC before ~1962 has no true intraday High/Low (they equal Close), so ATR and\n"
            "    touch detection in Era 1 are close-to-close approximations.",
            end="",
        )
    if ticker.upper().endswith(("-USD", "-USDT", "-EUR", "-BTC")):
        print(
            "\n  * This looks like a 24/7 market: every calendar day is a bar, so an N-day SMA\n"
            "    spans N calendar days (a 200d SMA is ~29 weeks, not ~40) and 'trading days' in\n"
            "    the horizons and de-clustering window are calendar days.",
            end="",
        )
    print()
