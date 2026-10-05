// Local test of the worker logic against the real upstream APIs:  node cloudflare/test_worker.mjs
import worker from "./worker.js";

const B = "https://vivaanshahani.com/FinanceProjectTests/api/proxy";
const get = (p) => worker.fetch(new Request(B + p), {}, { waitUntil() {} });
let failures = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS " : "FAIL ") + name + (detail ? "  " + detail : "")); if (!ok) failures++; };

let r = await get("/yahoo?symbol=AAPL&period1=1700000000&period2=1790000000");
let j = await r.json();
check("yahoo AAPL", r.status === 200 && j.chart?.result?.[0]?.timestamp?.length > 100, `status ${r.status}`);

r = await get("/yahoo?symbol=../../etc&period1=1&period2=2");
check("yahoo rejects bad symbol", r.status === 400);

r = await get("/yahoo?symbol=AAPL");
check("yahoo requires periods", r.status === 400);

r = await get("/kalshi/series/KXBTC15M");
j = await r.json();
check("kalshi series", r.status === 200 && j.series?.ticker === "KXBTC15M", `status ${r.status}`);

r = await get("/kalshi/markets?series_ticker=KXBTC15M&status=settled&limit=2");
j = await r.json();
check("kalshi markets", r.status === 200 && j.markets?.length === 2, `status ${r.status}`);

r = await get("/kalshi/portfolio/orders");
check("kalshi blocks non-allowlisted path", r.status === 403);

r = await get("/coinbase/products/BTC-USD/candles?granularity=60");
check("coinbase candles", r.status === 200 && Array.isArray(await r.json()), `status ${r.status}`);

r = await get("/coinbase/accounts");
check("coinbase blocks non-allowlisted path", r.status === 403);

r = await worker.fetch(new Request(B + "/yahoo?symbol=AAPL", { method: "POST" }), {}, {});
check("POST rejected", r.status === 405);

r = await worker.fetch(new Request("https://vivaanshahani.com/other"), {}, {});
check("outside base is 404", r.status === 404);

process.exit(failures ? 1 : 0);
