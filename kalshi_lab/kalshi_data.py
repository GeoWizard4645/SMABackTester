"""Kalshi 15-minute crypto contract data.

Pulls settled contracts, 1-minute quote/trade candles and spot prices from public APIs, or
generates a synthetic dataset with the same schema. Works in two environments:

* normal Python  -> ``requests``
* Pyodide (browser) -> synchronous XHR via ``pyodide.http.open_url`` through a same-origin
  proxy, because Kalshi rejects browser ``Origin`` headers (see ``configure``).

Contract frame schema (one row per settled contract, prices in cents, times naive UTC):
    ticker, series, open_time, close_time, strike, settle_value, result (1 = Yes, 0 = No),
    spot_open, and for every checkpoint m (minutes before expiry):
    trade_m, bid_m, ask_m (YES prices) and spot_m.
"""

from __future__ import annotations

import bisect
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE_BASE = "https://api.exchange.coinbase.com"
IS_BROWSER = sys.platform == "emscripten"

# series -> (Coinbase product used for spot, human name)
SERIES = {
    "KXBTC15M": ("BTC-USD", "Bitcoin"),
    "KXETH15M": ("ETH-USD", "Ethereum"),
    "KXSOL15M": ("SOL-USD", "Solana"),
    "KXXRP15M": ("XRP-USD", "XRP"),
    "KXDOGE15M": ("DOGE-USD", "Dogecoin"),
    "KXBNB15M": (None, "BNB"),  # not listed on Coinbase: no spot -> direction unavailable
    "KXHYPE15M": (None, "Hyperliquid"),
}
DEFAULT_CHECKPOINTS = (10, 5)
# The batch-candlestick endpoint rejects a request when (number of tickers) x (minutes between
# start_ts and end_ts) > 10,000, whether or not those minutes contain any candles. Markets are
# therefore grouped greedily so that every batch stays under this budget even across gaps.
CANDLE_BUDGET = 9000

ENDPOINTS = {"kalshi": KALSHI_BASE, "coinbase": COINBASE_BASE}
_progress = lambda msg: None  # noqa: E731


class DataError(RuntimeError):
    """Raised when the live data source cannot satisfy a request."""


def configure(kalshi: str | None = None, coinbase: str | None = None, progress=None) -> None:
    """Point the data layer at proxy URLs (browser) and/or install a progress callback."""
    global _progress
    if kalshi:
        ENDPOINTS["kalshi"] = kalshi.rstrip("/")
    if coinbase:
        ENDPOINTS["coinbase"] = coinbase.rstrip("/")
    if progress is not None:
        _progress = progress


# ------------------------------------------------------------------ HTTP
_last_call = {"t": 0.0}


def _pace(url: str) -> None:
    """Space requests out: Kalshi answers 429 to bursts of calls (about a dozen in a second)."""
    gap = 0.35 if "kalshi" in url else 0.12
    wait = gap - (time.monotonic() - _last_call["t"])
    if wait > 0:
        time.sleep(wait)
    _last_call["t"] = time.monotonic()


def _rate_limited(err, status: int) -> bool:
    text = json.dumps(err).lower() if err is not None else ""
    return status == 429 or "too_many" in text or "too many" in text or "rate" in text and "limit" in text


def _get_json(url: str, params: dict | None = None, retries: int = 7):
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    last = "unknown error"
    for attempt in range(retries):
        _pace(url)
        try:
            if IS_BROWSER:
                from pyodide.http import open_url  # type: ignore

                body = open_url(url).read()
                status = 200
            else:
                import requests

                r = requests.get(url, headers={"User-Agent": "kalshi-lab/1.0"}, timeout=40)
                body, status = r.text, r.status_code
            if status == 403:
                raise DataError("HTTP 403 from the data source (Kalshi blocks browser-style requests; "
                                "use the proxy or the synthetic source)")
            data = json.loads(body)
        except DataError:
            raise
        except Exception as exc:  # network / JSON problems
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(0.6 * (attempt + 1))
            continue
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            code = err.get("code") if isinstance(err, dict) else str(err)
            last = f"API error {code}"
            if _rate_limited(err, status):
                _progress(f"Kalshi is rate-limiting requests; waiting {min(20, 2 ** attempt)}s…")
                time.sleep(min(20, 2 ** attempt))
                continue
            raise DataError(f"{url.split('?')[0]} -> {err}")
        if status == 429:
            time.sleep(min(20, 2 ** attempt))
            continue
        return data
    raise DataError(f"giving up on {url.split('?')[0]}: {last}")


