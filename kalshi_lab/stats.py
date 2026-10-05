"""Hypothesis tests and strategy metrics for the Kalshi 15-minute study."""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats as sst

P_TESTS = ("twoprop", "binomial", "pbinom")


def wilson_ci(k: float, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (float("nan"), float("nan"))
    z = sst.norm.ppf(1 - (1 - conf) / 2)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def two_proportion_ztest(p1: float, n1: int, p2: float, n2: int) -> tuple[float, float]:
    """Two-sided two-proportion z-test (pooled variance)."""
    if n1 <= 0 or n2 <= 0:
        return (float("nan"), float("nan"))
    pbar = (n1 * p1 + n2 * p2) / (n1 + n2)
    se = math.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
    if se == 0:
        return (float("nan"), float("nan"))
    z = (p1 - p2) / se
    return (z, float(2 * sst.norm.sf(abs(z))))


def implied_vs_realized_p(prices_cents: np.ndarray, outcomes: np.ndarray, method: str = "twoprop") -> float:
    """p-value for H0: contracts are calibrated (realised Yes frequency = implied probability).

    twoprop  - two-proportion z-test of mean implied price vs realised rate (n for both); the
               form the study spec asks for. Treating the implied rate as a second sample of
               size n inflates the variance, so it is conservative.
    binomial - exact two-sided binomial test of the wins against the mean implied probability.
    pbinom   - z-test using the exact Poisson-binomial variance, sum p_i(1-p_i): each contract
               is held to its OWN price. The most powerful of the three.
    """
    n = len(outcomes)
    if n == 0:
        return float("nan")
    p = np.asarray(prices_cents, dtype=float) / 100.0
    wins = float(np.sum(outcomes))
    if method == "twoprop":
        return two_proportion_ztest(float(p.mean()), n, wins / n, n)[1]
    if method == "binomial":
        return float(sst.binomtest(int(round(wins)), n, float(np.clip(p.mean(), 1e-9, 1 - 1e-9))).pvalue)
    if method == "pbinom":
        var = float(np.sum(p * (1 - p)))
        if var == 0:
            return float("nan")
        return float(2 * sst.norm.sf(abs((wins - p.sum()) / math.sqrt(var))))
    raise ValueError(f"p_test must be one of {P_TESTS}")


def cluster_mean_test(values, days, n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean of ``values`` with a day-cluster bootstrap 95% CI and recentred two-sided p-value (H0: mean = 0).

    Contracts expiring on the same day share market conditions, so whole days are resampled. With fewer
    than 5 distinct days no interval is reported.
    """
    values = np.asarray(values, dtype=float)
    keep = ~np.isnan(values)
    values, days = values[keep], np.asarray(days)[keep]
    n = len(values)
    out = {"n": n, "mean": float(values.mean()) if n else None, "lo": None, "hi": None, "p": None}
    uniq, inv = np.unique(days, return_inverse=True)
    if n == 0 or len(uniq) < 5:
        return out
    sums = np.bincount(inv, weights=values)
    cnt = np.bincount(inv).astype(float)
    idx = np.random.default_rng(seed).integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = sums[idx].sum(1) / cnt[idx].sum(1)
    m = float(values.mean())
    out.update(lo=float(np.quantile(means, 0.025)), hi=float(np.quantile(means, 0.975)),
               p=float(min(1.0, (1 + np.sum(np.abs(means - m) >= abs(m))) / (n_boot + 1))))
    return out


def _compare_groups(up: np.ndarray, dn: np.ndarray) -> dict:
    out = {"n_upside": len(up), "n_downside": len(dn), "gap_upside": float(up.mean()) if len(up) else None,
           "gap_downside": float(dn.mean()) if len(dn) else None, "diff": None, "welch_p": None,
           "mwu_p": None, "ci_lo": None, "ci_hi": None}
    if len(up) < 2 or len(dn) < 2:
        return out
    diff = float(up.mean() - dn.mean())
    se = math.sqrt(up.var(ddof=1) / len(up) + dn.var(ddof=1) / len(dn))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out["welch_p"] = float(sst.ttest_ind(up, dn, equal_var=False).pvalue)
        try:
            out["mwu_p"] = float(sst.mannwhitneyu(up, dn, alternative="two-sided").pvalue)
        except ValueError:
            pass
    out.update(diff=diff, ci_lo=diff - 1.96 * se, ci_hi=diff + 1.96 * se)
    return out


def asymmetry_test(frame: pd.DataFrame, overlap: tuple[float, float] = (40.0, 60.0), measure: str = "raw") -> dict:
    """Is the optimism bias different for upside strikes (K > spot) than downside (K < spot)?

    Per contract the *overpricing residual* is r = Yes price - realised outcome (as a fraction);
    its mean is the overpricing gap. Two comparisons are returned:

    * ``raw``     - all upside vs all downside contracts. CAUTION: in an up/down market an upside
                    strike is almost always a cheap out-of-the-money Yes (< 50c) and a downside
                    strike an expensive in-the-money one, so this mixes direction with the
                    favourite-longshot effect.
    * ``matched`` - only contracts with Yes priced inside ``overlap`` cents, where both
                    directions trade, which holds the price level roughly fixed.
    """
    if measure == "fair":  # trend-free: price minus model fair value
        frame = frame[frame["fair"].notna()]
        r = frame["premium"] / 100.0
    else:  # price minus what actually happened (includes trend and luck)
        r = frame["yes_price"] / 100.0 - frame["result"]
    is_up, is_dn = frame["direction"] == "upside", frame["direction"] == "downside"
    raw = _compare_groups(r[is_up].to_numpy(), r[is_dn].to_numpy())
    lo, hi = overlap
    inside = (frame["yes_price"] >= lo) & (frame["yes_price"] <= hi)
    matched = _compare_groups(r[is_up & inside].to_numpy(), r[is_dn & inside].to_numpy())
    return {**raw, "matched": matched, "overlap": [lo, hi]}


def strategy_metrics(trades: pd.DataFrame, capital: float = 1000.0) -> dict:
    """Performance summary of a trade list (columns: time, cost, fee, gross, net, won, contracts).

    All money is in dollars in the output; trade columns are in cents.
    ROI is net profit over capital deployed (entry cost + fees). Sharpe uses daily PnL and
    sqrt(365) because the market trades every day.
    """
    n = len(trades)
    keys = ["trades", "wins", "win_rate", "gross_profit", "fees", "net_profit", "roi_pct", "profit_factor",
            "max_drawdown", "max_drawdown_pct", "sharpe", "mean_net_cents", "t_stat", "p_value", "breakeven_win_rate"]
    if n == 0:
        return {k: (0 if k in ("trades", "wins") else None) for k in keys}
    net = trades["net"].to_numpy(dtype=float)
    gross, fee, cost = trades["gross"].sum() / 100, trades["fee"].sum() / 100, trades["cost"].sum() / 100
    wins = int(trades["won"].sum())
    pos, neg = net[net > 0].sum(), -net[net < 0].sum()
    cum = np.cumsum(net) / 100
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = peak - cum
    daily = trades.assign(day=pd.to_datetime(trades["time"]).dt.date).groupby("day")["net"].sum() / 100
    sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(365)) if len(daily) > 2 and daily.std(ddof=1) > 0 else None
    t_stat = p_val = None
    if n > 2 and net.std(ddof=1) > 0:
        res = sst.ttest_1samp(net, 0.0)
        t_stat, p_val = float(res.statistic), float(res.pvalue)
    contracts = trades["contracts"].to_numpy(dtype=float)
    extra = _edge_metrics(trades)
    return {**extra,
        "trades": n, "wins": wins, "win_rate": wins / n,
        "gross_profit": float(gross), "fees": float(fee), "net_profit": float(net.sum() / 100),
        "roi_pct": float(100 * (net.sum() / 100) / (cost + fee)) if cost + fee > 0 else None,
        "profit_factor": float(pos / neg) if neg > 0 else None,
        "max_drawdown": float(dd.max()), "max_drawdown_pct": float(100 * dd.max() / (capital + peak[dd.argmax()])) if capital > 0 else None,
        "sharpe": sharpe, "mean_net_cents": float(net.mean() / contracts.mean()),
        "t_stat": t_stat, "p_value": p_val,
        "breakeven_win_rate": float(((trades["cost"] + trades["fee"]) / (100 * contracts)).mean()),
    }


def _edge_metrics(trades: pd.DataFrame) -> dict:
    """Split realised profit into the part explained by mispricing and the part that is luck / BTC's trend.

    For every trade, ``edge_gross`` is the profit you would expect if the model's fair probability were the
    truth (expected payout minus price paid): that is exactly the mispricing captured. ``luck`` is realised
    payout minus expected payout. realised net = edge_net + luck, trade by trade.
    """
    blank = {"edge_net_profit": None, "luck": None, "edge_cents": None, "edge_ci": None, "edge_p": None}
    if "edge_net" not in trades.columns:
        return blank
    e = trades["edge_net"].to_numpy(dtype=float)
    ok = ~np.isnan(e)
    if not ok.any():
        return blank
    t = trades[ok]
    per = (t["edge_net"] / t["contracts"]).to_numpy(dtype=float)
    test = cluster_mean_test(per, pd.to_datetime(t["time"]).dt.date.to_numpy())
    return {"edge_net_profit": float(t["edge_net"].sum() / 100), "luck": float(t["luck"].sum() / 100),
            "edge_cents": test["mean"], "edge_ci": [test["lo"], test["hi"]] if test["lo"] is not None else None,
            "edge_p": test["p"]}


def day_cluster_bootstrap_mean(values: np.ndarray, days: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% CI for a mean, resampling whole calendar days (trades within a day are dependent)."""
    values, days = np.asarray(values, dtype=float), np.asarray(days)
    uniq, inv = np.unique(days, return_inverse=True)
    if len(uniq) < 5:
        return (float("nan"), float("nan"))
    s = np.bincount(inv, weights=values)
    c = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = s[idx].sum(1) / c[idx].sum(1)
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))
