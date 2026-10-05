# SMABackTester

A statistical research pipeline that tests whether the **200-day Simple Moving Average (SMA) is a self-fulfilling support/resistance level**.

**Authors:** Vivaan Shahani & Ren Yamaki

---

## 1. The question

Traders widely watch the 200-day SMA. If enough of them buy when price falls to it and sell when price rises to it, the level could become a real support/resistance zone purely through coordination. This project turns that idea into three testable claims:

| # | Claim | How it is tested |
|---|-------|------------------|
| H1 | Price reacts to the 200-day SMA more than to a level that *nobody* watches | 200-day SMA vs. an arbitrary **control SMA** (default 174-day), identical event rules |
| H2 | "Reaction" means price turns away from the level, not through it | Bounce rate and abnormal forward return, direction-adjusted |
| H3 | The effect has grown in the modern algorithmic/retail era | Difference-in-differences between Era 3 (2008+) and Era 1 (1950-1990) |

The control SMA is the key design choice. Any moving average will "look like" support in hindsight, because a smoothed price line sits near where price has been. Only the *difference* between the 200-day and a comparable arbitrary SMA says anything about coordination.

The null hypothesis is that the 200-day SMA behaves exactly like the control SMA.

---

## 2. Project layout

| File | Role |
|------|------|
| `data.py` | Downloads daily OHLC from Yahoo Finance (`^GSPC` from 1950), caches it to `.cache/`, validates and cleans it. Also loads a user CSV or generates a synthetic null random walk. |
| `metrics.py` | SMA, True Range, Wilder ATR, distance-to-MA, range-expansion ratios, offset-return matrices. |
| `events.py` | Event ("touch") detection, de-clustering, and measurement of every reactivity metric for one MA. |
| `stats.py` | Era segmentation, confidence intervals, two-sample tests, cluster bootstrap, clustered regression. |
| `report.py` | ASCII console tables. |
| `plot.py` | `event_study_car.png` and `era_comparison.png`. |
| `main.py` | `argparse` command-line entry point that wires everything together. |

Data flow: `data` -> `metrics` -> `events` (one run per MA) -> `stats` -> `report` + `plot`.

---

## 3. The math

Notation: for trading day $t$, $O_t, H_t, L_t, C_t$ are open, high, low, close. $N$ is the SMA window.

### 3.1 Indicators

**Simple moving average** (includes the current bar):

$$\text{SMA}_t^{(N)} = \frac{1}{N}\sum_{i=0}^{N-1} C_{t-i}$$

**True range and Average True Range** (Wilder smoothing, 14 days):

$$\text{TR}_t = \max\big(H_t - L_t,\; |H_t - C_{t-1}|,\; |L_t - C_{t-1}|\big)$$

$$\text{ATR}_t = \text{ATR}_{t-1} + \tfrac{1}{14}\big(\text{TR}_t - \text{ATR}_{t-1}\big)$$

ATR is only used once 14 observations exist. It converts distances into volatility units, so a "close" approach means the same thing in calm and turbulent markets.

**Distance to the moving average:**

$$d_t = \frac{C_t - \text{SMA}_t}{\text{SMA}_t}, \qquad d^{\text{ATR}}_t = \frac{C_t - \text{SMA}_t}{\text{ATR}_t}$$

**Range expansion** compares event-day volatility with the *previous* 20 days (the event day is excluded from its own baseline):

$$\rho^{\text{ATR}}_t = \frac{\text{ATR}_t}{\frac{1}{20}\sum_{i=1}^{20}\text{ATR}_{t-i}}, \qquad \rho^{\text{TR}}_t = \frac{\text{TR}_t}{\frac{1}{20}\sum_{i=1}^{20}\text{TR}_{t-i}}$$

Wilder ATR moves slowly, so $\rho^{\text{ATR}}$ stays near 1. The raw true-range ratio $\rho^{\text{TR}}$ is reported too because it is a sharper measure of a one-day range blow-out.

### 3.2 Event definition ("touch")

The tolerance band around the SMA is

$$\big[\text{SMA}_t - 0.5\,\text{ATR}_t,\;\; \text{SMA}_t + 0.5\,\text{ATR}_t\big]$$

A touch must be an *approach* from a definite side, so each candidate requires that price had been on one side of the SMA for the previous 5 sessions.

