# SMABackTester

An interactive research workbench with two labs, a command-line pipeline behind each, and a website that runs real Python in your browser.

**Authors:** Vivaan Shahani & Ren Yamaki

| Lab | Question |
|-----|----------|
| **SMA Lab** | Is the 200-day moving average a *self-fulfilling* support/resistance level — i.e. does price react to it more than to a line nobody watches, and more so in the modern era? |
| **Kalshi 15m Lab** | Do retail traders systematically overprice "Yes" on Kalshi's 15-minute crypto contracts, so that simply buying "No" is profitable after fees? |

Live site: **financetests.vivaanshahani.com** (see [Deploying](#3-deploying-to-cloudflare)).

---

## 1. Quick start (local)

Requires Python 3.10+ (developed on 3.14).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python app.py                 # website at http://127.0.0.1:5050
```

Open <http://127.0.0.1:5050>. The header switches between the two labs.

Command-line versions (no browser needed):

```bash
# SMA Lab
python main.py                                      # S&P 500 from 1950, 200d vs 174d, PNG charts
python main.py --ticker BTC-USD ETH-USD AAPL        # several assets, one folder each
python main.py --era-years 1970 1990 2010           # four custom eras

# Kalshi Lab
python kalshi_lab/main.py --entry-checkpoint 5m --min-price 20 --max-price 50
python kalshi_lab/main.py --source synthetic --bias 0     # a perfectly calibrated null market
python kalshi_lab/main.py --series KXETH15M --days 14 --price-source executable

# Tests
pytest -q tests
```

> macOS note: port 5000 is taken by AirPlay Receiver, so the dev server defaults to **5050**.

---

## 2. How it is built

```
                ┌───────────────────────── browser ─────────────────────────┐
 static page ──►│  index.html + static/js/*  (Plotly charts, KaTeX math)     │
 (any host)     │        │                                                    │
                │        ▼  engine.js picks an engine                         │
                │  ┌───────────────┐         ┌───────────────────────────┐   │
                │  │ server engine │   or    │ browser engine            │   │
                │  │ python app.py │         │ Web Worker + Pyodide      │   │
                │  │ (native, fast)│         │ (the SAME .py files, run  │   │
                │  └───────────────┘         │  in WebAssembly)          │   │
                └─────────────────────────── └───────────┬───────────────┘ ──┘
                                                         │ fetches data through
                                                         ▼
                              same-origin proxy  /api/proxy/{yahoo,kalshi,coinbase}
                              (cloudflare/worker.js in production, app.py locally)
```

* **One Python code base, two ways to run it.** `service.py` / `kalshi_lab/web.py` turn a JSON config into JSON results. `app.py` calls them natively; the public site loads the identical files into Pyodide (Python 3.14 + pandas + SciPy compiled to WebAssembly) inside a Web Worker. Results agree to the last digit across engines.
* **Static hosting works.** The production site is one HTML file plus a tiny data proxy — no Python server. Every URL in the page is relative, so it works at a domain root or under any sub-path.
* **Why a proxy?** Browsers cannot call Yahoo Finance directly (no CORS headers), and Kalshi answers `403` to any request carrying a browser `Origin` header. The proxy forwards a small allowlist of read-only `GET` requests from the server side.

---

## 3. Deploying to Cloudflare

The site is **one HTML file + one Cloudflare Worker (the data proxy)**.

### Step 1 — build

```bash
python build_static.py
```

This needs Node (it bundles the JavaScript with esbuild) and produces:

```
dist/
  index.html      <- THE WEBSITE: styles, scripts, Python sources and the maths page are all inside this one file
  cloudflare/     <- worker.js, wrangler.toml, test_worker.mjs (the data proxy)
  functions/      <- the same proxy as a Cloudflare Pages Function (alternative to the Worker)
```

Because everything is inside `index.html`, publishing that single file is enough — there is nothing else to forget to upload. (An earlier version was split into `static/` and `py/` folders; when only `index.html` was uploaded the page showed up unstyled and empty. `python build_static.py --multi` still writes that multi-file layout to `dist/site/` if you want it.)

Rehearse production locally (serves **only** `dist/index.html`, 404 for everything else, plus the proxy):

```bash
python serve_dist.py        # http://127.0.0.1:5001/   (add --prefix /FinanceProjectTests to test a sub-path)
```

### Step 2 — publish the page

Put `dist/index.html` at the root of the site served at `financetests.vivaanshahani.com` (for a Cloudflare Pages project: make it the only file in the build output, or the `index.html` in the published folder) and deploy as usual. The page also works under a sub-path such as `/FinanceProjectTests/`; a missing trailing slash is redirected for you.

### Step 3 — deploy the proxy (pick **one**)

**A. Cloudflare Worker (recommended)**

```bash
cd dist/cloudflare            # or ./cloudflare in the repo
npx wrangler login
npx wrangler deploy
```

`wrangler.toml` binds the Worker to `financetests.vivaanshahani.com/api/proxy/*` and `vivaanshahani.com/FinanceProjectTests/api/proxy/*` (delete the one you do not use). The Worker only looks for the `/api/proxy/` marker in the path, so it works under any hostname or prefix.

**B. Cloudflare Pages Function** — if the site is a Pages project, copy `dist/functions/` into the project root (next to the files Pages publishes). It serves `/api/proxy/*` from the same code.

### Step 4 — verify

1. `https://financetests.vivaanshahani.com/api/proxy/yahoo?symbol=AAPL&period1=1700000000&period2=1790000000` should return JSON (not a 404 page).
2. Open the site and press **Run**. The first visit downloads the Python runtime (~30 MB from the jsDelivr CDN; cached afterwards).
3. `node cloudflare/test_worker.mjs` checks the proxy logic against the live APIs (11 checks).
4. Switch to **Kalshi 15-minute test** and run it with *Real data only*.

### Things to know

* **If the page looks unstyled or its inputs are empty**, the HTML was served without its scripts, or the proxy is missing: check the browser console and the URL in step 4.1.
* **Upstream blocking and rate limits are the main risk.** Yahoo and Kalshi may treat Cloudflare's IP ranges differently from a laptop, and Kalshi answers HTTP 429 to bursts of requests, so the Kalshi study paces its requests (about 3 per second) and backs off when throttled (a 7-day pull takes ~30 s). If Yahoo blocks you, use "upload your own CSV"; the Kalshi tool's default *real data (else simulated)* falls back to a clearly labelled synthetic dataset instead of failing.
* **Content-Security-Policy.** If the site sets a CSP it must allow `cdn.jsdelivr.net` and `cdn.plot.ly` for scripts, `connect-src` to `cdn.jsdelivr.net`, `worker-src blob:`, and `script-src 'wasm-unsafe-eval'` (WebAssembly).
* **Third-party CDNs** are used for Plotly, KaTeX and Pyodide. Pin or self-host them if you need offline or locked-down operation.
* **Caching.** The Worker caches successful responses (Yahoo 1 h, Kalshi 60 s, Coinbase 5 min) and never caches errors.
* **Updating.** Re-run `python build_static.py` and re-publish `dist/index.html`; the Worker only changes if `cloudflare/worker.js` does.

---

## 4. SMA Lab

### 4.1 The question

Traders widely watch the 200-day SMA. If enough of them buy at it and sell at it, it could become a real support/resistance level through coordination alone. Three claims are tested:

| # | Claim | How |
|---|-------|-----|
| H1 | Price reacts to the target line more than to a line nobody watches | Identical event rules for the target and one or more **control lines** |
| H2 | "Reacts" means turning away from the line, not through it | Bounce rate and direction-adjusted abnormal return |
| H3 | The effect is stronger in the modern algorithmic/retail era | Difference-in-differences between a late and an early era |

The control line is the key design choice. Any smoothed line looks like support in hindsight; only the *difference* from a comparable arbitrary line says anything about coordination. The null hypothesis is that the target behaves exactly like the control.

### 4.2 What you can change in the website

| Area | Controls |
|------|----------|
| Assets | Any Yahoo Finance symbol, presets (indices, ETFs, stocks, crypto), a synthetic no-effect series, or your own uploaded CSV; any date range |
| Lines | A target window and its type (SMA / EMA / WMA); up to 8 control windows; random controls; a **line scan** of every window from 2 to 1000 |
| Eras | **Smart** (default regimes if the history reaches back to 1980, else equal thirds), **Custom** (any number of boundary years, 2–8 eras), or **Equal slices**; choose which two eras the "did it grow?" test compares |
| Event rules | Touch band, breach distance, approach length, de-clustering gap, ATR window, plot window, any set of forward horizons, breach test on closes or intraday, support only / resistance only / both |
| Statistics | Bootstrap replications and seed |

The page is one column: the inputs at the top (with advanced options under *More settings*) and the results below in six tabs — **Summary** (plain-language verdicts), **Charts** (by time period, what happens after a touch, price with touches), **Tables** (CSV export), **Try every line** (the line scan), **Each touch** (click any touch to see its candles and the definition checked step by step) and **How it works**.

### 4.3 The math

Notation: for bar $t$, $O_t, H_t, L_t, C_t$ are open, high, low, close; $N$ is the line's window.

**Moving averages** (all include the current bar):

$$\text{SMA}_t=\frac1N\sum_{i=0}^{N-1}C_{t-i},\qquad \text{EMA}_t=\alpha C_t+(1-\alpha)\text{EMA}_{t-1}\ \ (\alpha=\tfrac{2}{N+1}),\qquad \text{WMA}_t=\frac{\sum_{i=0}^{N-1}(N-i)C_{t-i}}{N(N+1)/2}$$

**True range and ATR** (Wilder, 14 bars):

$$\text{TR}_t=\max\big(H_t-L_t,\ |H_t-C_{t-1}|,\ |L_t-C_{t-1}|\big),\qquad \text{ATR}_t=\text{ATR}_{t-1}+\tfrac1{14}(\text{TR}_t-\text{ATR}_{t-1})$$

ATR turns distances into volatility units, so "close to the line" means the same in calm and wild markets.

**Distance and range expansion:**

$$d_t=\frac{C_t-\text{MA}_t}{\text{MA}_t},\quad d^{\text{ATR}}_t=\frac{C_t-\text{MA}_t}{\text{ATR}_t},\quad \rho^{\text{TR}}_t=\frac{\text{TR}_t}{\frac1{20}\sum_{i=1}^{20}\text{TR}_{t-i}}$$

The baseline excludes the event day itself.

**Touch events.** The band is $[\text{MA}_t-b\,\text{ATR}_t,\ \text{MA}_t+b\,\text{ATR}_t]$ ($b=0.5$). A touch must be an approach from a definite side, so each candidate requires the previous $m=5$ closes on one side of the line:

- *Support test:* $C_{t-i}>\text{MA}_{t-i}$ for $i=1..m$ **and** $L_t\le \text{MA}_t+b\,\text{ATR}_t$
- *Resistance test:* $C_{t-i}<\text{MA}_{t-i}$ for $i=1..m$ **and** $H_t\ge \text{MA}_t-b\,\text{ATR}_t$

Let $s_t=+1$ for support and $-1$ for resistance.

**De-clustering.** Candidates are processed in time order and accepted only if $i-i_{\text{last accepted}}>R$ ($R=10$). This also stops forward windows from overlapping.

**Reaction metrics** (all from the close of the event day $C_t$, so nothing about that day's own outcome leaks into entry):

$$R_{t\to t+k}=\frac{C_{t+k}-C_t}{C_t},\qquad \mu_k(e)=\underset{s\in e}{\text{mean}}\,R_{s\to s+k},\qquad \text{CAR}_k=s_t\big(R_{t\to t+k}-\mu_k(e_t)\big)$$

$\mu_k(e)$ is the average $k$-bar return over *all* bars of the same asset and era (it removes drift, and the target and every control share it). Multiplying by $s_t$ makes **positive always mean "reacted the way a support/resistance level predicts"**, so directions can be pooled.

$$\text{Bounce (support)}=\mathbb 1\Big[C_{t+k}>C_t\ \wedge\ C_u\ge\text{MA}_u-\beta\,\text{ATR}_t\ \ \forall u\in[t,t+k]\Big],\quad\beta=1.5$$

Resistance mirrors it. A window running past the end of the data gives a *missing* bounce, never a failure. For the event-study chart, $\text{AR}_j=C_{t+j}/C_{t-5}-1-\mu^{\text{path}}_j(e)$ for $j=-5..10$.

**Confidence intervals.** Bounce rates use the Wilson score interval ($\hat p=x/n$, $z=1.96$):

$$\frac{\hat p+\frac{z^2}{2n}\pm z\sqrt{\frac{\hat p(1-\hat p)}{n}+\frac{z^2}{4n^2}}}{1+\frac{z^2}{n}}$$

and mean CAR uses a Student-$t$ interval.

**Target vs control.** For each era and metric, with $\Delta=\bar y_{\text{target}}-\bar y_{\text{control}}$: Student's $t$, Welch's $t$, Mann-Whitney $U$ and a **year-cluster bootstrap**. The first three assume independent samples, which is false here (both lines see the same prices and share events), so they are *conservative* — on simulated no-effect data they reject only about 1% of the time at a nominal 5%. The bootstrap:

1. Group events by calendar year (a year keeps both lines' events together).
2. Resample whole years with replacement $B$ times; compute $\Delta^*$ each time.
3. CI = 2.5th and 97.5th percentiles of $\Delta^*$; recentred p-value $p=\dfrac{1+\#\{|\Delta^*-\hat\Delta|\ge|\hat\Delta|\}}{B+1}$.

With fewer than 5 distinct years it returns *n/a* rather than a meaningless number. On 60 simulated no-effect histories it rejects 5–9% at a nominal 5% (slightly liberal when an era has few years).

**Did the effect grow?** A difference-in-differences between the early and late era you pick:

$$\text{DiD}=\underbrace{(\bar y_{\text{target}}-\bar y_{\text{control}})_{\text{late}}}_{\Delta_{\text{late}}}-\underbrace{(\bar y_{\text{target}}-\bar y_{\text{control}})_{\text{early}}}_{\Delta_{\text{early}}}$$

estimated by a stratified cluster bootstrap and by a pooled regression with cluster-robust (CR1) errors:

$$y=\beta_0+\beta_1T+\textstyle\sum_{e}\gamma_e E_e+\sum_{e}\delta_e\,(T\!\cdot\!E_e)+\varepsilon,\qquad \hat V=\tfrac{G}{G-1}\tfrac{N-1}{N-K}(X^\top X)^{-1}\Big(\sum_g X_g^\top\hat u_g\hat u_g^\top X_g\Big)(X^\top X)^{-1}$$

The late-era interaction $\delta$ is the DiD; $p$-values use $t_{G-1}$ with calendar years as clusters.

**Line scan.** Runs the same event study for every window in a range and ranks the target among them: empirical $p=\dfrac{1+\#\{\text{other lines}\ge\text{target}\}}{M+1}$ (neighbouring lines excluded; still only a rough guide because nearby lines share events).

### 4.4 Validation

Calibrated on 60 simulated random walks with no effect (about 5% of tests should reject):

| Test | False-positive rate |
|------|--------------------|
| Student / Welch / Mann-Whitney | ≈ 1% (conservative) |
| Year-cluster bootstrap | 5–9% |
| Era-expansion bootstrap / clustered OLS | 5.4–6.7% |

The browser (Pyodide) and server engines were checked to produce identical events, tables and scan results.

---

## 5. Kalshi 15m Lab

### 5.1 The question

Kalshi's 15-minute crypto contracts ask *"will the price at expiry be at or above where it started?"* If retail traders are systematically optimistic, **Yes** trades above its true probability, and buying **No** on every contract would profit even after fees. Three tests:

1. **Overpricing** — when "Yes" trades at $P$, does it win less than $P\%$ of the time?
2. **Asymmetry** — is the bias stronger on upside strikes (BTC must rise) than downside strikes?
3. **Strategy** — would "Buy No" make money after Kalshi's fees?

### 5.2 Data

| Source | Used for |
|--------|----------|
| Kalshi public API (`/markets`, batch `/markets/candlesticks`, `/historical/*`) | Settled contracts: strike, open/close time, result; 1-minute last-trade / bid / ask candles |
| Coinbase Exchange 1-minute candles | Spot, used only to decide whether the strike is above or below spot |
| Synthetic generator | Same schema as live data; Yes price = model-fair probability + an **assumed** optimism premium (set to 0 for a calibrated null). Planted by assumption — not evidence about the real market |

At each checkpoint "N minutes before expiry" the lab takes the latest known trade price, bid and ask (forward-filled, discarded if older than 3 minutes). Kalshi's batch-candle endpoint rejects any request where *tickers × minutes spanned > 10,000*, so markets are batched greedily under that budget.

### 5.3 Removing BTC's trend (the fair-value benchmark)

Comparing the Yes price with how often Yes won mixes three things: **mispricing** (the behavioral part), **BTC's drift** during the sample, and **luck**. A week in which BTC happened to rise makes Yes look cheap; a week in which it fell makes it look expensive. To isolate behavior the lab compares the Yes price with a **fair value computed only from what was known at that moment**: BTC spot $S$, strike $K$, minutes left $m$ and the trailing per-minute volatility $v$ (the previous hour of 1-minute Coinbase returns), with zero drift:

$$\text{fair}=\Phi\!\left(\frac{\operatorname{sign}(z)\,|z|^{\gamma}}{s}\right),\qquad z=\frac{\ln(S/K)}{v\sqrt{m-\tfrac23}}$$

The $\tfrac23$ accounts for settlement averaging the last 60 seconds of the index. Nothing here looks at what BTC did afterwards, so the benchmark contains neither trend nor luck. The **mispricing** of a contract is $P_{\text{yes}}-100\cdot\text{fair}$ cents, reported with a day-cluster bootstrap interval.

* **Fitted shape.** The volatility multiplier $s$ and tail exponent $\gamma$ are fitted to the sample by maximum likelihood (or you can fix $s$). The family is odd in $z$, so it can stretch or flatten the probabilities but can never tilt them up or down: a trend cannot be absorbed by the fit. This matters on real data: with plain $\gamma=s=1$ the model was under-confident in the middle and over-confident in the tails.
* **Profit split.** If fair value were the truth, buying a No at cost $c$ earns an expected $100(1-\text{fair})-c$ before fees: the **edge from mispricing**. Realised minus expected payout is **luck and trend**. They add up to the actual net profit, trade by trade.
* **Checked on simulated markets:** with no planted bias the premium is about 0; a planted 4¢ bias is found; and with BTC trending +8% a day the raw gap swings to −4¢ (wrongly saying Yes is cheap) while the premium stays near 0.
* **Honest limit.** Kalshi's own prices predict outcomes *better* than any model built only from spot, strike, time and volatility (they also reflect order flow and other venues). So part of a gap between price and model can be information, not behavior; the overall average gap is more reliable than the gap in any single bin. The page shows this comparison under "Check the fair-value model itself".

### 5.3b The saved run (the page opens with results)

`python build_static.py` runs the default study on **live data** at build time (14 days by default; about 30 seconds) and embeds the result in `index.html`, so the Kalshi tab opens with the main breakdown already on screen and without starting Python or calling Kalshi. It is labelled "Saved run" with its timestamp; **Run** recomputes with your settings. Rebuild and republish to refresh it.

```bash
python build_static.py                     # recompute the saved run from live data
python build_static.py --reuse-snapshot    # reuse the previous saved run (fast, offline)
python build_static.py --no-snapshot       # no saved run: the Kalshi tab opens empty
python build_static.py --snapshot-days 30  # a longer saved run
```

### 5.4 Definitions

**Calibration.** Contracts are binned by Yes price. In each bin the implied probability is the mean Yes price $\bar P$ and the realised rate is $\hat p$:

$$\text{gap}=\bar P-100\,\hat p\qquad(\text{positive}\Rightarrow\text{Yes overpriced})$$

The p-value tests $\hat p=\bar P/100$. Three tests are offered: the **two-proportion z-test** (the form the study specifies; it treats the implied rate as a second sample of size $n$, which inflates variance, so it is conservative), an **exact binomial test**, and a **Poisson-binomial z-test** that holds each contract to its *own* price and is the most powerful:

$$z=\frac{\sum_i y_i-\sum_i p_i}{\sqrt{\sum_i p_i(1-p_i)}}$$

Realised-rate error bars are Wilson intervals.

**Upside vs downside.** In the live `KXBTC15M` series the strike *is* the BTC reference price at market open, so "strike vs spot at open" is essentially noise. The lab therefore defaults to comparing the strike with spot **at the entry checkpoint** ($K>S$ = upside; $K<S$ = downside) and offers the open-based split as an option. Because upside strikes are nearly always cheap out-of-the-money Yes contracts and downside ones expensive, the raw comparison is confounded with the favourite–longshot bias; a **price-matched** comparison (Yes priced 40–60¢) is reported alongside it. Per contract the overpricing residual is $r_i=P_i/100-y_i$, and the groups' means are compared with Welch's test.

**Buy-No backtest.** Entry: buy one No at $100-P_{\text{yes}}$ cents at the checkpoint (or, with *executable* pricing, at its ask $100-\text{bid}_{\text{yes}}$). Payout: 100¢ if the market settles No, else 0. Kalshi's taker fee is charged on entry:

$$\text{fee}=\Big\lceil 0.07\times C\times P(1-P)\Big\rceil\text{ dollars},\ P\in[0,1]\qquad(\text{one contract at }50¢:\ \lceil 0.07\times0.25\times100\rceil=2¢)$$

The fee is symmetric in $P$. A trade profits only if the win rate exceeds the break-even rate $(\text{entry}+\text{fee})/100$.

| Rule | Description |
|------|-------------|
| 1 | Buy No on every contract |
| 2 | Buy No on upside strikes only |
| 3 | Buy No only when Yes is priced between a lower and upper bound (default 20–50¢) |
| custom | Any side, strike direction and price range you choose |

Metrics: **ROI** = net profit ÷ capital deployed (entry cost + fees); **profit factor** = winning ÷ losing trades after fees; **max drawdown** = largest peak-to-trough fall of cumulative net profit; **Sharpe** from daily profit with $\sqrt{365}$; a one-sample $t$-test of mean net profit per trade; and a **day-cluster bootstrap** CI (whole days resampled, since trades within a day are dependent).

### 5.5 What you can change in the website

Data source (live / auto / synthetic), the fair-value benchmark's volatility window, multiplier and index alignment, which 15-minute market (BTC, ETH, SOL, XRP, DOGE, BNB, HYPE), number of days or exact dates, **timing** (which checkpoints to extract, the entry checkpoint, expiry hours in UTC, weekdays), price used (last trade / midpoint / executable), upside-vs-downside reference, bin width, tails, p-value test, the three rules plus a custom rule, contracts per trade, fee schedule (taker / half / maker-like / none / custom), capital, and the synthetic-data knobs (including a BTC trend that moves outcomes but not prices, to show the benchmark ignoring it).

**Python console tab.** Real Python in the browser with `raw`, `frame`, `params`, `trades`, `pd`, `np`, and the lab's modules preloaded. Six runnable examples (entry-time sweep, hour-of-day, fee sensitivity, bootstrap CI, matplotlib plot, custom rule); edit and run (Ctrl/⌘+Enter). Packages such as matplotlib load on first import.

### 5.6 Caveats

* **Small samples.** A week is ≈ 670 contracts spread over bins and splits. A bin of 25 contracts has a ±20 pp interval; apparent overpricing there is mostly noise.
* **Many tests.** Splits × bins × rules multiply false positives. Do not tune the checkpoint, price range and rule until something works.
* **Execution.** Trading at a last-trade price ignores paying the ask — try *executable*. Market impact and queue position are ignored.
* **Settlement index.** Kalshi settles on CF Benchmarks' BRTI; Coinbase spot differs slightly, which only affects the upside/downside split.
* **Regime.** A few days of crypto data say little about other conditions.
* **Not financial advice.**

---

## 6. Project layout

| Path | Role |
|------|------|
| `main.py`, `data.py`, `metrics.py`, `events.py`, `stats.py`, `plot.py`, `report.py` | SMA research pipeline (CLI): data & cache, indicators, event detection, statistics, charts, console tables |
| `service.py` | JSON-in / JSON-out layer used by the web app (validation, analysis, event window, line scan) |
| `app.py` | Local Flask server: static page, native analysis API, data proxy, Python sources |
| `bridge.py` | Dispatch layer the browser worker calls |
| `appmeta.py` | Ticker presets, list of Python files for the browser, proxy allowlist |
| `kalshi_lab/` | `kalshi_data.py`, `calibration.py`, `backtest.py`, `stats.py`, `plot.py`, `main.py` (CLI), `web.py` (browser entry points + console), `requirements.txt` |
| `static/` | Page source: `index.html`, `style.css`, `method.html`, `js/` (`main`, `kalshi`, `controls`, `charts`, `tables`, `engine`, `pyworker`, `util`). `build_static.py` inlines all of it into one file |
| `cloudflare/` | `worker.js` (data proxy), `wrangler.toml`, `test_worker.mjs` |
| `build_static.py`, `serve_dist.py` | Build the single-file site (`dist/index.html`); rehearse production locally |
| `tests/` | 34 pytest tests (indicators, events, statistics, fees, backtest arithmetic, API validation, end-to-end) |

---

## 7. Limitations (both labs)

* **Multiple testing.** Dozens of p-values are shown with no correction; about 1 in 20 will cross 0.05 by luck.
* **Few events / short histories.** Cluster methods are unreliable below ~10 years per era and are switched off below 5.
* **Old data.** The S&P 500 index before ~1962 has no true intraday high/low, so ATR and touches there are close-to-close approximations.
* **24/7 markets.** For crypto an $N$-bar line spans $N$ calendar days.
* **Free data.** Yahoo Finance prices (split/dividend adjusted) with only basic cleaning.
* **Not investment advice.** Research tools only; costs, slippage and position sizing are not modelled.
