"""Era segmentation, confidence intervals, hypothesis tests, regression, bootstrap."""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats as sst

ERA_ORDER = ["Era 1", "Era 2", "Era 3"]
ERA_ALL = "All"
ERA_DESC = {
    "Era 1": "1950-1990",
    "Era 2": "1991-2007",
    "Era 3": "2008-present",
    ERA_ALL: "full sample",
}


# --------------------------------------------------------------------------- eras
def assign_era(index: pd.DatetimeIndex) -> pd.Series:
    """Label each date with its market regime (by calendar year)."""
    years = pd.DatetimeIndex(index).year
    labels = np.where(years <= 1990, "Era 1", np.where(years <= 2007, "Era 2", "Era 3"))
    return pd.Series(labels, index=index, name="era")


# ------------------------------------------------------------ interval estimates
def wilson_ci(successes: float, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (np.nan, np.nan)
    z = sst.norm.ppf(1 - (1 - conf) / 2)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mean_ci(x: np.ndarray, conf: float = 0.95) -> tuple[float, float]:
    """Student-t interval for a mean."""
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    m = float(np.mean(x))
    se = float(np.std(x, ddof=1)) / np.sqrt(n)
    h = sst.t.ppf(1 - (1 - conf) / 2, n - 1) * se
    return (m - h, m + h)


# ----------------------------------------------------------------- descriptives
def _select(events: pd.DataFrame, ma: int | None, era: str) -> pd.DataFrame:
    sub = events
    if ma is not None:
        sub = sub[sub["ma"] == ma]
    if era != ERA_ALL:
        sub = sub[sub["era"] == era]
    return sub


def event_counts(events: pd.DataFrame, mas: Sequence[int]) -> pd.DataFrame:
    """Events per MA / era / approach direction."""
    rows = []
    for ma in mas:
        for era in ERA_ORDER + [ERA_ALL]:
            sub = _select(events, ma, era)
            rows.append(
                {
                    "ma": ma,
                    "era": era,
                    "total": len(sub),
                    "support": int((sub["direction"] == "support").sum()),
                    "resistance": int((sub["direction"] == "resistance").sum()),
                }
            )
    return pd.DataFrame(rows)


def summarize(
    events: pd.DataFrame, mas: Sequence[int], horizons: Sequence[int], conf: float = 0.95
) -> pd.DataFrame:
    """Bounce rate (Wilson CI) and mean/SD/CI of directional CAR per MA, era, horizon."""
    rows = []
    for ma in mas:
        for era in ERA_ORDER + [ERA_ALL]:
            sub = _select(events, ma, era)
            for k in horizons:
                b = sub[f"bounce_{k}"].dropna().to_numpy()
                c = sub[f"car_{k}"].dropna().to_numpy()
                lo, hi = wilson_ci(b.sum(), len(b), conf)
                clo, chi = mean_ci(c, conf)
                rows.append(
                    {
                        "ma": ma,
                        "era": era,
                        "horizon": k,
                        "n": len(b),
                        "bounce_rate": b.mean() if len(b) else np.nan,
                        "bounce_lo": lo,
                        "bounce_hi": hi,
                        "car_mean": c.mean() if len(c) else np.nan,
                        "car_std": c.std(ddof=1) if len(c) > 1 else np.nan,
                        "car_lo": clo,
                        "car_hi": chi,
                    }
                )
    return pd.DataFrame(rows)


# ------------------------------------------------------------- hypothesis tests
def _two_sample_tests(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    out = {"t_p": np.nan, "welch_p": np.nan, "mwu_p": np.nan}
    if len(a) < 2 or len(b) < 2:
        return out
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        out["t_p"] = float(sst.ttest_ind(a, b, equal_var=True).pvalue)
        out["welch_p"] = float(sst.ttest_ind(a, b, equal_var=False).pvalue)
        try:
            out["mwu_p"] = float(sst.mannwhitneyu(a, b, alternative="two-sided").pvalue)
        except ValueError:  # e.g. all values identical
            pass
    return out


def _cluster_diff_draws(
    years_a: np.ndarray,
    vals_a: np.ndarray,
    years_b: np.ndarray,
    vals_b: np.ndarray,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[float, np.ndarray]:
    """Cluster (calendar-year) bootstrap of mean(a) - mean(b).

    Whole years are resampled with replacement, keeping both MAs' events from a
    given year together. This respects (i) serial dependence of events inside
    a year and (ii) the strong cross-MA dependence that arises because the 200d
    and control SMAs are tested against the same price path.
    Returns (observed difference, array of bootstrap differences).
    """
    if len(vals_a) == 0 or len(vals_b) == 0:
        return np.nan, np.full(n_boot, np.nan)
    lo = int(min(years_a.min(), years_b.min()))
    hi = int(max(years_a.max(), years_b.max()))
    g = hi - lo + 1
    sa = np.bincount(years_a - lo, weights=vals_a, minlength=g)
    na = np.bincount(years_a - lo, minlength=g).astype(float)
    sb = np.bincount(years_b - lo, weights=vals_b, minlength=g)
    nb = np.bincount(years_b - lo, minlength=g).astype(float)
    obs = sa.sum() / na.sum() - sb.sum() / nb.sum()
    idx = rng.integers(0, g, size=(n_boot, g))
    bsa, bna = sa[idx].sum(axis=1), na[idx].sum(axis=1)
    bsb, bnb = sb[idx].sum(axis=1), nb[idx].sum(axis=1)
    with np.errstate(all="ignore"):
        draws = bsa / bna - bsb / bnb
    draws[(bna == 0) | (bnb == 0)] = np.nan
    return float(obs), draws


def _boot_summary(obs: float, draws: np.ndarray, conf: float = 0.95) -> tuple[float, float, float]:
    """Percentile CI and recentred two-sided bootstrap p-value (H0: difference = 0)."""
    d = draws[~np.isnan(draws)]
    if len(d) < 100 or np.isnan(obs):
        return (np.nan, np.nan, np.nan)
    a = (1 - conf) / 2
    lo, hi = np.quantile(d, [a, 1 - a])
    p = (1 + np.sum(np.abs(d - obs) >= abs(obs))) / (len(d) + 1)
    return (float(lo), float(hi), float(min(1.0, p)))


def _metric_specs(horizons: Sequence[int]) -> list[tuple[str, str, int]]:
    specs: list[tuple[str, str, int]] = []
    for k in horizons:
        specs.append(("bounce", f"bounce_{k}", k))
        specs.append(("car", f"car_{k}", k))
    specs.append(("atr_ratio", "atr_ratio", 0))
    specs.append(("tr_ratio", "tr_ratio", 0))
    return specs


def _arrays(sub: pd.DataFrame, col: str) -> tuple[np.ndarray, np.ndarray]:
    s = sub[["year", col]].dropna()
    return s["year"].to_numpy(dtype=int), s[col].to_numpy(dtype=float)


def compare(
    events: pd.DataFrame,
    target: int,
    control: int,
    horizons: Sequence[int],
    n_boot: int = 5000,
    seed: int = 0,
) -> pd.DataFrame:
    """Target-vs-control comparison of every metric, by era.

    For each (era, metric): difference in means (target - control), Student t,
    Welch t, Mann-Whitney U, and a cluster-bootstrap CI / p-value.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for era in ERA_ORDER + [ERA_ALL]:
        for name, col, k in _metric_specs(horizons):
            ya, va = _arrays(_select(events, target, era), col)
            yb, vb = _arrays(_select(events, control, era), col)
            obs, draws = _cluster_diff_draws(ya, va, yb, vb, n_boot, rng)
            blo, bhi, bp = _boot_summary(obs, draws)
            rows.append(
                {
                    "era": era,
                    "metric": name,
                    "horizon": k,
                    "n_target": len(va),
                    "n_control": len(vb),
                    "mean_target": va.mean() if len(va) else np.nan,
                    "mean_control": vb.mean() if len(vb) else np.nan,
                    "diff": obs,
                    **_two_sample_tests(va, vb),
                    "boot_lo": blo,
                    "boot_hi": bhi,
                    "boot_p": bp,
                }
            )
    return pd.DataFrame(rows)


# -------------------------------------------------------------------- regression
def ols_cluster(
    y: np.ndarray, X: np.ndarray, groups: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OLS with CR1 cluster-robust standard errors; p-values use t(G-1)."""
    n, k = X.shape
    nan = np.full(k, np.nan)
    uniq = np.unique(groups)
    g = len(uniq)
    if g < 2 or n <= k or np.linalg.matrix_rank(X) < k:
        return nan, nan, nan
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    scores = pd.DataFrame(X * resid[:, None]).groupby(groups).sum().to_numpy()
    meat = scores.T @ scores
    c = g / (g - 1) * (n - 1) / (n - k)
    cov = c * xtx_inv @ meat @ xtx_inv
    se = np.sqrt(np.diag(cov))
    with np.errstate(all="ignore"):
        t = beta / se
    p = 2 * sst.t.sf(np.abs(t), g - 1)
    return beta, se, p


def did_regression(
    events: pd.DataFrame,
    target: int,
    control: int,
    col: str,
    base_era: str = "Era 1",
    late_era: str = "Era 3",
) -> tuple[float, float, float]:
    """Difference-in-differences coefficient from a pooled interaction regression.

        y = b0 + b1*Target + b2*Era2 + b3*Era3 + b4*Target*Era2 + b5*Target*Era3 + e

    The coefficient on Target x late_era is the change in (target - control)
    reactivity between ``base_era`` and ``late_era``. SEs are clustered by
    calendar year. Returns (coefficient, se, p-value).
    """
    sub = events[events["ma"].isin([target, control])][["ma", "era", "year", col]].dropna()
    if (sub["era"] == base_era).sum() == 0 or (sub["era"] == late_era).sum() == 0:
        return (np.nan, np.nan, np.nan)
    is_t = (sub["ma"] == target).to_numpy(dtype=float)
    names = ["const", "target"]
    cols = [np.ones(len(sub)), is_t]
    for era in ERA_ORDER:
        if era == base_era or (sub["era"] == era).sum() == 0:
            continue
        d = (sub["era"] == era).to_numpy(dtype=float)
        names.append(era)
        cols.append(d)
    for era in ERA_ORDER:
        if era == base_era or (sub["era"] == era).sum() == 0:
            continue
        names.append(f"target:{era}")
        cols.append(is_t * (sub["era"] == era).to_numpy(dtype=float))
    X = np.column_stack(cols)
    beta, se, p = ols_cluster(sub[col].to_numpy(dtype=float), X, sub["year"].to_numpy())
    i = names.index(f"target:{late_era}")
    return (float(beta[i]), float(se[i]), float(p[i]))


def era_expansion(
    events: pd.DataFrame,
    target: int,
    control: int,
    horizons: Sequence[int],
    n_boot: int = 5000,
    seed: int = 0,
    base_era: str = "Era 1",
    late_era: str = "Era 3",
) -> pd.DataFrame:
    """Did (Metric_target - Metric_control) grow from ``base_era`` to ``late_era``?

    Reports the difference-in-differences with a stratified cluster bootstrap
    (years resampled independently within each era) and the clustered
    interaction regression.
    """
    rng = np.random.default_rng(seed + 1)
    rows = []
    for name, col, k in _metric_specs(horizons):
        if name in ("atr_ratio", "tr_ratio"):
            continue
        parts = {}
        for era in (base_era, late_era):
            ya, va = _arrays(_select(events, target, era), col)
            yb, vb = _arrays(_select(events, control, era), col)
            parts[era] = _cluster_diff_draws(ya, va, yb, vb, n_boot, rng)
        obs_b, dr_b = parts[base_era]
        obs_l, dr_l = parts[late_era]
        did = obs_l - obs_b
        blo, bhi, bp = _boot_summary(did, dr_l - dr_b)
        coef, se, p = did_regression(events, target, control, col, base_era, late_era)
        rows.append(
            {
                "metric": name,
                "horizon": k,
                "diff_base": obs_b,
                "diff_late": obs_l,
                "did": did,
                "boot_lo": blo,
                "boot_hi": bhi,
                "boot_p": bp,
                "reg_coef": coef,
                "reg_se": se,
                "reg_p": p,
            }
        )
    return pd.DataFrame(rows)
