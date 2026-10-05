"""Historical price download, caching and validation."""

from __future__ import annotations

import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close"]
CACHE_MAX_AGE_HOURS = 24.0


def _cache_path(cache_dir: Path, ticker: str, start: str, end: str | None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", ticker)
    return cache_dir / f"{safe}_{start}_{end or 'latest'}.csv"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names/index and drop unusable rows."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.title)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Price data is missing columns: {missing}")
    df = df[REQUIRED_COLUMNS + (["Volume"] if "Volume" in df.columns else [])].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    df.index.name = "Date"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=REQUIRED_COLUMNS)
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    # Repair the odd inconsistent bar so High/Low always bracket Open/Close.
    df["High"] = df[["Open", "High", "Low", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "High", "Low", "Close"]].min(axis=1)
    return df


def download_prices(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(
            f"yfinance returned no data for {ticker!r} ({start} -> {end or 'today'}). "
            "Check the ticker/network, or use --csv / --synthetic."
        )
    return _clean(raw)


def load_prices(
    ticker: str = "^GSPC",
    start: str = "1950-01-01",
    end: str | None = None,
    cache_dir: str | Path = ".cache",
    refresh: bool = False,
) -> pd.DataFrame:
    """Return daily OHLC data, using an on-disk CSV cache.

    A cache entry for an open-ended request (``end=None``) expires after 24h;
    entries with a fixed ``end`` never expire.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, ticker, start, end)

    if path.exists() and not refresh:
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        if end is not None or age_h < CACHE_MAX_AGE_HOURS:
            return _clean(pd.read_csv(path, index_col=0, parse_dates=True))

    df = download_prices(ticker, start, end)
    df.to_csv(path)
    return df


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a user-supplied OHLC CSV (first column = date)."""
    return _clean(pd.read_csv(path, index_col=0, parse_dates=True))


def generate_synthetic(
    start: str = "1950-01-01",
    end: str | None = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Random-walk OHLC series with GARCH-like volatility clustering.

    Contains NO moving-average effect by construction, so it is useful for
    smoke-testing the pipeline and for checking that the tests do not reject
    a true null.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end or pd.Timestamp.today().normalize())
    n = len(idx)
    omega, alpha, beta = 2e-6, 0.08, 0.90
    var = np.empty(n)
    ret = np.empty(n)
    var[0] = omega / (1 - alpha - beta)
    for i in range(n):
        if i > 0:
            var[i] = omega + alpha * ret[i - 1] ** 2 + beta * var[i - 1]
        ret[i] = 0.0003 + np.sqrt(var[i]) * rng.standard_normal()
    close = 17.0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[close[0]], close[:-1]]) * np.exp(
        0.2 * np.sqrt(var) * rng.standard_normal(n)
    )
    span = np.abs(rng.standard_normal(n)) * np.sqrt(var) * 0.8
    high = np.maximum(open_, close) * np.exp(span)
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.standard_normal(n)) * np.sqrt(var) * 0.8)
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)
    df.index.name = "Date"
    return df