def _dollars_to_cents(x) -> float:
    try:
        return float(x) * 100.0 if x not in (None, "") else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


# ------------------------------------------------------------------ live pull
def _paged(path: str, params: dict, key: str, stop=None) -> list[dict]:
    out, cursor = [], None
    while True:
        p = dict(params, **({"cursor": cursor} if cursor else {}))
        page = _get_json(f"{ENDPOINTS['kalshi']}/{path}", p)
        rows = page.get(key, [])
        out.extend(rows)
        cursor = page.get("cursor")
        _progress(f"listed {len(out)} markets…")
        if not cursor or not rows or (stop and stop(rows)):
            return out


def historical_cutoff_ts() -> int:
    """Settled markets older than this live under /historical/*."""
    try:
        return _ts(_get_json(f"{ENDPOINTS['kalshi']}/historical/cutoff")["market_settled_ts"])
    except Exception:
        return 0


def list_markets(series: str, start_ts: int, end_ts: int, max_markets: int) -> list[dict]:
    """Settled markets of a series that closed in [start_ts, end_ts]."""
    cutoff = historical_cutoff_ts()
    markets: list[dict] = []
    if end_ts > cutoff:
        markets += _paged("markets", {"series_ticker": series, "status": "settled", "limit": 1000,
                                      "min_close_ts": max(start_ts, cutoff), "max_close_ts": end_ts}, "markets")
    if start_ts < cutoff:
        # Historical listings are newest-first and ignore time filters: page until we pass start_ts.
        older = _paged("historical/markets", {"series_ticker": series, "limit": 1000}, "markets",
                       stop=lambda rows: min(_ts(m["close_time"]) for m in rows) < start_ts)
        markets += [m for m in older if start_ts <= _ts(m["close_time"]) <= min(end_ts, cutoff)]
    rows = [m for m in markets if m.get("result") in ("yes", "no")]
    rows.sort(key=lambda m: m["close_time"])
    if len(rows) > max_markets:
        _progress(f"capping {len(rows)} markets to the most recent {max_markets}")
        rows = rows[-max_markets:]
    return rows


def _candle_arrays(candles: list[dict]):
    """Per-minute arrays, forward-filled so every minute has the latest known quote/trade."""
    ends, trade, bid, ask = [], [], [], []
    lt = lb = la = float("nan")
    for c in sorted(candles, key=lambda c: c["end_period_ts"]):
        price = c.get("price") or {}
        t = _dollars_to_cents(price.get("close_dollars"))
        if math.isnan(t):
            t = _dollars_to_cents(price.get("previous_dollars"))
        b = _dollars_to_cents((c.get("yes_bid") or {}).get("close_dollars"))
        a = _dollars_to_cents((c.get("yes_ask") or {}).get("close_dollars"))
        lt = t if not math.isnan(t) else lt
        lb = b if not math.isnan(b) else lb
        la = a if not math.isnan(a) else la
        ends.append(int(c["end_period_ts"]))
        trade.append(lt), bid.append(lb), ask.append(la)
    return ends, trade, bid, ask


def fetch_candles(markets: list[dict], series: str) -> dict[str, list[dict]]:
    """1-minute candles for every market (batched for live markets, one call each for old ones)."""
    cutoff = historical_cutoff_ts()
    live = [m for m in markets if _ts(m["close_time"]) > cutoff]
    old = [m for m in markets if _ts(m["close_time"]) <= cutoff]
    out: dict[str, list[dict]] = {}
    batches, chunk = [], []
    for m in live:  # `live` is sorted by close time
        trial = chunk + [m]
        lo = min(_ts(x["open_time"]) for x in trial) - 60
        hi = max(_ts(x["close_time"]) for x in trial) + 60
        if chunk and len(trial) * ((hi - lo) / 60 + 1) > CANDLE_BUDGET:
            batches.append(chunk)
            chunk = [m]
        else:
            chunk = trial
    if chunk:
        batches.append(chunk)
    done = 0
    for chunk in batches:
        lo = min(_ts(m["open_time"]) for m in chunk) - 60
        hi = max(_ts(m["close_time"]) for m in chunk) + 60
        data = _get_json(f"{ENDPOINTS['kalshi']}/markets/candlesticks", {
            "market_tickers": ",".join(m["ticker"] for m in chunk), "start_ts": lo, "end_ts": hi, "period_interval": 1})
        for entry in data.get("markets", []):
            out[entry.get("market_ticker") or entry.get("ticker")] = entry.get("candlesticks", [])
        done += len(chunk)
        _progress(f"candles for {done}/{len(live)} recent markets")
    for j, m in enumerate(old):
        data = _get_json(f"{ENDPOINTS['kalshi']}/historical/markets/{m['ticker']}/candlesticks", {
            "start_ts": _ts(m["open_time"]) - 60, "end_ts": _ts(m["close_time"]) + 60, "period_interval": 1})
        out[m["ticker"]] = data.get("candlesticks", [])
        if j % 25 == 0:
            _progress(f"candles for {j}/{len(old)} historical markets")
    return out


