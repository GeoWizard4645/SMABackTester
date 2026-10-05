"""Indicator and return calculations: SMA, ATR, distance to MA, offset returns."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

MA_TYPES = ("sma", "ema", "wma")


def compute_sma(close: pd.Series, window: int) -> pd.Series:
    """Simple moving average that includes the current bar."""
    return close.rolling(window, min_periods=window).mean()


def compute_ema(close: pd.Series, window: int) -> pd.Series:
    """Exponential moving average with span = window (alpha = 2 / (window + 1))."""
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def compute_wma(close: pd.Series, window: int) -> pd.Series:
    """Linearly weighted moving average: the newest bar has weight N, the oldest 1."""
    weights = np.arange(window, 0, -1, dtype=float)  # weight of lag 0, 1, ..., N-1
    values = np.convolve(close.to_numpy(dtype=float), weights)[: len(close)] / weights.sum()
    values[: window - 1] = np.nan
    return pd.Series(values, index=close.index)


def compute_ma(close: pd.Series, window: int, ma_type: str = "sma") -> pd.Series:
    """Moving average of the requested type ('sma', 'ema' or 'wma')."""
    kind = ma_type.lower()
    if kind == "sma":
        return compute_sma(close, window)
    if kind == "ema":
        return compute_ema(close, window)
    if kind == "wma":
        return compute_wma(close, window)
    raise ValueError(f"ma_type must be one of {MA_TYPES}, got {ma_type!r}")


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
    ma_type: str = "sma",
) -> pd.DataFrame:
    """Return a copy of ``prices`` with MA/ATR/distance/range-expansion columns.

    The moving average column is always called ``sma`` (whatever ``ma_type`` is) so
    downstream code does not care which kind of line is being tested.

    ``atr_ratio`` and ``tr_ratio`` compare the current ATR / true range with
    the mean over the *previous* ``baseline_window`` days (current day excluded
    so the baseline is not contaminated by the event itself).
    """
    out = prices.copy()
    out["sma"] = compute_ma(out["Close"], ma_window, ma_type)
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
