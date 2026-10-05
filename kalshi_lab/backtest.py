"""Rule-based Buy-No (or Buy-Yes) backtester with Kalshi's quadratic taker fee."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

TAKER_FEE_RATE = 0.07


def kalshi_fee_cents(price_cents: float, contracts: int = 1, rate: float = TAKER_FEE_RATE) -> int:
    """Kalshi fee in cents: ceil(rate * contracts * P * (1 - P)) dollars, rounded up to the next cent.

    ``P`` is the contract price in DOLLARS (0-1). Per contract at 50c: 0.07 * 0.25 = $0.0175 -> 2c.
    The fee is charged on the entry price; settlement is free. Because the formula is
    symmetric in P, a No bought at 100-P pays the same fee as the Yes at P.
    """
    p = float(price_cents) / 100.0
    return int(math.ceil(round(rate * 100.0 * contracts * p * (1.0 - p), 8)))


@dataclass(frozen=True)
class Rule:
    name: str
    side: str = "no"  # 'no' or 'yes'
    direction: str | None = None  # None, 'upside' or 'downside'
    min_price: float = 0.0  # on the YES price, inclusive
    max_price: float = 100.0


def default_rules(min_price: float = 20, max_price: float = 50) -> list[Rule]:
    return [
        Rule("Rule 1: Buy No on everything", "no"),
        Rule("Rule 2: Buy No on upside strikes only", "no", "upside"),
        Rule(f"Rule 3: Buy No when Yes is {min_price:g}-{max_price:g}¢", "no", None, min_price, max_price),
    ]


def run_rule(frame: pd.DataFrame, rule: Rule, price_source: str = "trade", contracts: int = 1,
             fee_rate: float = TAKER_FEE_RATE) -> pd.DataFrame:
    """Trade list for one rule. All money columns are in cents.

    Entry (per contract): Buy No at 100 - Yes price; with price_source='executable' the No is
    bought at its ask (100 - Yes bid) instead, which includes the bid/ask spread.
    Payout: 100c per winning contract (No wins if the market settles No), else 0.
    """
    f = frame
    if rule.direction:
        f = f[f["direction"] == rule.direction]
    f = f[(f["yes_price"] >= rule.min_price) & (f["yes_price"] <= rule.max_price)]
    if f.empty:
        return _empty()
    if rule.side == "no":
        yes_ref = f["yes_bid"] if price_source == "executable" else f["yes_price"]
        entry = 100 - yes_ref
        won = f["result"] == 0
    else:
        entry = f["yes_ask"] if price_source == "executable" else f["yes_price"]
        won = f["result"] == 1
    entry = np.clip(np.floor(entry.to_numpy(dtype=float) + 0.5), 1, 99)
    ok = ~np.isnan(entry)
    f, entry, won = f[ok], entry[ok], won.to_numpy()[ok]
    cost = entry * contracts
    payout = np.where(won, 100.0 * contracts, 0.0)
    fee = np.array([kalshi_fee_cents(e, contracts, fee_rate) for e in entry], dtype=float)
    trades = pd.DataFrame({
        "ticker": f["ticker"].to_numpy(), "time": pd.to_datetime(f["close_time"]).to_numpy(), "side": rule.side,
        "yes_price": f["yes_price"].to_numpy(), "direction": f["direction"].to_numpy(),
        "entry": entry, "contracts": contracts, "cost": cost, "result": f["result"].to_numpy(),
        "won": won, "payout": payout, "gross": payout - cost, "fee": fee, "net": payout - cost - fee,
    })
    trades = trades.sort_values("time").reset_index(drop=True)
    trades["cum_net"] = trades["net"].cumsum() / 100.0
    return trades


def _empty() -> pd.DataFrame:
    cols = ["ticker", "time", "side", "yes_price", "direction", "entry", "contracts", "cost", "result", "won",
            "payout", "gross", "fee", "net", "cum_net"]
    return pd.DataFrame({c: [] for c in cols})


def run_rules(frame: pd.DataFrame, rules: list[Rule], **kw) -> dict[str, pd.DataFrame]:
    return {r.name: run_rule(frame, r, **kw) for r in rules}
