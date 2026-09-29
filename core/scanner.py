"""Tek coin analizi ve tüm izleme listesinin taranıp sıralanması."""
import asyncio
import logging

from core import data, db, levels, onchain, settings, signal, tradfi
from core.indicators import add_indicators, last_atr

log = logging.getLogger(__name__)
_scan_lock = asyncio.Lock()
MIN_BARS = 60  # yeni listelenen coinlerde seviye/EMA hesabı anlamsız


class InsufficientData(Exception):
    pass


def _normalize(symbol: str) -> str:
    return symbol.upper().removesuffix("/USDT").removesuffix("USDT") or symbol.upper()


async def universe() -> list[str]:
    """Hacme göre ilk N + coins.yaml manuel + /watch add − /watch rm."""
    extra = db.kv_get("watch_add", [])
    excluded = set(db.kv_get("watch_rm", []))
    top = await data.top_by_volume(settings.get("universe_size"))
    listed = await data.tickers()
    out = []
    for s in top + onchain.manual_coins() + extra:
        if s not in out and s not in excluded and s in listed:
            out.append(s)
    return out


def watch_add(symbol: str) -> None:
    symbol = _normalize(symbol)
    add = db.kv_get("watch_add", [])
    rm = [s for s in db.kv_get("watch_rm", []) if s != symbol]
    if symbol not in add:
        add.append(symbol)
    db.kv_set("watch_add", add)
    db.kv_set("watch_rm", rm)


def watch_rm(symbol: str) -> None:
    symbol = _normalize(symbol)
    db.kv_set("watch_add", [s for s in db.kv_get("watch_add", []) if s != symbol])
    rm = db.kv_get("watch_rm", [])
    if symbol not in rm:
        rm.append(symbol)
    db.kv_set("watch_rm", rm)


async def analyze(symbol: str, cfg: dict | None = None) -> dict:
    symbol = _normalize(symbol)
    cfg = cfg or settings.all_settings()
    raw = await data.fetch_all_tf(symbol)
    _check_bars(symbol, raw)
    price = float(raw["1h"]["Close"].iloc[-1])
    volume = (await data.tickers()).get(symbol, {}).get("volume", 0.0)
    oc = await onchain.analyze(symbol, price, volume)
    res = evaluate_frames(symbol, raw, cfg, oc)
    res["volume_24h"] = volume
    return res


def _check_bars(symbol: str, raw: dict) -> None:
    short_tf = [tf for tf, df in raw.items() if len(df) < MIN_BARS]
    if short_tf:
        raise InsufficientData(f"{symbol}: {', '.join(short_tf)} için yetersiz mum geçmişi")


def evaluate_frames(symbol: str, raw: dict, cfg: dict, oc: dict,
                    market: str = "crypto", name: str | None = None) -> dict:
    """Ham OHLCV çerçevelerinden (1h/4h/8h/1d) seviye + sinyal üretir; veri kaynağından bağımsız."""
    _check_bars(symbol, raw)
    frames = {tf: add_indicators(df) for tf, df in raw.items()}
    price = float(frames["1h"]["Close"].iloc[-1])
    lv = {tf: levels.compute_levels(df, tf, price) for tf, df in frames.items()}
    levels.annotate_confluence(lv, 0.5 * last_atr(frames["4h"]))
    res = signal.evaluate(symbol, frames, lv, oc, cfg)
    res.update(frames=frames, levels=lv, onchain=oc, market=market, name=name or symbol)
    return res


def _rank(results: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """LONG: long planıyla skoru en yüksek n; SHORT: kalanlardan short planıyla skoru en düşük n."""
    n = max(cfg["top_n"], 10)
    longs = sorted((signal.with_side(r, "long", cfg) for r in results),
                   key=lambda r: r["score"], reverse=True)[:n]
    taken = {r["symbol"] for r in longs}
    shorts = sorted((signal.with_side(r, "short", cfg) for r in results if r["symbol"] not in taken),
                    key=lambda r: r["score"])[:n]
    return longs, shorts


async def scan_tradfi() -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """(sabit liste: altın/gümüş/endeksler, BIST100 en iyi LONG, en iyi SHORT, veri alınamayanlar)."""
    cfg = settings.all_settings()
    insts = tradfi.instruments()
    all_frames = await asyncio.to_thread(tradfi.frames, insts)
    no_oc = {"available": False, "score": 0, "reason": "borsa dışı", "netflow_24h": None, "daily": [], "whales": []}
    fixed, stocks, failed = [], [], []
    for key, inst in insts.items():
        raw = all_frames.get(key)
        try:
            if raw is None:
                raise InsufficientData(f"{key}: veri yok")
            res = evaluate_frames(key, raw, cfg, no_oc, market=inst["market"], name=inst["name"])
        except InsufficientData as e:
            log.info("atlandı: %s", e)
            if inst["market"] == "tradfi":
                failed.append(inst["name"])
            continue
        (fixed if inst["market"] == "tradfi" else stocks).append(res)
    longs, shorts = _rank(stocks, cfg)
    return fixed, longs, shorts, failed


async def scan() -> tuple[list[dict], list[dict], list[str]]:
    """(en güçlü top_n LONG, en güçlü top_n SHORT, hata alan coinler)."""
    async with _scan_lock:
        cfg = settings.all_settings()
        symbols = await universe()
        sem = asyncio.Semaphore(8)

        async def one(sym):
            async with sem:
                return await analyze(sym, cfg)

        outcomes = await asyncio.gather(*(one(s) for s in symbols), return_exceptions=True)
        results, failed = [], []
        for sym, out in zip(symbols, outcomes):
            if isinstance(out, InsufficientData):
                log.info("atlandı: %s", out)
            elif isinstance(out, Exception):
                log.warning("analiz hatası %s: %s", sym, out)
                failed.append(sym)
            else:
                results.append(out)

        longs, shorts = _rank(results, cfg)
        db.save_signals(longs + shorts)
        return longs, shorts, failed
