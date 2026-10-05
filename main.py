"""CLI: does the 200-day SMA act as a self-fulfilling support/resistance level?

Example:
    python main.py                              # ^GSPC 1950-present, 200d vs 174d
    python main.py --ticker BTC-USD ETH-USD     # several assets, one output folder each
    python main.py --ticker AAPL --control 150 --bootstrap 10000
    python main.py --synthetic                  # offline smoke test on a null random walk
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

import data
import report
from events import EventConfig, build_baselines, detect_events
from plot import plot_era_comparison, plot_event_study
from stats import (
    ERA_ALL,
    ERA_DESC,
    ERA_ORDER,
    auto_era_bounds,
    compare,
    configure_eras,
    era_expansion,
    event_counts,
    summarize,
)

DEFAULT_ERAS = [1990, 2007]
# The default S&P-style eras need a reasonable pre-1991 history to be meaningful.
DEFAULT_ERAS_MAX_FIRST_YEAR = 1980


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Event-study backtest of SMA support/resistance reactivity "
        "(target SMA vs arbitrary control SMA, across market eras). Works with any "
        "Yahoo Finance symbol: indices, stocks, ETFs, crypto (BTC-USD, ETH-USD, ...).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    src = p.add_argument_group("data")
    src.add_argument("--ticker", nargs="+", default=["^GSPC"],
                     help="one or more Yahoo Finance tickers, e.g. BTC-USD ETH-USD AAPL NVDA")
    src.add_argument("--start", default="1950-01-01",
                     help="first date (YYYY-MM-DD); earlier than the asset's history is fine")
    src.add_argument("--end", default=None, help="last date (YYYY-MM-DD), default today")
    src.add_argument("--cache-dir", default=".cache", help="directory for cached downloads")
    src.add_argument("--refresh", action="store_true", help="ignore the cache and re-download")
    src.add_argument("--csv", default=None, help="read OHLC from this CSV instead of downloading")
    src.add_argument("--synthetic", action="store_true",
                     help="use a simulated no-effect random walk (offline smoke test)")

    ev = p.add_argument_group("event definition")
    ev.add_argument("--target", type=int, default=200, help="target SMA window")
    ev.add_argument("--control", type=int, default=174, help="control SMA window (any integer N)")
    ev.add_argument("--atr-window", type=int, default=14)
    ev.add_argument("--band", type=float, default=0.5, help="touch band half-width in ATRs")
    ev.add_argument("--breach", type=float, default=1.5, help="bounce-failure distance in ATRs")
    ev.add_argument("--approach", type=int, default=5, help="prior closes required on one side")
    ev.add_argument("--refractory", type=int, default=10, help="de-clustering window (bars)")
    ev.add_argument("--horizons", type=int, nargs="+", default=[1, 3, 5, 10])
    ev.add_argument("--breach-basis", choices=["close", "low"], default="close",
                    help="price used for the breach check (close, or low/high intraday)")

    st = p.add_argument_group("statistics & output")
    st.add_argument("--era-years", type=int, nargs="+", metavar="YEAR", default=None,
                    help="last calendar year of each era except the final one, e.g. '1990 2007' "
                    "gives three eras; any number is allowed. Default: 1990 2007 when the data "
                    "starts by 1980, otherwise the history is split into equal thirds")
    st.add_argument("--bootstrap", type=int, default=5000, help="bootstrap replications")
    st.add_argument("--seed", type=int, default=42)
    st.add_argument("--plot-horizon", type=int, default=None,
                    help="horizon shown in era_comparison.png (default: 5d, else the middle horizon)")
    st.add_argument("--outdir", default=".",
                    help="where to write PNGs (a sub-folder per ticker when several are given)")
    st.add_argument("--save-events", action="store_true", help="also write events.csv to the output folder")
    args = p.parse_args(argv)

    if args.target == args.control:
        p.error("--target and --control must differ")
    if min(args.target, args.control) < 2:
        p.error("SMA windows must be >= 2")
    if not args.horizons or min(args.horizons) < 1:
        p.error("--horizons must be positive integers")
    if args.csv and len(args.ticker) > 1:
        p.error("--csv holds a single series; give at most one --ticker label with it")
    args.horizons = sorted(set(args.horizons))
    if args.plot_horizon is None:
        args.plot_horizon = 5 if 5 in args.horizons else args.horizons[len(args.horizons) // 2]
    elif args.plot_horizon not in args.horizons:
        p.error("--plot-horizon must be one of --horizons")
    args.ticker = list(dict.fromkeys(t.strip() for t in args.ticker))  # de-duplicate, keep order
    return args


def load(args: argparse.Namespace, ticker: str) -> pd.DataFrame:
    if args.synthetic:
        return data.generate_synthetic(args.start, args.end, seed=args.seed)
    if args.csv:
        return data.load_csv(args.csv)
    return data.load_prices(ticker, args.start, args.end, args.cache_dir, args.refresh)


def setup_eras(args: argparse.Namespace, prices: pd.DataFrame) -> str:
    """Choose era boundaries for this asset; returns a human-readable note."""
    first, last = prices.index[0].year, prices.index[-1].year
    if args.era_years:
        ends = args.era_years
        how = "user-specified"
    elif first <= DEFAULT_ERAS_MAX_FIRST_YEAR:
        ends = DEFAULT_ERAS
        how = "default regimes"
    else:
        ends = auto_era_bounds(prices.index)
        how = "history split into equal thirds"
    configure_eras(ends, first, last, open_ended=args.end is None)
    return f"Eras ({how}): " + ", ".join(f"{e} {ERA_DESC[e]}" for e in ERA_ORDER)


def run_one(args: argparse.Namespace, ticker: str, outdir: Path) -> dict | None:
    """Full analysis for one asset. Returns a summary row, or None on failure."""
    try:
        prices = load(args, ticker)
    except Exception as exc:  # network failure, bad ticker, bad CSV
        print(f"error [{ticker}]: could not load price data: {exc}", file=sys.stderr)
        return None
    if len(prices) < max(args.target, args.control) + 100:
        print(f"error [{ticker}]: only {len(prices)} bars, not enough for the requested SMA windows",
              file=sys.stderr)
        return None
    try:
        era_note = setup_eras(args, prices)
    except ValueError as exc:
        print(f"error [{ticker}]: {exc}", file=sys.stderr)
        return None

    label = "synthetic random walk" if args.synthetic else (args.csv or ticker)
    span = f"{prices.index[0].year}-{prices.index[-1].year}"
    print(f"\n{'=' * 100}\nAsset: {label}")
    print(
        f"Data: {len(prices):,} daily bars, "
        f"{prices.index[0].date()} -> {prices.index[-1].date()}"
    )
    print(era_note)

    horizons = tuple(args.horizons)
    pre, post = 5, 10
    baselines = build_baselines(prices["Close"], horizons, pre, post)
    mas = [args.target, args.control]
    frames = []
    for ma in mas:
        cfg = EventConfig(
            ma_window=ma,
            atr_window=args.atr_window,
            band_mult=args.band,
            breach_mult=args.breach,
            approach_days=args.approach,
            refractory_days=args.refractory,
            horizons=horizons,
            pre=pre,
            post=post,
            breach_basis=args.breach_basis,
        )
        frames.append(detect_events(prices, cfg, baselines))
    if any(len(f) == 0 for f in frames):
        print(f"error [{ticker}]: no events detected for at least one MA; "
              "widen --band or the date range", file=sys.stderr)
        return None
    events = pd.concat(frames).reset_index()

    counts = event_counts(events, mas)
    summary = summarize(events, mas, horizons)
    comp = compare(events, args.target, args.control, horizons, args.bootstrap, args.seed)
    expansion = era_expansion(events, args.target, args.control, horizons, args.bootstrap, args.seed)

    report.print_event_counts(counts)
    report.print_bounce_table(summary, mas, horizons)
    report.print_car_table(summary, mas, horizons)
    report.print_comparison(comp, args.target, args.control)
    report.print_range_expansion(events, comp, mas, args.target, args.control)
    report.print_expansion(expansion, args.target, args.control)
    report.print_notes(len(comp) + 2 * len(expansion), label,
                       prices.index[-1].year - prices.index[0].year + 1)

    outdir.mkdir(parents=True, exist_ok=True)
    p1 = plot_event_study(events, args.target, args.control, pre, post, outdir / "event_study_car.png")
    p2 = plot_era_comparison(events, comp, args.target, args.control, args.plot_horizon,
                             outdir / "era_comparison.png")
    print(f"\nSaved: {p1}\nSaved: {p2}")
    if args.save_events:
        path = outdir / "events.csv"
        events.to_csv(path, index=False)
        print(f"Saved: {path}")

    h = args.plot_horizon
    full = comp[(comp.era == ERA_ALL) & (comp.horizon == h)].set_index("metric")
    did = expansion[(expansion.metric == "car") & (expansion.horizon == h)]
    return {
        "ticker": label,
        "span": span,
        "n_target": int((events.ma == args.target).sum()),
        "n_control": int((events.ma == args.control).sum()),
        "bounce_diff": full.loc["bounce", "diff"],
        "bounce_p": full.loc["bounce", "boot_p"],
        "car_diff": full.loc["car", "diff"],
        "car_p": full.loc["car", "boot_p"],
        "did_car_p": did["boot_p"].iloc[0] if len(did) else float("nan"),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base = Path(args.outdir)
    tickers = ["synthetic"] if args.synthetic else args.ticker
    multi = len(tickers) > 1

    rows = []
    for t in tickers:
        out = base / re.sub(r"[^A-Za-z0-9_.-]+", "_", t) if multi else base
        row = run_one(args, t, out)
        if row is not None:
            rows.append(row)

    if not rows:
        return 1
    if multi:
        print(f"\n{'=' * 100}")
        report.print_cross_asset(rows, args.target, args.control, args.plot_horizon)
        print("Per-asset charts are in sub-folders of", base)
    return 0 if len(rows) == len(tickers) else 1


if __name__ == "__main__":
    sys.exit(main())
