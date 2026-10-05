"""Indicator and return calculations: SMA, ATR, distance to MA, offset returns."""

from __future__ import annotations

from typing import Iterable

import pandas as pd


def compute_sma(close: pd.Series, window: int) -> pd.Series:
    """Simple moving average that includes the current bar."""
    return close.rolling(window, min_periods=window).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    parts = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return parts.max(axis=1)


def compute_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14
) -> pd.Series:
    """Wilder-smoothed Average True Range."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def pct_distance(close: pd.Series, sma: pd.Series) -> pd.Series:
    """Signed percentage distance of price to the moving average."""
    return (close - sma) / sma


def add_indicators(
    prices: pd.DataFrame,
    ma_window: int,
    atr_window: int = 14,
    baseline_window: int = 20,
) -> pd.DataFrame:
    """Return a copy of ``prices`` with SMA/ATR/distance/range-expansion columns.

    ``atr_ratio`` and ``tr_ratio`` compare the current ATR / true range with
    the mean over the *previous* ``baseline_window`` days (current day excluded
    so the baseline is not contaminated by the event itself).
    """
    out = prices.copy()
    out["sma"] = compute_sma(out["Close"], ma_window)
    out["tr"] = true_range(out["High"], out["Low"], out["Close"])
    out["atr"] = compute_atr(out["High"], out["Low"], out["Close"], atr_window)
    out["dist_pct"] = pct_distance(out["Close"], out["sma"])
    out["dist_atr"] = (out["Close"] - out["sma"]) / out["atr"]
    atr_base = out["atr"].shift(1).rolling(baseline_window, min_periods=baseline_window).mean()
    tr_base = out["tr"].shift(1).rolling(baseline_window, min_periods=baseline_window).mean()
    out["atr_ratio"] = out["atr"] / atr_base
    out["tr_ratio"] = out["tr"] / tr_base
    return out


def offset_returns(close: pd.Series, offsets: Iterable[int], base: int = 0) -> pd.DataFrame:
    """Return matrix R[s, j] = Close[s+j] / Close[s+base] - 1 for each offset j.

    Positive offsets look forward in time, negative offsets look back.
    NaN where the required bar does not exist.
    """
    base_px = close.shift(-base)
    return pd.DataFrame(
        {j: close.shift(-j) / base_px - 1.0 for j in offsets}, index=close.index
    )
