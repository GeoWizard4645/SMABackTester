"""CLI: do retail traders overprice 'Yes' on Kalshi's 15-minute crypto contracts?

    python kalshi_lab/main.py                                   # live data (falls back to synthetic)
    python kalshi_lab/main.py --entry-checkpoint 5m --min-price 20 --max-price 50
    python kalshi_lab/main.py --source synthetic --bias 0       # a perfectly calibrated null
    python kalshi_lab/main.py --series KXETH15M --days 14 --price-source executable
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kalshi_lab import backtest, calibration, kalshi_data, plot, stats  # noqa: E402


def minutes(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*m?(?:in)?\s*", text)
    if not m:
        raise argparse.ArgumentTypeError(f"expected minutes like 5m or 5, got {text!r}")
    return int(m.group(1))


def table(headers, rows, title=None) -> str:
    cells = [[str(c) for c in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]
    sep = "+" + "+".join("-" * (x + 2) for x in w) + "+"
    line = lambda v: "|" + "|".join(f" {c:>{w[i]}} " if i else f" {c:<{w[i]}} " for i, c in enumerate(v)) + "|"  # noqa: E731
    out = ([ "", title] if title else []) + [sep, line(headers), sep] + [line(r) for r in cells] + [sep]
    return "\n".join(out)


def _p(x):
    return "n/a" if x is None or x != x else (f"{x:.4f}" + ("**" if x < 0.01 else "*" if x < 0.05 else ""))


def format_calibration(tables: dict) -> str:
    out = []
    for split, t in tables.items():
        rows = [[r["bin"], r["count"], "n/a" if r["avg_yes"] is None else f"{r['avg_yes']:.1f}¢",
                 "n/a" if r["actual_pct"] is None else f"{r['actual_pct']:.1f}%",
                 "n/a" if r["gap"] is None else f"{r['gap']:+.1f} pp", _p(r["p_value"])]
                for r in t["rows"] + [t["overall"]]]
        out.append(table(["Price Bin", "Count", "Avg Yes Price", "Actual Yes Win %", "Overpricing Gap", "p-value"], rows,
                         f"TABLE 1 [{split.upper()} strikes]: calibration (gap = implied - realised; positive = Yes overpriced; p-test: {t['p_test']})"))
    return "\n".join(out)


def format_strategies(results: dict) -> str:
    rows = []
    for name, m in results.items():
        f = lambda v, fmt: "n/a" if v is None else format(v, fmt)  # noqa: E731
        rows.append([name, m["trades"], f(None if m["win_rate"] is None else 100 * m["win_rate"], ".1f") + "%",
                     f"${m['gross_profit']:,.2f}" if m["gross_profit"] is not None else "n/a",
                     f"${m['fees']:,.2f}" if m["fees"] is not None else "n/a",
                     f"${m['net_profit']:,.2f}" if m["net_profit"] is not None else "n/a",
                     f(m["roi_pct"], ".2f") + "%", f"${m['max_drawdown']:,.2f}" if m["max_drawdown"] is not None else "n/a",
                     f(m["profit_factor"], ".2f"), f(m["sharpe"], ".2f"), _p(m["p_value"])])
    return table(["Strategy", "Trades", "Win Rate", "Gross Profit", "Total Fees", "Net Profit", "ROI %", "Max DD",
                  "Profit Factor", "Sharpe", "p (mean>0?)"], rows, "TABLE 2: 'Buy No' strategies (after Kalshi taker fees)")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    d = p.add_argument_group("data")
    d.add_argument("--series", default="KXBTC15M", choices=list(kalshi_data.SERIES))
    d.add_argument("--days", type=float, default=7)
    d.add_argument("--start"), d.add_argument("--end")
    d.add_argument("--source", choices=["auto", "live", "synthetic"], default="auto")
    d.add_argument("--checkpoints", type=minutes, nargs="+", default=[10, 5], help="minutes before expiry to extract, e.g. 10m 5m")
    d.add_argument("--max-markets", type=int, default=1500)
    d.add_argument("--cache-dir", default=".cache")
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--bias", type=float, default=3.0, help="synthetic only: Yes overpricing premium in cents")
    d.add_argument("--upside-extra", type=float, default=2.0, help="synthetic only: extra premium on upside strikes")
    a = p.add_argument_group("analysis")
    a.add_argument("--entry-checkpoint", type=minutes, default=5)
    a.add_argument("--price-source", choices=["trade", "mid", "executable"], default="trade")
    a.add_argument("--spot-ref", choices=["checkpoint", "open"], default="checkpoint")
    a.add_argument("--min-price", type=float, default=20, help="Rule 3 lower Yes price (cents)")
    a.add_argument("--max-price", type=float, default=50, help="Rule 3 upper Yes price (cents)")
    a.add_argument("--bin-width", type=int, default=10)
    a.add_argument("--tails", action="store_true", help="also show <10c and >90c bins")
    a.add_argument("--p-test", choices=list(stats.P_TESTS), default="twoprop")
    a.add_argument("--hours", help="only trade expiries in this UTC hour range, e.g. 13-21")
    t = p.add_argument_group("trading")
    t.add_argument("--contracts", type=int, default=1)
    t.add_argument("--fee-rate", type=float, default=backtest.TAKER_FEE_RATE)
    t.add_argument("--capital", type=float, default=1000.0)
    o = p.add_argument_group("output")
    o.add_argument("--outdir", default=".")
    o.add_argument("--no-plots", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    cps = sorted({*a.checkpoints, a.entry_checkpoint}, reverse=True)
    start = datetime.fromisoformat(a.start) if a.start else None
    end = datetime.fromisoformat(a.end) if a.end else None
    raw = kalshi_data.load_contracts(a.series, a.days, end, start, cps, a.source, a.seed, a.bias, a.upside_extra,
                                     max_markets=a.max_markets, cache_dir=a.cache_dir)
    hours = tuple(int(x) for x in a.hours.split("-")) if a.hours else None
    frame = kalshi_data.analysis_frame(raw, a.entry_checkpoint, a.price_source, a.spot_ref, hours)
    print(f"Source: {raw.attrs['source'].upper()} | series {a.series} | {len(raw)} settled contracts "
          f"({raw['close_time'].min():%Y-%m-%d} -> {raw['close_time'].max():%Y-%m-%d} UTC) | "
          f"{len(frame)} with a {a.entry_checkpoint}m price")
    for note in raw.attrs.get("notes", []):
        print("NOTE:", note)
    tables = calibration.calibration_report(frame, width=a.bin_width, tails=a.tails, p_test=a.p_test)
    print(format_calibration(tables))
    asym = stats.asymmetry_test(frame)
    if asym["diff"] is not None:
        mt = asym["matched"]
        if mt["diff"] is not None:
            print(f"Asymmetry, price-matched ({asym['overlap'][0]:g}-{asym['overlap'][1]:g}¢ only): upside {100 * mt['gap_upside']:+.2f} pp "
                  f"(n={mt['n_upside']}) vs downside {100 * mt['gap_downside']:+.2f} pp (n={mt['n_downside']}); difference "
                  f"{100 * mt['diff']:+.2f} pp, Welch p={_p(mt['welch_p'])}")
        print(f"\nAsymmetry (raw, confounded with price level): overpricing upside {100 * asym['gap_upside']:+.2f} pp (n={asym['n_upside']}) vs downside "
              f"{100 * asym['gap_downside']:+.2f} pp (n={asym['n_downside']}); difference {100 * asym['diff']:+.2f} pp "
              f"[{100 * asym['ci_lo']:+.2f}, {100 * asym['ci_hi']:+.2f}], Welch p={_p(asym['welch_p'])}")
    rules = backtest.default_rules(a.min_price, a.max_price)
    trades = backtest.run_rules(frame, rules, price_source=a.price_source, contracts=a.contracts, fee_rate=a.fee_rate)
    print(format_strategies({n: stats.strategy_metrics(t, a.capital) for n, t in trades.items()}))
    if not a.no_plots:
        out = Path(a.outdir)
        out.mkdir(parents=True, exist_ok=True)
        print("\nSaved:", plot.calibration_chart(tables, out / "calibration_chart.png"))
        print("Saved:", plot.equity_curve(trades, out / "equity_curve.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
