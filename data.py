"""Historical price download, caching and validation."""

from __future__ import annotations

import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close"]
CACHE_MAX_AGE_HOURS = 24.0
IS_BROWSER = sys.platform == "emscripten"  # running inside Pyodide
PROXY_BASE: str | None = None  # same-origin data proxy used in the browser (set by the worker)
UPLOADS: dict[str, pd.DataFrame] = {}  # user-uploaded series, keyed by pseudo-ticker


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


def parse_yahoo_chart(payload: dict) -> pd.DataFrame:
    """Daily OHLC from a Yahoo ``v8/finance/chart`` JSON payload, split/dividend adjusted.

    Mirrors yfinance's ``auto_adjust=True``: every price is scaled by adjclose / close.
    """
    chart = payload.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        err = chart.get("error") or {}
        raise RuntimeError(f"Yahoo returned no data: {err.get('description') or 'unknown symbol or empty range'}")
    res = chart["result"][0]
    ts = res.get("timestamp") or []
    if not ts:
        raise RuntimeError("Yahoo returned an empty price history")
    quote = res["indicators"]["quote"][0]
    offset = int((res.get("meta") or {}).get("gmtoffset") or 0)
    idx = pd.to_datetime(np.asarray(ts, dtype="int64") + offset, unit="s")
    df = pd.DataFrame({"Open": quote["open"], "High": quote["high"], "Low": quote["low"], "Close": quote["close"]},
                      index=idx).apply(pd.to_numeric, errors="coerce")
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    if adj:
        factor = pd.to_numeric(pd.Series(adj, index=idx), errors="coerce") / df["Close"]
        factor = factor.where(np.isfinite(factor), 1.0)
        for col in REQUIRED_COLUMNS:
            df[col] = df[col] * factor
    return _clean(df)


def _download_via_proxy(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    if not PROXY_BASE:
        raise RuntimeError("no data proxy configured")
    from pyodide.http import open_url  # type: ignore

    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp(end).timestamp()) if end else int(time.time()) + 86400
    url = f"{PROXY_BASE}/yahoo?" + urlencode({"symbol": ticker, "period1": p1, "period2": p2})
    body = open_url(url).read()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError("the data proxy returned a non-JSON response") from None
    if "error" in payload and "chart" not in payload:
        raise RuntimeError(f"data proxy error: {payload['error']}")
    return parse_yahoo_chart(payload)


def download_prices(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    if IS_BROWSER:
        return _download_via_proxy(ticker, start, end)
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


def register_upload(name: str, csv_text: str) -> str:
    """Store an uploaded OHLC CSV (first column = date) and return its pseudo-ticker."""
    safe = re.sub(r"[^A-Za-z0-9]+", "-", name.rsplit(".", 1)[0]).strip("-")[:14] or "DATA"
    ticker = f"UPLOAD-{safe}".upper()
    df = _clean(pd.read_csv(io.StringIO(csv_text), index_col=0, parse_dates=True))
    if len(df) < 50:
        raise ValueError("the CSV needs at least 50 daily rows with Open, High, Low, Close columns")
    UPLOADS[ticker] = df
    return ticker


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
