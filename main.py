"""CLI: does the 200-day SMA act as a self-fulfilling support/resistance level?

Example:
    python main.py                          # ^GSPC 1950-present, 200d vs 174d
    python main.py --control 150 --horizons 1 3 5 10 --bootstrap 10000
    python main.py --synthetic              # offline smoke test on a null random walk
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

import data
import report
from events import EventConfig, build_baselines, detect_events
from plot import plot_era_comparison, plot_event_study
from stats import compare, era_expansion, event_counts, summarize


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Event-study backtest of SMA support/resistance reactivity "
        "(target SMA vs arbitrary control SMA, across market eras).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    src = p.add_argument_group("data")
    src.add_argument("--ticker", default="^GSPC", help="Yahoo Finance ticker")
    src.add_argument("--start", default="1950-01-01", help="first date (YYYY-MM-DD)")
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
    ev.add_argument("--refractory", type=int, default=10, help="de-clustering window (trading days)")
    ev.add_argument("--horizons", type=int, nargs="+", default=[1, 3, 5, 10])
    ev.add_argument("--breach-basis", choices=["close", "low"], default="close",
                    help="price used for the breach check (close, or low/high intraday)")

    st = p.add_argument_group("statistics & output")
    st.add_argument("--bootstrap", type=int, default=5000, help="bootstrap replications")
    st.add_argument("--seed", type=int, default=42)
    st.add_argument("--plot-horizon", type=int, default=None,
                    help="horizon shown in era_comparison.png (default: 5d, else the middle horizon)")
    st.add_argument("--outdir", default=".", help="where to write PNGs")
    st.add_argument("--save-events", action="store_true", help="also write events.csv to --outdir")
    args = p.parse_args(argv)

    if args.target == args.control:
        p.error("--target and --control must differ")
    if min(args.target, args.control) < 2:
        p.error("SMA windows must be >= 2")
    if not args.horizons or min(args.horizons) < 1:
        p.error("--horizons must be positive integers")
    args.horizons = sorted(set(args.horizons))
    if args.plot_horizon is None:
        args.plot_horizon = 5 if 5 in args.horizons else args.horizons[len(args.horizons) // 2]
    elif args.plot_horizon not in args.horizons:
        p.error("--plot-horizon must be one of --horizons")
    return args


def load(args: argparse.Namespace) -> pd.DataFrame:
    if args.synthetic:
        return data.generate_synthetic(args.start, args.end, seed=args.seed)
    if args.csv:
        return data.load_csv(args.csv)
    return data.load_prices(args.ticker, args.start, args.end, args.cache_dir, args.refresh)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        prices = load(args)
    except Exception as exc:  # network failure, bad ticker, bad CSV
        print(f"error: could not load price data: {exc}", file=sys.stderr)
        return 1
    if len(prices) < max(args.target, args.control) + 100:
        print("error: not enough history for the requested SMA windows", file=sys.stderr)
        return 1

    label = "synthetic random walk" if args.synthetic else (args.csv or args.ticker)
    print(
        f"Data: {label}, {len(prices):,} daily bars, "
        f"{prices.index[0].date()} -> {prices.index[-1].date()}"
    )

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
    events = pd.concat(frames)
    if events.empty or any(len(f) == 0 for f in frames):
        print("error: no events detected for at least one MA; widen --band or the date range",
              file=sys.stderr)
        return 1
    events = events.reset_index()

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
    report.print_notes(len(comp) + 2 * len(expansion))

    p1 = plot_event_study(events, args.target, args.control, pre, post, outdir / "event_study_car.png")
    p2 = plot_era_comparison(events, comp, args.target, args.control, args.plot_horizon,
                             outdir / "era_comparison.png")
    print(f"\nSaved: {p1}\nSaved: {p2}")
    if args.save_events:
        path = outdir / "events.csv"
        events.to_csv(path, index=False)
        print(f"Saved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
