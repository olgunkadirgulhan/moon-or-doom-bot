"""Tek coin analizi ve tüm izleme listesinin taranıp sıralanması."""
import asyncio
import logging

from core import data, db, levels, onchain, settings, signal
from core.indicators import add_indicators, last_atr

log = logging.getLogger(__name__)
_scan_lock = asyncio.Lock()


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
    frames = {tf: add_indicators(df) for tf, df in raw.items()}
    price = float(frames["1h"]["Close"].iloc[-1])
    lv = {tf: levels.compute_levels(df, tf, price) for tf, df in frames.items()}
    levels.annotate_confluence(lv, 0.5 * last_atr(frames["4h"]))

    volume = (await data.tickers()).get(symbol, {}).get("volume", 0.0)
    oc = await onchain.analyze(symbol, price, volume)
    res = signal.evaluate(symbol, frames, lv, oc, cfg)
    res.update(frames=frames, levels=lv, onchain=oc, volume_24h=volume)
    return res


async def scan() -> tuple[list[dict], list[str]]:
    """(skora göre azalan ilk top_n sonuç, hata alan coinler)."""
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
            if isinstance(out, Exception):
                log.warning("analiz hatası %s: %s", sym, out)
                failed.append(sym)
            else:
                results.append(out)

        results.sort(key=lambda r: r["score"], reverse=True)
        top = results[: max(cfg["top_n"], 10)]
        db.save_signals(top)
        return top, failed
