"""ccxt ile OHLCV ve ticker verisi, SQLite cache'li."""
import asyncio
import os

import ccxt.async_support as ccxt
import pandas as pd

from core import db

TIMEFRAMES = ["1h", "4h", "8h", "1d"]
TTL = {"1h": 300, "4h": 600, "8h": 900, "1d": 1800}
LIMIT = 300

STABLES = {
    "USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USDE", "USD1", "PYUSD",
    "EUR", "EURI", "AEUR", "TRY", "BRL", "XUSD", "USDD", "RLUSD", "BFUSD", "U",
    # altın ve wrapped/staked türevler: ayrı sinyal üretmesinin anlamı yok
    "XAUT", "PAXG", "WBTC", "WBETH", "BETH", "STETH", "WSTETH", "BNSOL", "CBBTC",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

_exchange = None


def exchange():
    global _exchange
    if _exchange is None:
        name = os.getenv("EXCHANGE", "binance")
        options = {"defaultType": "spot"}
        if name == "binance":
            options |= {"fetchMarkets": ["spot"], "fetchCurrencies": False}
        _exchange = getattr(ccxt, name)({"enableRateLimit": True, "options": options})
        if name == "binance":
            # herkese açık piyasa verisi sunucusu: ABD dahil her yerden erişilebilir (GitHub Actions)
            _exchange.urls["api"]["public"] = "https://data-api.binance.vision/api/v3"
    return _exchange


async def close() -> None:
    global _exchange
    if _exchange is not None:
        await _exchange.close()
        _exchange = None


def _to_df(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    return df.astype(float)


async def fetch_ohlcv(symbol: str, tf: str, limit: int = LIMIT) -> pd.DataFrame:
    key = f"ohlcv:{symbol}:{tf}"
    rows = db.cache_get(key, TTL[tf])
    if rows is None:
        rows = await exchange().fetch_ohlcv(f"{symbol}/USDT", tf, limit=limit)
        db.cache_set(key, rows)
    return _to_df(rows)


async def fetch_all_tf(symbol: str) -> dict[str, pd.DataFrame]:
    frames = await asyncio.gather(*(fetch_ohlcv(symbol, tf) for tf in TIMEFRAMES))
    return dict(zip(TIMEFRAMES, frames))


TOKENIZED_STOCKS = {"CRCLB", "SPCXB", "TSLAB", "NVDAB", "AAPLB", "MSTRB", "COINB", "HOODB"}


def _eligible(base: str) -> bool:
    return (base.isascii() and base.isalnum() and base not in STABLES and base not in TOKENIZED_STOCKS
            and not base.endswith(LEVERAGED_SUFFIXES))


async def tickers() -> dict[str, dict]:
    """{BASE: {"last": fiyat, "volume": 24s USDT hacmi}} — sadece aktif spot USDT pariteleri."""
    cached = db.cache_get("tickers", 300)
    if cached is not None:
        return cached
    ex = exchange()
    await ex.load_markets()
    raw = await ex.fetch_tickers()
    out = {}
    for sym, t in raw.items():
        m = ex.markets.get(sym)
        if not m or not m.get("spot") or not m.get("active") or m.get("quote") != "USDT":
            continue
        if t.get("last") and t.get("quoteVolume"):
            out[m["base"]] = {"last": float(t["last"]), "volume": float(t["quoteVolume"])}
    db.cache_set("tickers", out)
    return out


async def top_by_volume(n: int, min_volume: float = 0.0) -> list[str]:
    """24s USDT hacmine göre ilk n; min_volume altındakiler (sığ piyasa: spread/kayma R:R'yi bozar) elenir."""
    t = await tickers()
    ranked = sorted((b for b in t if _eligible(b) and t[b]["volume"] >= min_volume),
                    key=lambda b: t[b]["volume"], reverse=True)
    return ranked[:n]


async def is_listed(symbol: str) -> bool:
    return symbol in await tickers()
