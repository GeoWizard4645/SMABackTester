"""Touch-event detection and reactivity measurement for one moving average."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from metrics import add_indicators, offset_returns
from stats import assign_era


@dataclass(frozen=True)
class EventConfig:
    ma_window: int
    atr_window: int = 14
    band_mult: float = 0.5  # touch band half-width, in ATRs
    breach_mult: float = 1.5  # failure level distance from the SMA, in ATRs
    approach_days: int = 5  # prior closes that must all be on one side of the SMA
    refractory_days: int = 10  # de-clustering window between accepted events
    horizons: tuple[int, ...] = (1, 3, 5, 10)
    pre: int = 5  # event-study window start (t-pre)
    post: int = 10  # event-study window end (t+post)
    baseline_window: int = 20  # lookback for the range-expansion baseline
    breach_basis: str = "close"  # "close" or "low" (support) / "high" (resistance)


@dataclass(frozen=True)
class Baselines:
    """Unconditional mean returns per era, used as the 'normal' benchmark."""

    forward: pd.DataFrame  # index = era, columns = horizons: mean Close[t+k]/Close[t]-1
    path: pd.DataFrame  # index = era, columns = offsets: mean Close[t+j]/Close[t-pre]-1


def cum_col(j: int) -> str:
    return f"cum_{j}"


def build_baselines(close: pd.Series, horizons: tuple[int, ...], pre: int, post: int) -> Baselines:
    """Unconditional forward / path returns over ALL days, averaged within each era.

    Computed once from the price series alone so the target and control MAs are
    benchmarked against exactly the same baseline.
    """
    eras = assign_era(close.index).to_numpy()
    fwd = offset_returns(close, horizons, base=0).groupby(eras).mean()
    path = offset_returns(close, range(-pre, post + 1), base=-pre).groupby(eras).mean()
    return Baselines(forward=fwd, path=path)


def _event_columns(cfg: EventConfig) -> list[str]:
    cols = [
        "ma", "direction", "sign", "era", "year", "close", "sma", "atr",
        "dist_pct", "dist_atr", "atr_ratio", "tr_ratio",
    ]
    cols += [f"ret_{k}" for k in cfg.horizons]
    cols += [f"car_{k}" for k in cfg.horizons]
    cols += [f"bounce_{k}" for k in cfg.horizons]
    cols += [cum_col(j) for j in range(-cfg.pre, cfg.post + 1)]
    return cols


def detect_events(prices: pd.DataFrame, cfg: EventConfig, baselines: Baselines) -> pd.DataFrame:
    """Find isolated SMA touches and measure the reaction after each.

    Definitions (band = SMA_t +/- band_mult * ATR_t):
      * Support test:    previous ``approach_days`` closes were each strictly
                         above their same-day SMA AND Low_t <= SMA_t + band.
      * Resistance test: previous ``approach_days`` closes were each strictly
                         below their same-day SMA AND High_t >= SMA_t - band.
      * De-clustering:   a candidate is dropped if an accepted event occurred
                         within the previous ``refractory_days`` trading days
                         (any direction), so forward windows never overlap.

    Reaction metrics (all measured from Close_t, so no look-ahead into t's
    outcome beyond the information available at the close of day t):
      * ret_k    raw return Close[t+k]/Close[t]-1
      * car_k    direction-adjusted abnormal return, sign * (ret_k - era baseline);
                 sign=+1 for support, -1 for resistance, so positive always means
                 "price reacted the way a support/resistance level predicts"
      * bounce_k support: Close[t+k] > Close[t] and no close in [t, t+k] fell below
                 SMA - breach_mult*ATR_t (mirror image for resistance); NaN if the
                 window runs past the end of the data
      * cum_j    raw abnormal cumulative return from Close[t-pre] to Close[t+j]
                 (for event-study plots; apply ``sign`` to direction-adjust)
    """
    f = add_indicators(prices, cfg.ma_window, cfg.atr_window, cfg.baseline_window)
    close_s = f["Close"]
    close = close_s.to_numpy()
    sma = f["sma"].to_numpy()
    atr = f["atr"].to_numpy()
    n = len(f)

    valid = f["sma"].notna() & f["atr"].notna()
    above = (close_s > f["sma"]).astype(int)
    below = (close_s < f["sma"]).astype(int)
    m = cfg.approach_days
    prior_above = above.rolling(m).sum().shift(1) == m
    prior_below = below.rolling(m).sum().shift(1) == m
    upper = f["sma"] + cfg.band_mult * f["atr"]
    lower = f["sma"] - cfg.band_mult * f["atr"]
    support = valid & prior_above & (f["Low"] <= upper)
    resistance = valid & prior_below & (f["High"] >= lower)

    accepted: list[int] = []
    last = -10**9
    for i in np.flatnonzero((support | resistance).to_numpy()):
        if i - last > cfg.refractory_days:
            accepted.append(int(i))
            last = int(i)

    if not accepted:
        return pd.DataFrame(columns=_event_columns(cfg)).rename_axis("date")

    idx = np.array(accepted)
    dates = f.index[idx]
    sign = np.where(support.to_numpy()[idx], 1, -1)
    eras = assign_era(dates).to_numpy()

    horizons = list(cfg.horizons)
    fwd = offset_returns(close_s, horizons, base=0).to_numpy()[idx]
    fwd_base = baselines.forward.reindex(eras)[horizons].to_numpy()
    car = sign[:, None] * (fwd - fwd_base)

    offsets = list(range(-cfg.pre, cfg.post + 1))
    path = offset_returns(close_s, offsets, base=-cfg.pre).to_numpy()[idx]
    path = path - baselines.path.reindex(eras)[offsets].to_numpy()

    if cfg.breach_basis == "close":
        px_sup = px_res = close
    elif cfg.breach_basis == "low":
        px_sup, px_res = f["Low"].to_numpy(), f["High"].to_numpy()
    else:
        raise ValueError("breach_basis must be 'close' or 'low'")

    bounce = np.full((len(idx), len(horizons)), np.nan)
    for r, i in enumerate(idx):
        for c, k in enumerate(horizons):
            if i + k >= n:
                continue
            win = slice(i, i + k + 1)
            if sign[r] > 0:
                breached = np.any(px_sup[win] < sma[win] - cfg.breach_mult * atr[i])
                hit = close[i + k] > close[i]
            else:
                breached = np.any(px_res[win] > sma[win] + cfg.breach_mult * atr[i])
                hit = close[i + k] < close[i]
            bounce[r, c] = float(hit and not breached)

    out = pd.DataFrame(
        {
            "ma": cfg.ma_window,
            "direction": np.where(sign > 0, "support", "resistance"),
            "sign": sign,
            "era": eras,
            "year": dates.year,
            "close": close[idx],
            "sma": sma[idx],
            "atr": atr[idx],
            "dist_pct": f["dist_pct"].to_numpy()[idx],
            "dist_atr": f["dist_atr"].to_numpy()[idx],
            "atr_ratio": f["atr_ratio"].to_numpy()[idx],
            "tr_ratio": f["tr_ratio"].to_numpy()[idx],
        },
        index=dates,
    )
    for c, k in enumerate(horizons):
        out[f"ret_{k}"] = fwd[:, c]
        out[f"car_{k}"] = car[:, c]
        out[f"bounce_{k}"] = bounce[:, c]
    for c, j in enumerate(offsets):
        out[cum_col(j)] = path[:, c]
    out.index.name = "date"
    return out
