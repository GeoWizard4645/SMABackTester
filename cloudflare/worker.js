// Cloudflare Worker: same-origin data proxy for the Finance Lab site (any hostname, any path prefix)
//
// Browsers cannot call Yahoo Finance or Kalshi directly (no CORS headers; Kalshi answers 403 to any
// request carrying a browser Origin header). The page therefore asks THIS worker, which forwards a
// small allowlist of read-only GET requests from Cloudflare's servers.
//
//   /api/proxy/yahoo?symbol=AAPL&period1=..&period2=..          -> Yahoo daily chart JSON
//   /api/proxy/kalshi/<markets|series|events|historical>/...     -> Kalshi public API v2
//   /api/proxy/coinbase/products/<PRODUCT>/candles?...           -> Coinbase Exchange candles
//
// The page asks for "api/proxy/..." relative to wherever it is hosted, so the worker only looks for the
// "/api/proxy/" marker: it works at https://financetests.vivaanshahani.com/api/proxy/... and equally at
// https://vivaanshahani.com/FinanceProjectTests/api/proxy/... See ../wrangler.toml for how it is deployed.

const MARK = "/api/proxy/";

const UPSTREAMS = {
  kalshi: "https://api.elections.kalshi.com/trade-api/v2",
  coinbase: "https://api.exchange.coinbase.com",
};
const KALSHI_PATH = /^(markets|series|events|historical)(\/[A-Za-z0-9_.\-]+)*$/;
const COINBASE_PATH = /^products\/[A-Za-z0-9\-]{3,15}\/candles$/;
const SYMBOL = /^[A-Za-z0-9^.=\-]{1,20}$/;
const UA = "Mozilla/5.0 (compatible; finance-project-tests-proxy/1.0)";

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "access-control-allow-origin": "*", ...extra },
  });
}

async function forward(url, ttl, ctx) {
  let upstream;
  try {
    upstream = await fetch(url, {
      method: "GET",
      headers: { "User-Agent": UA, Accept: "application/json" }, // deliberately NO Origin / Referer / Cookie
      // cache good answers only: never keep a 429 / 5xx around for the next visitor
      cf: { cacheEverything: true, cacheTtlByStatus: { "200-299": ttl, "300-599": -1 } },
    });
  } catch (err) {
    return json({ error: `upstream unreachable: ${err.message}` }, 502);
  }
  const body = await upstream.arrayBuffer();
  if (body.byteLength > 25 * 1024 * 1024) return json({ error: "upstream response too large" }, 502);
  const ok = upstream.status >= 200 && upstream.status < 300;
  return new Response(body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") || "application/json",
      "cache-control": ok ? `public, max-age=${ttl}` : "no-store",
      "access-control-allow-origin": "*",
    },
  });
}

export async function handle(request, ctx) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-methods": "GET", "access-control-max-age": "86400" } });
  }
  if (request.method !== "GET") return json({ error: "method not allowed" }, 405);

  const url = new URL(request.url);
  const at = url.pathname.indexOf(MARK);
  if (at < 0) return json({ error: "not found" }, 404);
  const rest = url.pathname.slice(at + MARK.length);

  if (rest === "yahoo") {
    const symbol = url.searchParams.get("symbol") || "";
    const p1 = Number(url.searchParams.get("period1"));
    const p2 = Number(url.searchParams.get("period2"));
    if (!SYMBOL.test(symbol)) return json({ error: "invalid symbol" }, 400);
    if (!Number.isInteger(p1) || !Number.isInteger(p2)) return json({ error: "period1 and period2 (unix seconds) are required" }, 400);
    const target = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?period1=${p1}&period2=${p2}&interval=1d&includeAdjustedClose=true&events=div%2Csplit`;
    return forward(target, 3600, ctx);
  }

  const slash = rest.indexOf("/");
  const name = slash < 0 ? rest : rest.slice(0, slash);
  const path = slash < 0 ? "" : rest.slice(slash + 1);
  let ttl;
  if (name === "kalshi" && KALSHI_PATH.test(path)) ttl = 60;
  else if (name === "coinbase" && COINBASE_PATH.test(path)) ttl = 300;
  else return json({ error: "path not allowed" }, 403);
  if (url.search.length > 6000) return json({ error: "query too long" }, 414);
  return forward(`${UPSTREAMS[name]}/${path}${url.search}`, ttl, ctx);
}

export default {
  fetch(request, env, ctx) {
    // Safety net: if the platform ever routes a non-proxy request here, hand it to the static assets.
    if (env && env.ASSETS && !new URL(request.url).pathname.includes("/api/proxy/")) return env.ASSETS.fetch(request);
    return handle(request, ctx);
  },
};