def fetch_spot(product: str, start_ts: int, end_ts: int) -> dict[int, float]:
    """Coinbase 1-minute closes keyed by the *end* timestamp of each minute bucket."""
    out: dict[int, float] = {}
    step = 300 * 60
    t = start_ts - start_ts % 60
    n_chunks = max(1, math.ceil((end_ts - t) / step))
    for k in range(n_chunks):
        lo, hi = t + k * step, min(end_ts, t + (k + 1) * step)
        iso = lambda s: datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        rows = _get_json(f"{ENDPOINTS['coinbase']}/products/{product}/candles",
                         {"granularity": 60, "start": iso(lo), "end": iso(hi)})
        for r in rows if isinstance(rows, list) else []:
            out[int(r[0]) + 60] = float(r[4])
        if k % 5 == 0:
            _progress(f"spot prices {k + 1}/{n_chunks}")
    return out


def _asof(ends: list[int], values: list[float], target: int, stale_s: int) -> float:
    i = bisect.bisect_right(ends, target) - 1
    if i < 0 or target - ends[i] > stale_s:
        return float("nan")
    return values[i]


def pull_live(series: str, start: datetime, end: datetime, checkpoints=DEFAULT_CHECKPOINTS,
              max_markets: int = 1500, max_stale_min: int = 3, with_spot: bool = True) -> pd.DataFrame:
    """Live contract frame from the public APIs."""
    s_ts, e_ts = int(start.replace(tzinfo=timezone.utc).timestamp()), int(end.replace(tzinfo=timezone.utc).timestamp())
    markets = list_markets(series, s_ts, e_ts, max_markets)
    if not markets:
        raise DataError(f"no settled {series} markets between {start:%Y-%m-%d} and {end:%Y-%m-%d}")
    candles = fetch_candles(markets, series)
    product = SERIES.get(series, (None, ""))[0]
    spot: dict[int, float] = {}
    notes: list[str] = []
    if with_spot and product:
        try:
            spot = fetch_spot(product, _ts(markets[0]["open_time"]) - 120, _ts(markets[-1]["close_time"]) + 60)
        except DataError as exc:
            notes.append(f"spot prices unavailable ({exc}); upside/downside split disabled")
    elif with_spot:
        notes.append(f"no spot source for {series}; upside/downside split disabled")
    spot_ends = sorted(spot)
    spot_vals = [spot[k] for k in spot_ends]

    stale = max_stale_min * 60
    rows = []
    for m in markets:
        open_ts, close_ts = _ts(m["open_time"]), _ts(m["close_time"])
        ends, trade, bid, ask = _candle_arrays(candles.get(m["ticker"], []))
        row = {
            "ticker": m["ticker"], "series": series,
            "open_time": datetime.fromtimestamp(open_ts, tz=timezone.utc).replace(tzinfo=None),
            "close_time": datetime.fromtimestamp(close_ts, tz=timezone.utc).replace(tzinfo=None),
            "strike": float(m.get("floor_strike") or float("nan")),
            "settle_value": float(m.get("expiration_value") or float("nan")),
            "result": 1 if m["result"] == "yes" else 0,
            "spot_open": _asof(spot_ends, spot_vals, open_ts, 180) if spot else float("nan"),
        }
        for c in checkpoints:
            t = close_ts - c * 60
            row[f"trade_{c}"] = _asof(ends, trade, t, stale) if ends else float("nan")
            row[f"bid_{c}"] = _asof(ends, bid, t, stale) if ends else float("nan")
            row[f"ask_{c}"] = _asof(ends, ask, t, stale) if ends else float("nan")
            row[f"spot_{c}"] = _asof(spot_ends, spot_vals, t, 180) if spot else float("nan")
        rows.append(row)
    df = pd.DataFrame(rows)
    df.attrs.update(source="live", series=series, notes=notes, checkpoints=list(checkpoints))
    return df


