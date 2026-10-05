"""Web-facing analysis service.

Turns a JSON config from the browser into validated settings, runs the research
pipeline (``data`` -> ``events`` -> ``stats``) and returns plain JSON-safe dicts.

The era scheme in ``stats`` is process-global state, so every analysis runs under
``LOCK``. That serialises requests inside one process, which is fine for a
research tool; run a single gunicorn worker (several threads are OK).
"""

from __future__ import annotations

import re
import threading
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import data
from events import EventConfig, build_baselines, cum_col, detect_events
from metrics import MA_TYPES, add_indicators, compute_ma
from stats import (
    ERA_ALL,
    ERA_CONFIG,
    ERA_DESC,
    ERA_ORDER,
    MIN_CLUSTERS,
    auto_era_bounds,
    compare,
    configure_eras,
    era_expansion,
    event_counts,
    summarize,
)

LOCK = threading.RLock()
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
TICKER_RE = re.compile(r"^[A-Za-z0-9^.=\-]{1,20}$")
SYNTHETIC = "SYNTHETIC"
DEFAULT_ERAS = [1990, 2007]
DEFAULT_ERAS_MAX_FIRST_YEAR = 1980

LIMITS = {
    "max_tickers": 8,
    "max_controls": 8,
    "max_window": 1000,
    "max_horizons": 8,
    "max_horizon": 60,
    "max_bootstrap": 20000,
    "max_eras": 8,
    "max_scan_windows": 250,
}

DEFAULTS: dict[str, Any] = {
    "tickers": ["^GSPC"],
    "start": "1950-01-01",
    "end": None,
    "target": 200,
    "controls": [174],
    "ma_type": "sma",
    "eras": {"mode": "smart", "ends": [1990, 2007], "n": 3},
    "base_era": None,
    "late_era": None,
    "band": 0.5,
    "breach": 1.5,
    "approach": 5,
    "refractory": 10,
    "atr_window": 14,
    "horizons": [1, 3, 5, 10],
    "breach_basis": "close",
    "direction": "both",
    "pre": 5,
    "post": 10,
    "bootstrap": 2000,
    "seed": 42,
    "plot_horizon": 5,
}


class ConfigError(ValueError):
    """Raised for invalid user input (reported to the browser as HTTP 400)."""


# ------------------------------------------------------------------ validation
def _num(raw: dict, key: str, lo: float, hi: float, integer: bool = False):
    value = raw.get(key, DEFAULTS[key])
    try:
        value = int(value) if integer else float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"'{key}' must be a number") from None
    if not (lo <= value <= hi):
        raise ConfigError(f"'{key}' must be between {lo} and {hi}")
    return value


def _int_list(values: Any, key: str, lo: int, hi: int, max_len: int) -> list[int]:
    if values is None:
        values = []
    if not isinstance(values, (list, tuple)):
        raise ConfigError(f"'{key}' must be a list")
    out: list[int] = []
    for v in values:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ConfigError(f"'{key}' contains a non-integer: {v!r}") from None
        if not (lo <= iv <= hi):
            raise ConfigError(f"'{key}' values must be between {lo} and {hi}")
        if iv not in out:
            out.append(iv)
    if len(out) > max_len:
        raise ConfigError(f"'{key}' accepts at most {max_len} values")
    return out


