"""Core maths and event-detection tests.   pytest -q"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import events as ev
import metrics
import stats
from data import _clean, parse_yahoo_chart


def series(values):
    return pd.Series(values, index=pd.date_range("2000-01-03", periods=len(values), freq="B"), dtype=float)


def test_moving_averages_match_definitions():
    c = series(range(1, 11))
    assert metrics.compute_sma(c, 3).iloc[2] == pytest.approx(2.0)
    assert metrics.compute_wma(c, 3).iloc[2] == pytest.approx((3 * 3 + 2 * 2 + 1 * 1) / 6)
    ema = metrics.compute_ema(c, 3)
    assert ema.iloc[2] == pytest.approx(2.25)  # alpha=.5 seeded with the first close
    assert metrics.compute_sma(c, 3).iloc[:2].isna().all()
    with pytest.raises(ValueError):
        metrics.compute_ma(c, 3, "hma")


def test_true_range_and_atr():
    df = pd.DataFrame({"High": [10, 12, 11], "Low": [9, 10, 8], "Close": [9.5, 11, 9]}, index=pd.date_range("2000-01-03", periods=3))
    tr = metrics.true_range(df.High, df.Low, df.Close)
    assert tr.tolist() == [1.0, 2.5, 3.0]  # day 2: |12-9.5|; day 3: |8-11|


def test_wilson_ci_known_value():
    lo, hi = stats.wilson_ci(7, 20)
    assert (lo, hi) == pytest.approx((0.1812, 0.5671), abs=1e-3)
    assert stats.wilson_ci(0, 0) == (pytest.approx(float("nan"), nan_ok=True),) * 2


def test_era_assignment_and_configuration():
    stats.configure_eras([1990, 2007], 1950, 2026)
    idx = pd.to_datetime(["1990-12-31", "1991-01-02", "2007-12-31", "2008-01-02"])
    assert stats.assign_era(idx).tolist() == ["Era 1", "Era 2", "Era 2", "Era 3"]
    stats.configure_eras([1960, 1970, 1980], 1950, 2026)
    assert stats.ERA_ORDER == ["Era 1", "Era 2", "Era 3", "Era 4"]
    with pytest.raises(ValueError):
        stats.configure_eras([2000, 1990], 1950, 2026)
    stats.configure_eras([1990, 2007], 1950, 2026)  # restore


def test_auto_era_bounds_equal_thirds():
    idx = pd.date_range("2010-01-01", "2021-12-31", freq="B")
    assert stats.auto_era_bounds(idx, 3) == [2013, 2017]
    with pytest.raises(ValueError):
        stats.auto_era_bounds(pd.date_range("2020-01-01", "2020-12-31", freq="B"), 3)


def crafted_prices():
    """Flat 100 for 260 bars, a dip into the line at bar 261, then a rally: exactly one support touch."""
    n = 330
    close = np.full(n, 100.0)
    close[:200] += np.linspace(-0.5, 0.0, 200)  # tiny drift so ATR > 0
    close[200:260] = 101 + np.sin(np.arange(60)) * 0.2  # above the (≈100) line
    close[260] = 100.2
    close[261:] = 103 + np.arange(n - 261) * 0.1
    idx = pd.date_range("2000-01-03", periods=n, freq="B")
    high, low = close + 0.3, close - 0.3
    low[260] = 99.0  # the touch day dips into the band
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close}, index=idx)


def test_event_detection_on_crafted_series():
    stats.configure_eras([2000], 1999, 2003)
    px = crafted_prices()
    base = ev.build_baselines(px["Close"], (1, 3), 5, 10)
    out = ev.detect_events(px, ev.EventConfig(ma_window=50, horizons=(1, 3)), base)
    assert len(out) >= 1
    first = out.iloc[0]
    assert first["direction"] == "support" and first["sign"] == 1
    assert first["ret_3"] > 0 and first["bounce_3"] == 1.0
    # refractory rule: accepted events are >10 bars apart
    pos = [px.index.get_loc(d) for d in out.index]
    assert all(b - a > 10 for a, b in zip(pos, pos[1:]))
    stats.configure_eras([1990, 2007], 1950, 2026)


def test_cluster_bootstrap_needs_enough_years():
    ya = np.array([2000, 2001, 2002]); va = np.array([1.0, 0.0, 1.0])
    obs, draws = stats._cluster_diff_draws(ya, va, ya, va, 100, np.random.default_rng(0))
    assert obs == pytest.approx(0.0) and np.isnan(draws).all()


def test_parse_yahoo_chart_adjusts_and_cleans():
    payload = {"chart": {"result": [{"meta": {"gmtoffset": -14400}, "timestamp": [1700000000, 1700086400, 1700172800],
        "indicators": {"quote": [{"open": [10, 11, 12], "high": [11, 12, 13], "low": [9, 10, 11], "close": [10, 11, None]}],
                       "adjclose": [{"adjclose": [5, 5.5, None]}]}}], "error": None}}
    df = parse_yahoo_chart(payload)
    assert len(df) == 2 and df["Close"].tolist() == [5.0, 5.5]  # adjusted by adjclose/close = 0.5; None row dropped
    assert df["High"].iloc[0] == pytest.approx(5.5)
    with pytest.raises(RuntimeError):
        parse_yahoo_chart({"chart": {"result": None, "error": {"description": "nope"}}})


def test_service_config_validation():
    import service

    cfg = service.parse_config({"tickers": ["aapl", "AAPL", "BTC-USD"], "controls": [174, 200, 150], "target": 200})
    assert cfg["tickers"] == ["aapl", "AAPL", "BTC-USD"] or len(cfg["tickers"]) == 3
    assert cfg["controls"] == [174, 150]  # target removed
    for bad in ({"tickers": ["../etc"]}, {"target": 1}, {"horizons": []}, {"eras": {"mode": "x"}}, {"direction": "x"}):
        with pytest.raises(service.ConfigError):
            service.parse_config(bad)


def test_service_end_to_end_on_synthetic():
    import service

    res = service.analyze({"tickers": ["SYNTHETIC"], "start": "1990-01-01", "end": "2020-01-01", "controls": [150], "bootstrap": 200,
                           "eras": {"mode": "custom", "ends": [2000, 2010]}})
    assert not res["errors"], res["errors"]
    r = res["results"][0]
    assert [e["name"] for e in r["eras"]] == ["Era 1", "Era 2", "Era 3"]
    assert "150" in r["comparisons"] and r["events"]
    import json
    json.dumps(res, allow_nan=False)  # fully JSON-safe