# ------------------------------------------------------------------ synthetic
def _phi(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(x / math.sqrt(2.0)))


def synthetic(series: str, start: datetime, end: datetime, checkpoints=DEFAULT_CHECKPOINTS, seed: int = 0,
              bias: float = 3.0, upside_extra: float = 2.0, noise: float = 2.0, annual_vol: float = 0.55) -> pd.DataFrame:
    """Simulated 15-minute up/down contracts with the same schema as live data.

    Spot follows a stochastic-volatility random walk. A contract opens every 15 minutes with
    strike = spot at open and settles Yes if spot at expiry >= strike. The quoted Yes price is
    the model-fair probability plus an *assumed* optimism premium::

        premium = bias * 4 p (1-p)  +  (upside_extra * 4 p (1-p) if the strike is above spot)

    so ``bias=0, upside_extra=0`` is a perfectly calibrated market (a null you can test the
    pipeline against) and larger values plant overpricing for the tests to find. These
    numbers are assumptions, NOT estimates of the real market.
    """
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start).floor("15min")
    t1 = pd.Timestamp(end).floor("15min")
    n_min = int((t1 - t0).total_seconds() // 60) + 16
    sig_min = annual_vol / math.sqrt(525_600)
    logvol = np.zeros(n_min)
    for i in range(1, n_min):
        logvol[i] = 0.995 * logvol[i - 1] + 0.06 * rng.standard_normal()
    sigma = sig_min * np.exp(logvol - logvol.var() / 2)
    spot = 65_000 * np.exp(np.cumsum(sigma * rng.standard_normal(n_min)))

    opens = np.arange(0, n_min - 15, 15)
    rows = []
    for o in opens:
        c_idx = o + 15
        k = spot[o] * (1 + rng.normal(0, 3e-6))
        row = {
            "ticker": f"{series}-SYN{(t0 + pd.Timedelta(minutes=int(o))):%y%b%d%H%M}".upper(),
            "series": series,
            "open_time": (t0 + pd.Timedelta(minutes=int(o))).to_pydatetime(),
            "close_time": (t0 + pd.Timedelta(minutes=int(c_idx))).to_pydatetime(),
            "strike": round(k, 2), "settle_value": round(float(spot[c_idx]), 2),
            "result": int(spot[c_idx] >= k), "spot_open": round(float(spot[o]), 2),
        }
        for m in checkpoints:
            idx = c_idx - m
            s_m = spot[idx]
            local_sig = sigma[idx] * s_m * math.sqrt(m)
            fair = float(_phi(np.array((s_m - k) / local_sig)))
            amp = 4 * fair * (1 - fair)
            prem = bias * amp + (upside_extra * amp if k > s_m else 0.0)
            px = float(np.clip(fair * 100 + prem + rng.normal(0, noise), 1, 99))
            spread = rng.choice([1, 1, 2, 2, 3])
            row[f"trade_{m}"] = float(np.clip(round(px + rng.normal(0, 0.6)), 1, 99))
            row[f"bid_{m}"] = float(np.clip(round(px - spread / 2), 1, 98))
            row[f"ask_{m}"] = float(np.clip(round(px + spread / 2), 2, 99))
            row[f"spot_{m}"] = round(float(s_m), 2)
        rows.append(row)
    df = pd.DataFrame(rows)
    df.attrs.update(source="synthetic", series=series, checkpoints=list(checkpoints),
                    notes=[f"SYNTHETIC data (seed {seed}, bias {bias}¢, upside extra {upside_extra}¢): "
                           "the overpricing is planted by assumption, not measured."])
    return df


# ------------------------------------------------------------------ orchestration
def load_contracts(series: str = "KXBTC15M", days: float = 7, end: datetime | None = None,
                   start: datetime | None = None, checkpoints=DEFAULT_CHECKPOINTS, source: str = "auto",
                   seed: int = 0, bias: float = 3.0, upside_extra: float = 2.0, noise: float = 2.0,
                   max_markets: int = 1500, cache_dir: str | Path | None = None, with_spot: bool = True) -> pd.DataFrame:
    """Contract frame from the live API ('live'), the generator ('synthetic') or live-then-synthetic ('auto')."""
    end = end or datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    start = start or end - timedelta(days=float(days))
    checkpoints = tuple(sorted({int(c) for c in checkpoints}, reverse=True))
    if source == "synthetic":
        return synthetic(series, start, end, checkpoints, seed, bias, upside_extra, noise)
    cache_file = None
    if cache_dir and not IS_BROWSER:
        cache_file = Path(cache_dir) / f"kalshi_{series}_{start:%Y%m%d%H}_{end:%Y%m%d%H}_{'-'.join(map(str, checkpoints))}.csv"
        if cache_file.exists():
            df = pd.read_csv(cache_file, parse_dates=["open_time", "close_time"])
            df.attrs.update(source="live", series=series, notes=["loaded from local cache"], checkpoints=list(checkpoints))
            return df
    try:
        df = pull_live(series, start, end, checkpoints, max_markets, with_spot=with_spot)
    except DataError as exc:
        if source == "live":
            raise
        df = synthetic(series, start, end, checkpoints, seed, bias, upside_extra, noise)
        df.attrs["notes"] = [f"Live Kalshi data unavailable ({exc}); using SYNTHETIC data instead."] + df.attrs["notes"]
        return df
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_file, index=False)
    return df


