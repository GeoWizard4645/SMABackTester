"""Kalshi lab tests.   pytest -q"""

import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kalshi_lab import backtest, calibration, kalshi_data, stats, web


@pytest.mark.parametrize("price,fee", [(50, 2), (1, 1), (99, 1), (10, 1), (25, 2), (90, 1), (75, 2), (5, 1)])
def test_fee_schedule(price, fee):
    assert backtest.kalshi_fee_cents(price) == fee


def test_fee_is_symmetric_and_scales_with_contracts():
    for p in range(1, 100):
        assert backtest.kalshi_fee_cents(p) == backtest.kalshi_fee_cents(100 - p)
    assert backtest.kalshi_fee_cents(50, 100) == 175  # 0.07 * 100 * 0.25 = $1.75
    assert backtest.kalshi_fee_cents(50, 1, rate=0) == 0


def frame(rows):
    df = pd.DataFrame(rows, columns=["yes_price", "result", "direction"])
    df["yes_bid"], df["yes_ask"] = df.yes_price - 1, df.yes_price + 1
    df["ticker"] = [f"T{i}" for i in range(len(df))]
    df["close_time"] = pd.date_range("2026-01-01", periods=len(df), freq="15min")
    return df


def test_buy_no_pnl_arithmetic():
    f = frame([(30, 0, "upside"), (30, 1, "upside")])
    t = backtest.run_rule(f, backtest.Rule("all", "no"))
    # entry 70c, fee ceil(7*.7*.3)=ceil(1.47)=2c. Win: +30 gross; lose: -70 gross.
    assert t["entry"].tolist() == [70, 70] and t["fee"].tolist() == [2, 2]
    assert t["gross"].tolist() == [30, -70] and t["net"].tolist() == [28, -72]
    m = stats.strategy_metrics(t)
    assert m["trades"] == 2 and m["wins"] == 1 and m["net_profit"] == pytest.approx(-0.44)
    assert m["gross_profit"] == pytest.approx(-0.40) and m["fees"] == pytest.approx(0.04)


def test_executable_price_uses_the_ask():
    f = frame([(30, 0, "upside")])
    mid = backtest.run_rule(f, backtest.Rule("x", "no"), "trade")
    exe = backtest.run_rule(f, backtest.Rule("x", "no"), "executable")
    assert mid["entry"].iloc[0] == 70 and exe["entry"].iloc[0] == 71  # No ask = 100 - Yes bid(29)


def test_rule_filters():
    f = frame([(15, 0, "upside"), (35, 0, "upside"), (60, 1, "downside")])
    assert len(backtest.run_rule(f, backtest.Rule("r", "no", "upside"))) == 2
    assert len(backtest.run_rule(f, backtest.Rule("r", "no", None, 20, 50))) == 1
    assert len(backtest.run_rule(f, backtest.Rule("r", "yes", "downside"))) == 1


def test_calibration_bins_and_gap():
    rng = np.random.default_rng(1)
    prices = rng.uniform(10, 90, 4000)
    results = (rng.uniform(0, 100, 4000) < prices).astype(int)  # perfectly calibrated
    df = pd.DataFrame({"yes_price": prices, "result": results, "direction": "upside"})
    t = calibration.calibrate(df, "all", p_test="pbinom")
    assert len(t["rows"]) == 8 and sum(r["count"] for r in t["rows"]) == 4000
    assert abs(t["overall"]["gap"]) < 3 and t["overall"]["p_value"] > 0.01
    # Plant 5c overpricing
    over = pd.DataFrame({"yes_price": prices, "result": (rng.uniform(0, 100, 4000) < prices - 5).astype(int), "direction": "upside"})
    assert calibration.calibrate(over, "all", p_test="pbinom")["overall"]["p_value"] < 1e-6


def test_p_tests_agree_on_direction():
    prices, outcomes = np.full(500, 60.0), np.r_[np.ones(250), np.zeros(250)]
    for m in stats.P_TESTS:
        assert stats.implied_vs_realized_p(prices, outcomes, m) < 0.01
    with pytest.raises(ValueError):
        stats.implied_vs_realized_p(prices, outcomes, "nope")


def test_synthetic_is_deterministic_and_has_schema():
    a = kalshi_data.synthetic("KXBTC15M", datetime(2026, 1, 1), datetime(2026, 1, 3), (10, 5), seed=3)
    b = kalshi_data.synthetic("KXBTC15M", datetime(2026, 1, 1), datetime(2026, 1, 3), (10, 5), seed=3)
    pd.testing.assert_frame_equal(a, b)
    assert {"ticker", "strike", "result", "trade_5", "bid_5", "ask_5", "spot_5", "spot_open"} <= set(a.columns)
    assert len(a) == 2 * 96 - 1 or len(a) >= 190
    frame = kalshi_data.analysis_frame(a, 5)
    assert set(frame["direction"]) <= {"upside", "downside", "at"} and frame["yes_price"].between(1, 99).all()


def test_synthetic_null_vs_planted_bias():
    null = kalshi_data.synthetic("KXBTC15M", datetime(2026, 1, 1), datetime(2026, 3, 1), (5,), seed=5, bias=0, upside_extra=0, noise=0.01)
    planted = kalshi_data.synthetic("KXBTC15M", datetime(2026, 1, 1), datetime(2026, 3, 1), (5,), seed=5, bias=6, upside_extra=0)
    gap = lambda d: kalshi_data.analysis_frame(d, 5, "mid").pipe(lambda f: f.yes_price.mean() - 100 * f.result.mean())
    assert gap(planted) - gap(null) > 3


def test_web_run_lab_json_safe():
    import json

    r = web.run_lab({"source": "synthetic", "days": 5, "seed": 2})
    json.dumps(r, allow_nan=False)
    assert r["summary"]["source"] == "synthetic" and len(r["strategies"]) == 3
    with pytest.raises(ValueError):
        web.run_lab({"min_price": 80, "max_price": 20})


def test_console_captures_output_errors_and_state():
    web.run_lab({"source": "synthetic", "days": 3})
    out = web.run_code("print(len(frame) > 0)")
    assert out["stdout"].strip() == "True" and not out["error"]
    bad = web.run_code("1/0")
    assert "ZeroDivisionError" in bad["error"]
    web.reset_console()
