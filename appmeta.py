"""Shared constants: ticker presets and the Python files the browser (Pyodide) engine needs."""

PRESETS = [
    {"group": "US indices", "items": [
        {"t": "^GSPC", "n": "S&P 500"}, {"t": "^IXIC", "n": "Nasdaq Composite"}, {"t": "^DJI", "n": "Dow Jones"},
        {"t": "^RUT", "n": "Russell 2000"}, {"t": "^NDX", "n": "Nasdaq 100"}]},
    {"group": "World indices", "items": [
        {"t": "^FTSE", "n": "FTSE 100"}, {"t": "^GDAXI", "n": "DAX"}, {"t": "^N225", "n": "Nikkei 225"},
        {"t": "^HSI", "n": "Hang Seng"}, {"t": "^STOXX50E", "n": "Euro Stoxx 50"}]},
    {"group": "ETFs & commodities", "items": [
        {"t": "SPY", "n": "SPDR S&P 500"}, {"t": "QQQ", "n": "Invesco QQQ"}, {"t": "IWM", "n": "iShares Russell 2000"},
        {"t": "GLD", "n": "Gold ETF"}, {"t": "TLT", "n": "20+yr Treasuries"}, {"t": "GC=F", "n": "Gold futures"},
        {"t": "CL=F", "n": "Crude oil futures"}]},
    {"group": "Stocks", "items": [
        {"t": "AAPL", "n": "Apple"}, {"t": "MSFT", "n": "Microsoft"}, {"t": "NVDA", "n": "Nvidia"},
        {"t": "AMZN", "n": "Amazon"}, {"t": "GOOGL", "n": "Alphabet"}, {"t": "META", "n": "Meta"},
        {"t": "TSLA", "n": "Tesla"}, {"t": "JPM", "n": "JPMorgan"}, {"t": "XOM", "n": "Exxon Mobil"},
        {"t": "KO", "n": "Coca-Cola"}]},
    {"group": "Crypto", "items": [
        {"t": "BTC-USD", "n": "Bitcoin"}, {"t": "ETH-USD", "n": "Ethereum"}, {"t": "SOL-USD", "n": "Solana"},
        {"t": "XRP-USD", "n": "XRP"}, {"t": "DOGE-USD", "n": "Dogecoin"}, {"t": "BNB-USD", "n": "BNB"},
        {"t": "ADA-USD", "n": "Cardano"}, {"t": "LTC-USD", "n": "Litecoin"}]},
    {"group": "Sanity check", "items": [
        {"t": "SYNTHETIC", "n": "Synthetic random walk (no effect by construction)"}]},
]

# Files copied into the in-browser Python runtime (paths relative to the repo root).
PY_FILES = [
    "data.py", "metrics.py", "events.py", "stats.py", "service.py", "bridge.py",
    "kalshi_lab/__init__.py", "kalshi_lab/kalshi_data.py", "kalshi_lab/calibration.py",
    "kalshi_lab/backtest.py", "kalshi_lab/stats.py", "kalshi_lab/plot.py", "kalshi_lab/web.py",
]

# Upstream APIs the same-origin proxy may forward to (Flask app and Cloudflare Worker share this policy).
UPSTREAMS = {
    "kalshi": "https://api.elections.kalshi.com/trade-api/v2",
    "coinbase": "https://api.exchange.coinbase.com",
}