# ------------------------------------------------------------------ analysis frame
def analysis_frame(df: pd.DataFrame, checkpoint: int, price_source: str = "trade", spot_ref: str = "checkpoint",
                   hours: tuple[int, int] | None = None, weekdays: list[int] | None = None) -> pd.DataFrame:
    """Rows with a usable Yes price at ``checkpoint`` plus the columns the analyses need.

    Adds ``yes_price`` (cents), ``yes_bid``, ``yes_ask``, ``direction`` ('upside' if the strike is
    above spot, 'downside' if below, 'at' if equal, 'unknown' without spot), ``hour``, ``weekday``.

    price_source: 'trade' (last trade), 'mid' (bid/ask midpoint) or 'executable' (mid is used
    for calibration; the backtester then pays the ask / hits the bid).
    spot_ref: 'checkpoint' (spot when the price is observed - the economically meaningful split) or
    'open' (spot at market open: in KXBTC15M the strike IS the open reference price, so this
    split is essentially noise).
    """
    need = [f"trade_{checkpoint}", f"bid_{checkpoint}", f"ask_{checkpoint}"]
    if any(c not in df.columns for c in need):
        raise ValueError(f"checkpoint {checkpoint}m was not extracted; available: {df.attrs.get('checkpoints')}")
    out = df.copy()
    out["yes_bid"], out["yes_ask"] = out[f"bid_{checkpoint}"], out[f"ask_{checkpoint}"]
    mid = (out["yes_bid"] + out["yes_ask"]) / 2
    if price_source == "trade":
        out["yes_price"] = out[f"trade_{checkpoint}"]
    elif price_source in ("mid", "executable"):
        out["yes_price"] = mid
    else:
        raise ValueError("price_source must be trade, mid or executable")
    out["price_source"] = price_source
    spot = out["spot_open"] if spot_ref == "open" else out[f"spot_{checkpoint}"]
    diff = out["strike"] - spot
    out["direction"] = np.select([diff > 0, diff < 0, diff == 0], ["upside", "downside", "at"], default="unknown")
    out["hour"] = pd.to_datetime(out["close_time"]).dt.hour
    out["weekday"] = pd.to_datetime(out["close_time"]).dt.weekday
    out = out.dropna(subset=["yes_price"])
    out = out[(out["yes_price"] > 0) & (out["yes_price"] < 100)]
    if hours is not None:
        lo, hi = hours
        out = out[(out["hour"] >= lo) & (out["hour"] <= hi)] if lo <= hi else out[(out["hour"] >= lo) | (out["hour"] <= hi)]
    if weekdays is not None:
        out = out[out["weekday"].isin(weekdays)]
    return out.sort_values("close_time").reset_index(drop=True)