- **Support test (from above):**
  $C_{t-i} > \text{SMA}_{t-i}$ for all $i = 1,\dots,5$, **and** $L_t \le \text{SMA}_t + 0.5\,\text{ATR}_t$ (the day's low reaches the band or goes through it).
- **Resistance test (from below):**
  $C_{t-i} < \text{SMA}_{t-i}$ for all $i = 1,\dots,5$, **and** $H_t \ge \text{SMA}_t - 0.5\,\text{ATR}_t$.

The two cases are mutually exclusive. Let $s_t = +1$ for a support test and $-1$ for a resistance test.

**De-clustering.** Price often hugs an MA for days, producing a string of near-identical events. Candidates are processed in time order and a candidate on day $i$ is accepted only if

$$i - i_{\text{last accepted}} > 10 \text{ trading days}$$

(either direction). This also guarantees the forward windows of consecutive events (up to 10 days) never overlap, which keeps observations closer to independent.

### 3.3 Reactivity metrics

All outcomes are measured from the **close of the event day** $C_t$, so nothing about day $t$'s own outcome leaks into entry.

**Forward return** for horizon $k \in \{1,3,5,10\}$:

$$R_{t\to t+k} = \frac{C_{t+k} - C_t}{C_t}$$

**Abnormal return.** Equities drift upward, so a raw positive return after a support test proves little. Each return is compared against the *unconditional* mean $k$-day return $\mu_k(e)$ over **all** trading days in the same era $e$ (computed once from price alone, so the 200-day and control SMAs share the identical benchmark):

$$\mu_k(e) = \operatorname*{mean}_{s \in e}\; R_{s\to s+k}$$

**Direction-adjusted forward CAR:**

$$\text{CAR}_k = s_t \cdot \big(R_{t\to t+k} - \mu_k(e_t)\big)$$

Multiplying by $s_t$ flips resistance tests, so a **positive CAR always means "price reacted the way a support/resistance level predicts"**, and the two directions can be pooled.

**Bounce.** For a support test, a bounce on horizon $k$ is

$$\mathbb{1}\Big[\,C_{t+k} > C_t \;\wedge\; C_u \ge \text{SMA}_u - 1.5\,\text{ATR}_t \;\;\forall u \in [t, t+k]\,\Big]$$

That is: price finished higher *and* never closed more than 1.5 ATR below the (moving) SMA, so a bounce that only happens after a decisive breakdown does not count. A resistance test mirrors it ($C_{t+k} < C_t$ and $C_u \le \text{SMA}_u + 1.5\,\text{ATR}_t$). The event-day ATR is frozen at $\text{ATR}_t$. If the window runs past the end of the data the bounce is missing (excluded, never counted as a failure). `--breach-basis low` swaps closes for intraday lows/highs.

**Event-study path.** For the trajectory plot, the cumulative return from $t-5$ is

$$\text{AR}_j = \frac{C_{t+j}}{C_{t-5}} - 1 - \mu^{\text{path}}_j(e), \qquad j = -5,\dots,10$$

where $\mu^{\text{path}}_j(e)$ is the same quantity averaged over all days in the era. Panels show support, resistance, and the direction-adjusted pool ($s_t \cdot \text{AR}_j$), with 95% bands $\bar{x} \pm 1.96\,\text{SE}$.

### 3.4 Confidence intervals

- **Bounce rates** use the **Wilson score interval** (well-behaved for small $n$ and rates near 0 or 1). With $\hat p = x/n$ and $z = 1.96$:

$$\frac{\hat p + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat p(1-\hat p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$

- **Mean CAR** uses a Student-$t$ interval, $\bar x \pm t_{n-1,\,0.975}\, s/\sqrt{n}$.

### 3.5 Target vs. control (H1)

For each era and each metric, with $\Delta = \bar y_{200} - \bar y_{\text{control}}$:

1. Student two-sample $t$-test (equal variances).
2. Welch's $t$-test (unequal variances).
3. Mann-Whitney $U$ test (rank-based, no normality assumption).
4. **Year-cluster bootstrap** (below).

All $p$-values are two-sided. A positive $\Delta$ is the direction the hypothesis predicts.

**Why a cluster bootstrap?** The first three tests assume the two samples are independent. They are not: both SMAs are tested against the *same* price path, and the 200-day and 174-day SMAs sit close together, so many events coincide. Treating them as independent overstates the variance of $\Delta$, making those tests conservative. Events inside a year are also serially dependent. The cluster bootstrap fixes both:

1. Group events by calendar year (a year keeps both MAs' events together).
2. Resample whole years with replacement, $B$ times (default 5000).
3. For each replicate compute $\Delta^*$.
4. **CI:** the 2.5th and 97.5th percentiles of $\Delta^*$.
5. **$p$-value**, recentred on the observed difference $\hat\Delta$:

$$p = \frac{1 + \#\{\,|\Delta^* - \hat\Delta| \ge |\hat\Delta|\,\}}{B + 1}$$

### 3.6 Did the effect grow in the modern era? (H3)

The three eras are 1950-1990 (pre-internet, manual execution), 1991-2007 (early electronic trading) and 2008-present (high-frequency and retail coordination).

The estimand is a **difference-in-differences**:

$$\text{DiD} = \underbrace{\big(\bar y_{200} - \bar y_{\text{ctl}}\big)_{\text{Era 3}}}_{\Delta_{E3}} - \underbrace{\big(\bar y_{200} - \bar y_{\text{ctl}}\big)_{\text{Era 1}}}_{\Delta_{E1}}$$

H3 predicts DiD $> 0$. Subtracting the control removes anything that affects *all* moving averages equally in an era (drift, volatility regime, how far price tends to wander). It is estimated two ways:

**(a) Stratified cluster bootstrap.** Years are resampled independently within Era 1 and within Era 3, and DiD$^* = \Delta^*_{E3} - \Delta^*_{E1}$ is formed per replicate, with percentile CI and recentred $p$-value as above.

**(b) Interaction regression** on the pooled events of both MAs:

$$y = \beta_0 + \beta_1 T + \beta_2 E_2 + \beta_3 E_3 + \beta_4 (T\!\cdot\!E_2) + \beta_5 (T\!\cdot\!E_3) + \varepsilon$$

$T = 1$ for the target MA, $E_2, E_3$ are era dummies (Era 1 is the reference). $\beta_5$ is the DiD coefficient. Standard errors are **cluster-robust by calendar year** (CR1):

$$\hat V = \frac{G}{G-1}\cdot\frac{N-1}{N-K}\,(X^\top X)^{-1}\Big(\sum_{g=1}^{G} X_g^\top \hat u_g \hat u_g^\top X_g\Big)(X^\top X)^{-1}$$

with $p$-values from a $t$ distribution on $G-1$ degrees of freedom ($G$ = number of years).

---

## 4. Running it

Requires Python 3.10+ and an internet connection for the first download.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py                                   # S&P 500 (^GSPC) from 1950, 200d vs 174d
python main.py --control 150                     # a different control window
python main.py --bootstrap 10000 --seed 7        # tighter bootstrap, different seed
python main.py --ticker ^IXIC --start 1971-02-05 # another index
python main.py --csv my_prices.csv               # your own OHLC data (first column = date)
python main.py --synthetic                       # offline smoke test on a no-effect random walk
```

Downloads are cached in `.cache/` (open-ended requests are refreshed after 24 hours; use `--refresh` to force it).

### Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--target` / `--control` | 200 / 174 | SMA windows (any integers) |
| `--band` | 0.5 | Touch band half-width, in ATRs |
| `--breach` | 1.5 | Bounce-failure distance, in ATRs |
| `--approach` | 5 | Prior closes that must lie on one side of the SMA |
| `--refractory` | 10 | De-clustering window (trading days) |
| `--horizons` | 1 3 5 10 | Forward horizons (days) |
| `--atr-window` | 14 | ATR period |
| `--breach-basis` | close | `close`, or `low` (intraday) |
| `--bootstrap` | 5000 | Bootstrap replications |
| `--seed` | 42 | Random seed (results are reproducible) |
| `--plot-horizon` | 5 | Horizon shown in `era_comparison.png` |
| `--outdir` | `.` | Where PNGs are written |
| `--save-events` | off | Also write every event to `events.csv` |

### Output

**Console** (six ASCII tables): (1) events per MA, era and direction; (2) bounce rates with 95% CIs; (3) mean CAR and standard deviation; (4) target-vs-control tests per era and horizon; (5) range expansion; (6) the Era 3 vs. Era 1 difference-in-differences.

**Figures:**
- `event_study_car.png`: average abnormal cumulative return from $t-5$ to $t+10$ around touches, 200-day vs. control.
- `era_comparison.png`: bounce rate and CAR by era, plus the 200-minus-control gap with bootstrap CIs.

---

## 5. Validation

The pipeline was checked on 60 simulated random walks (GARCH volatility, 1950-2025) that contain **no** moving-average effect, so about 5% of tests should reject at the 5% level:

| Test | False-positive rate |
|------|--------------------|
| Student / Welch / Mann-Whitney | about 1% (too conservative: samples are not independent) |
| Year-cluster bootstrap | 5-9% (slightly liberal when an era has few years) |
| Era-expansion bootstrap / clustered OLS | 5.4-6.7% |

Run `python main.py --synthetic` to see the same kind of null output.

---

## 6. Limitations and caveats

- **Multiple testing.** Roughly 56 tests are reported with no correction; a few $p < 0.05$ results are expected by chance. A lone significant cell is weak evidence.
- **Few events.** Each era has only tens to a couple of hundred events per MA, so confidence intervals are wide and power is low for small effects.
- **Old data quality.** `^GSPC` before about 1962 has no true intraday high/low (they equal the close), so ATR and touch detection in Era 1 are close-to-close approximations.
- **Drift.** Bounce rates above 50% for support tests partly reflect equity drift. Only the 200-minus-control difference speaks to the hypothesis.
- **Parameter choices.** Interpretations of "prior 5-day close above", the refractory rule and the breach test are documented in `events.py` and are configurable, but results can move with them.
- **One market.** A single index over one history. A null here does not rule out effects in individual stocks or intraday data, and a positive result would not prove the *mechanism* is trader coordination.
- **Not investment advice.** This is a research tool, not a trading strategy; it ignores costs, slippage and position sizing.