def _date(value: Any, key: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(str(value)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        raise ConfigError(f"'{key}' must be a date like 2015-01-31") from None


def parse_config(raw: dict | None) -> dict:
    """Validate and normalise a browser config; fills in defaults."""
    raw = dict(raw or {})
    tickers = raw.get("tickers", DEFAULTS["tickers"])
    if isinstance(tickers, str):
        tickers = [tickers]
    clean: list[str] = []
    for t in tickers:
        t = str(t).strip()
        if t.lower() == "synthetic":
            t = SYNTHETIC
        if not TICKER_RE.match(t):
            raise ConfigError(f"invalid ticker {t!r}: use letters, digits and ^ . = -")
        if t not in clean:
            clean.append(t)
    if not clean:
        raise ConfigError("choose at least one asset")
    if len(clean) > LIMITS["max_tickers"]:
        raise ConfigError(f"at most {LIMITS['max_tickers']} assets per run")

    cfg: dict[str, Any] = {"tickers": clean}
    cfg["start"] = _date(raw.get("start", DEFAULTS["start"]), "start") or DEFAULTS["start"]
    cfg["end"] = _date(raw.get("end"), "end")
    if cfg["end"] and cfg["end"] <= cfg["start"]:
        raise ConfigError("'end' must be after 'start'")

    cfg["target"] = _num(raw, "target", 2, LIMITS["max_window"], integer=True)
    controls = _int_list(raw.get("controls", DEFAULTS["controls"]), "controls", 2,
                         LIMITS["max_window"], LIMITS["max_controls"])
    cfg["controls"] = [c for c in controls if c != cfg["target"]]
    kind = str(raw.get("ma_type", DEFAULTS["ma_type"])).lower()
    if kind not in MA_TYPES:
        raise ConfigError(f"'ma_type' must be one of {MA_TYPES}")
    cfg["ma_type"] = kind

    eras = raw.get("eras") or {}
    mode = str(eras.get("mode", "smart")).lower()
    if mode not in ("smart", "custom", "equal"):
        raise ConfigError("eras.mode must be smart, custom or equal")
    ends = _int_list(eras.get("ends", DEFAULTS["eras"]["ends"]), "eras.ends", 1000, 2200,
                     LIMITS["max_eras"] - 1)
    ends = sorted(ends)
    try:
        n_eras = int(eras.get("n", 3))
    except (TypeError, ValueError):
        raise ConfigError("eras.n must be a number") from None
    if mode == "custom" and not ends:
        raise ConfigError("custom eras need at least one boundary year")
    if not (2 <= n_eras <= LIMITS["max_eras"]):
        raise ConfigError(f"eras.n must be between 2 and {LIMITS['max_eras']}")
    cfg["eras"] = {"mode": mode, "ends": ends, "n": n_eras}
    for key in ("base_era", "late_era"):
        v = raw.get(key)
        try:
            cfg[key] = None if v in (None, "") else int(v)
        except (TypeError, ValueError):
            raise ConfigError(f"'{key}' must be an era number") from None

    cfg["band"] = _num(raw, "band", 0.05, 5.0)
    cfg["breach"] = _num(raw, "breach", 0.1, 10.0)
    cfg["approach"] = _num(raw, "approach", 1, 30, integer=True)
    cfg["refractory"] = _num(raw, "refractory", 0, 90, integer=True)
    cfg["atr_window"] = _num(raw, "atr_window", 2, 100, integer=True)
    cfg["pre"] = _num(raw, "pre", 1, 30, integer=True)
    cfg["post"] = _num(raw, "post", 1, LIMITS["max_horizon"], integer=True)
    horizons = _int_list(raw.get("horizons", DEFAULTS["horizons"]), "horizons", 1,
                         LIMITS["max_horizon"], LIMITS["max_horizons"])
    if not horizons:
        raise ConfigError("choose at least one horizon")
    cfg["horizons"] = sorted(horizons)
    basis = str(raw.get("breach_basis", "close")).lower()
    if basis not in ("close", "low"):
        raise ConfigError("'breach_basis' must be close or low")
    cfg["breach_basis"] = basis
    direction = str(raw.get("direction", "both")).lower()
    if direction not in ("both", "support", "resistance"):
        raise ConfigError("'direction' must be both, support or resistance")
    cfg["direction"] = direction
    cfg["bootstrap"] = _num(raw, "bootstrap", 100, LIMITS["max_bootstrap"], integer=True)
    cfg["seed"] = _num(raw, "seed", 0, 2**31 - 1, integer=True)
    ph = raw.get("plot_horizon")
    cfg["plot_horizon"] = int(ph) if ph in cfg["horizons"] else (
        5 if 5 in cfg["horizons"] else cfg["horizons"][len(cfg["horizons"]) // 2]
    )
    return cfg


# ------------------------------------------------------------------ JSON safety
def to_py(obj: Any) -> Any:
    """Recursively convert numpy/pandas values to JSON-safe Python (NaN/inf -> None)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if np.isfinite(f) else None
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(obj).strftime("%Y-%m-%d")
    if isinstance(obj, pd.DataFrame):
        return to_py(obj.to_dict("records"))
    if isinstance(obj, (pd.Series, np.ndarray, pd.Index)):
        return [to_py(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): to_py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_py(v) for v in obj]
    return str(obj)


def _sig(arr: np.ndarray, digits: int = 6) -> list:
    """Round to significant digits for compact JSON."""
    out = []
    for v in np.asarray(arr, dtype=float):
        out.append(None if not np.isfinite(v) else float(f"{v:.{digits}g}"))
    return out


# ------------------------------------------------------------------ data & eras
def load_asset(cfg: dict, ticker: str) -> pd.DataFrame:
    if ticker == SYNTHETIC:
        return data.generate_synthetic(cfg["start"], cfg["end"], seed=cfg["seed"])
    if ticker in data.UPLOADS:
        df = data.UPLOADS[ticker]
        df = df[df.index >= pd.Timestamp(cfg["start"])]
        return df[df.index <= pd.Timestamp(cfg["end"])] if cfg["end"] else df
    try:
        return data.load_prices(ticker, cfg["start"], cfg["end"], CACHE_DIR)
    except Exception as exc:  # network, unknown symbol, ...
        raise ConfigError(f"could not load {ticker}: {exc}") from None


def setup_eras(cfg: dict, prices: pd.DataFrame) -> str:
    """Configure the global era scheme for this asset. Returns how it was chosen."""
    first, last = prices.index[0].year, prices.index[-1].year
    mode = cfg["eras"]["mode"]
    if mode == "custom":
        ends, how = cfg["eras"]["ends"], "custom boundaries"
    elif mode == "equal":
        ends = auto_era_bounds(prices.index, cfg["eras"]["n"])
        how = f"history split into {cfg['eras']['n']} equal eras"
    elif first <= DEFAULT_ERAS_MAX_FIRST_YEAR:
        ends, how = DEFAULT_ERAS, "default market regimes"
    else:
        ends, how = auto_era_bounds(prices.index, 3), "history split into equal thirds"
    configure_eras(ends, first, last, open_ended=cfg["end"] is None)
    return how


def _event_config(cfg: dict, window: int) -> EventConfig:
    return EventConfig(
        ma_window=window,
        atr_window=cfg["atr_window"],
        band_mult=cfg["band"],
        breach_mult=cfg["breach"],
        approach_days=cfg["approach"],
        refractory_days=cfg["refractory"],
        horizons=tuple(cfg["horizons"]),
        pre=cfg["pre"],
        post=cfg["post"],
        breach_basis=cfg["breach_basis"],
        ma_type=cfg["ma_type"],
    )


def _detect(cfg: dict, prices: pd.DataFrame, window: int, baselines) -> pd.DataFrame:
    ev = detect_events(prices, _event_config(cfg, window), baselines)
    if cfg["direction"] != "both" and len(ev):
        ev = ev[ev["direction"] == cfg["direction"]]
    return ev


def _resolve_eras(cfg: dict) -> tuple[str, str]:
    n = len(ERA_ORDER)
    b, l = cfg["base_era"] or 1, cfg["late_era"] or n
    if not (1 <= b <= n and 1 <= l <= n):
        raise ConfigError(f"base/late era must be between 1 and {n} for this asset")
    if b == l:
        raise ConfigError("base era and late era must differ")
    return ERA_ORDER[b - 1], ERA_ORDER[l - 1]


# ------------------------------------------------------------------ result pieces
def _path_block(sub: pd.DataFrame, offsets: list[int], signed: bool) -> dict:
    if len(sub) < 2:
        return {"n": int(len(sub)), "mean": None, "se": None}
    m = sub[[cum_col(j) for j in offsets]].to_numpy(dtype=float)
    if signed:
        m = m * sub["sign"].to_numpy(dtype=float)[:, None]
    cnt = (~np.isnan(m)).sum(axis=0)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        mean = np.nanmean(m, axis=0)
        se = np.nanstd(m, axis=0, ddof=1) / np.sqrt(cnt)
    return {"n": int(len(sub)), "mean": _sig(mean), "se": _sig(se)}


def _paths(events: pd.DataFrame, mas: list[int], pre: int, post: int) -> dict:
    offsets = list(range(-pre, post + 1))
    series: dict[str, dict] = {}
    for ma in mas:
        sub = events[events["ma"] == ma]
        block = {
            "support": _path_block(sub[sub["direction"] == "support"], offsets, False),
            "resistance": _path_block(sub[sub["direction"] == "resistance"], offsets, False),
            "pooled": _path_block(sub, offsets, True),
            "era": {e: _path_block(sub[sub["era"] == e], offsets, True) for e in ERA_ORDER},
        }
        series[str(ma)] = block
    return {"offsets": offsets, "series": series}


def _range_table(events: pd.DataFrame, mas: list[int]) -> list[dict]:
    rows = []
    for ma in mas:
        for era in ERA_ORDER + [ERA_ALL]:
            sub = events[events["ma"] == ma]
            if era != ERA_ALL:
                sub = sub[sub["era"] == era]
            rows.append(
                {
                    "ma": ma,
                    "era": era,
                    "n": len(sub),
                    "atr_ratio": sub["atr_ratio"].mean() if len(sub) else None,
                    "tr_ratio": sub["tr_ratio"].mean() if len(sub) else None,
                    "abs_dist_pct": sub["dist_pct"].abs().mean() if len(sub) else None,
                    "abs_dist_atr": sub["dist_atr"].abs().mean() if len(sub) else None,
                }
            )
    return rows


def _warnings(cfg: dict, ticker: str, prices: pd.DataFrame, events: pd.DataFrame, mas: list[int]) -> list[str]:
    out = []
    years = prices.index[-1].year - prices.index[0].year + 1
    if years < 20:
        out.append(
            f"Only {years} calendar years of history: each era holds few year-clusters, so the "
            "bootstrap and clustered regression are unreliable. Treat results as exploratory."
        )
    if ticker.upper().endswith(("-USD", "-USDT", "-EUR", "-BTC")):
        out.append(
            "24/7 market: every calendar day is a bar, so an N-bar average spans N calendar "
            "days and horizons / de-clustering are in calendar days."
        )
    if ticker == "^GSPC":
        out.append(
            "^GSPC before ~1962 has no true intraday High/Low (they equal Close), so ATR and "
            "touches in the early era are close-to-close approximations."
        )
    tgt = events[events["ma"] == cfg["target"]]
    for era in ERA_ORDER:
        n = int((tgt["era"] == era).sum())
        if n < 10:
            out.append(f"{era} ({ERA_DESC[era]}) has only {n} target events; its estimates are very noisy.")
        yrs = tgt.loc[tgt["era"] == era, "year"].nunique()
        if 0 < yrs < MIN_CLUSTERS:
            out.append(
                f"{era} spans only {yrs} calendar years with events; bootstrap inference is disabled "
                f"there (needs at least {MIN_CLUSTERS})."
            )
    return out


EVENT_FIELDS = ["date", "ma", "direction", "era", "close", "sma", "atr", "dist_pct", "dist_atr",
                "atr_ratio", "tr_ratio"]


def _events_payload(events: pd.DataFrame, horizons: list[int]) -> list[dict]:
    cols = EVENT_FIELDS + [f"{p}_{k}" for k in horizons for p in ("ret", "car", "bounce")]
    sub = events[cols].copy()
    sub["date"] = pd.to_datetime(sub["date"]).dt.strftime("%Y-%m-%d")
    num = sub.select_dtypes("number").columns
    sub[num] = sub[num].round(6)
    return to_py(sub)


def _price_payload(prices: pd.DataFrame, mas: list[int], ma_type: str) -> dict:
    close = prices["Close"]
    return {
        "dates": prices.index.strftime("%Y-%m-%d").tolist(),
        "close": _sig(close.to_numpy(), 7),
        "lines": {str(w): _sig(compute_ma(close, w, ma_type).to_numpy(), 7) for w in mas},
    }


# ------------------------------------------------------------------ main analysis
def analyze_ticker(cfg: dict, ticker: str) -> dict:
    t0 = time.time()
    with LOCK:
        prices = load_asset(cfg, ticker)
        mas = [cfg["target"]] + cfg["controls"]
        if len(prices) < max(mas) + 100:
            raise ConfigError(
                f"{ticker} has only {len(prices):,} bars; the longest line ({max(mas)}) needs at "
                "least that plus 100. Shorten the lines or widen the date range."
            )
        try:
            how = setup_eras(cfg, prices)
            base_era, late_era = _resolve_eras(cfg)
        except ValueError as exc:
            raise ConfigError(f"{ticker}: {exc}") from None

        horizons = cfg["horizons"]
        baselines = build_baselines(prices["Close"], tuple(horizons), cfg["pre"], cfg["post"])
        frames, skipped = [], []
        for ma in mas:
            ev = _detect(cfg, prices, ma, baselines)
            if len(ev):
                frames.append(ev)
            elif ma == cfg["target"]:
                raise ConfigError(
                    f"{ticker}: no touch events for the {ma}-bar line with these settings "
                    "(try a wider band or a shorter approach window)."
                )
            else:
                skipped.append(ma)
        events = pd.concat(frames).reset_index()
        live_controls = [c for c in cfg["controls"] if c not in skipped]
        live_mas = [cfg["target"]] + live_controls

        comparisons, expansion = {}, {}
        for c in live_controls:
            pair = events[events["ma"].isin([cfg["target"], c])]
            comparisons[str(c)] = compare(pair, cfg["target"], c, horizons, cfg["bootstrap"], cfg["seed"])
            expansion[str(c)] = era_expansion(
                pair, cfg["target"], c, horizons, cfg["bootstrap"], cfg["seed"], base_era, late_era
            )

        eras = [{"name": e, "desc": ERA_DESC[e]} for e in ERA_ORDER]
        result = {
            "ticker": ticker,
            "label": "Synthetic null random walk" if ticker == SYNTHETIC else ticker,
            "span": {
                "start": prices.index[0].strftime("%Y-%m-%d"),
                "end": prices.index[-1].strftime("%Y-%m-%d"),
                "bars": len(prices),
            },
            "era_mode": how,
            "eras": eras,
            "era_ends": list(ERA_CONFIG["ends"]),
            "base_era": base_era,
            "late_era": late_era,
            "mas": live_mas,
            "skipped_controls": skipped,
            "warnings": _warnings(cfg, ticker, prices, events, live_mas),
            "counts": event_counts(events, live_mas),
            "summary": summarize(events, live_mas, horizons),
            "range": _range_table(events, live_mas),
            "comparisons": comparisons,
            "expansion": expansion,
            "paths": _paths(events, live_mas, cfg["pre"], cfg["post"]),
            "price": _price_payload(prices, live_mas, cfg["ma_type"]),
            "events": _events_payload(events, horizons),
            "seconds": round(time.time() - t0, 2),
        }
        return to_py(result)


def analyze(raw_cfg: dict | None) -> dict:
    """Run every requested asset; one failing asset never sinks the others."""
    cfg = parse_config(raw_cfg)
    t0 = time.time()
    results, errors = [], {}
    for ticker in cfg["tickers"]:
        try:
            results.append(analyze_ticker(cfg, ticker))
        except ConfigError as exc:
            errors[ticker] = str(exc)
    return {"config": cfg, "results": results, "errors": errors, "seconds": round(time.time() - t0, 2)}


# ------------------------------------------------------------------ event explorer
def event_window(raw_cfg: dict, ticker: str, ma: int, date: str, direction: str,
                 before: int = 40, after: int = 25) -> dict:
    """Candles + MA + band + breach level around one event, for the explorer chart."""
    cfg = parse_config({**raw_cfg, "tickers": [ticker]})
    before, after = max(5, min(int(before), 120)), max(5, min(int(after), 120))
    with LOCK:
        prices = load_asset(cfg, ticker)
        f = add_indicators(prices, int(ma), cfg["atr_window"], 20, cfg["ma_type"])
        ts = pd.Timestamp(date)
        if ts not in f.index:
            raise ConfigError(f"no bar on {date}")
        i = f.index.get_loc(ts)
        lo, hi = max(0, i - before), min(len(f), i + after + 1)
        w = f.iloc[lo:hi]
        atr_event = float(f["atr"].iloc[i])
        sign = 1.0 if direction == "support" else -1.0
        out = {
            "dates": w.index.strftime("%Y-%m-%d").tolist(),
            "open": _sig(w["Open"].to_numpy(), 7),
            "high": _sig(w["High"].to_numpy(), 7),
            "low": _sig(w["Low"].to_numpy(), 7),
            "close": _sig(w["Close"].to_numpy(), 7),
            "sma": _sig(w["sma"].to_numpy(), 7),
            "upper": _sig((w["sma"] + cfg["band"] * atr_event).to_numpy(), 7),
            "lower": _sig((w["sma"] - cfg["band"] * atr_event).to_numpy(), 7),
            "breach": _sig((w["sma"] - sign * cfg["breach"] * atr_event).to_numpy(), 7),
            "event_index": int(i - lo),
            "atr_event": atr_event,
            "horizons": cfg["horizons"],
        }
        return to_py(out)


# ------------------------------------------------------------------ MA window scan
def _agg(sub: pd.DataFrame, horizons: list[int]) -> dict:
    n = len(sub)
    return {
        "n": n,
        "bounce": {str(k): (sub[f"bounce_{k}"].mean() if n else None) for k in horizons},
        "car": {str(k): (sub[f"car_{k}"].mean() if n else None) for k in horizons},
    }


def scan(raw_cfg: dict, ticker: str, wmin: int, wmax: int, step: int) -> dict:
    """Event-study metrics for every line length in a grid.

    This answers "is the target special, or would any line look like this?" by placing the
    target inside the distribution of all other windows.
    """
    cfg = parse_config({**raw_cfg, "tickers": [ticker]})
    wmin, wmax, step = int(wmin), int(wmax), int(step)
    if not (2 <= wmin < wmax <= LIMITS["max_window"]) or step < 1:
        raise ConfigError(f"scan range must satisfy 2 <= min < max <= {LIMITS['max_window']}, step >= 1")
    windows = sorted(set(range(wmin, wmax + 1, step)) | {cfg["target"]})
    if len(windows) > LIMITS["max_scan_windows"]:
        raise ConfigError(f"scan limited to {LIMITS['max_scan_windows']} windows; increase the step")
    t0 = time.time()
    with LOCK:
        prices = load_asset(cfg, ticker)
        if len(prices) < max(windows) + 100:
            windows = [w for w in windows if w + 100 <= len(prices)]
            if cfg["target"] not in windows:
                raise ConfigError("not enough history for the target line")
        setup_eras(cfg, prices)
        horizons = cfg["horizons"]
        baselines = build_baselines(prices["Close"], tuple(horizons), cfg["pre"], cfg["post"])
        names = list(ERA_ORDER) + [ERA_ALL]
        out = {e: [] for e in names}
        for w in windows:
            ev = _detect(cfg, prices, w, baselines)
            for e in names:
                sub = ev if e == ERA_ALL else ev[ev["era"] == e]
                out[e].append(_agg(sub, horizons))
        return to_py(
            {
                "ticker": ticker,
                "windows": windows,
                "target": cfg["target"],
                "controls": cfg["controls"],
                "horizons": horizons,
                "eras": [{"name": e, "desc": ERA_DESC[e]} for e in names],
                "metrics": out,
                "ma_type": cfg["ma_type"],
                "seconds": round(time.time() - t0, 2),
            }
        )
