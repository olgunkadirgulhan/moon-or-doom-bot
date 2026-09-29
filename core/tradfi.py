"""Kripto dışı piyasalar (Yahoo Finance): altın/gümüş (ons, gram $, gram ₺), BIST endeksleri ve BIST100 hisseleri.

1h ve 1d mumlar indirilir; 4h/8h, 1h'ten yeniden örneklenir. Gram ve TL fiyatları
vadeli ons fiyatından türetilir (bkz. config/tradfi.yaml).
"""
import asyncio
import logging
import threading
import time
import warnings
from functools import lru_cache

import pandas as pd
import yaml
import yfinance as yf

from core import ROOT

log = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", module="yfinance")

LIMIT = 300
CACHE_TTL = 600
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


@lru_cache
def config() -> dict:
    with open(ROOT / "config" / "tradfi.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def instruments() -> dict[str, dict]:
    """{anahtar: {name, ticker, div?, fx?, market}} — sabit liste + BIST100 hisseleri."""
    cfg = config()
    out = {k: {**v, "market": "tradfi"} for k, v in cfg["fixed"].items()}
    for s in cfg["bist100"]:
        out[s] = {"name": s, "ticker": f"{s}.IS", "market": "bist"}
    return out


def _utc(df: pd.DataFrame) -> pd.DataFrame:
    idx = df.index
    df.index = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    return df


def _download(tickers: tuple[str, ...], period: str, interval: str) -> dict[str, pd.DataFrame]:
    key = (tickers, period, interval)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    raw = yf.download(list(tickers), period=period, interval=interval, group_by="ticker",
                      progress=False, auto_adjust=False, threads=True)
    out = {}
    for t in tickers:
        if t not in raw.columns.get_level_values(0):
            continue
        df = raw[t][list(AGG)].dropna(subset=["Close"])
        if not df.empty:
            out[t] = _utc(df.astype(float).fillna({"Volume": 0.0}))
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def _compose(inst: dict, data: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    df = data.get(inst["ticker"])
    if df is None:
        return None
    df = df.copy()
    if inst.get("fx"):
        fx = data.get(inst["fx"])
        if fx is None:
            return None
        rate = fx["Close"].reindex(df.index, method="ffill").bfill()
        for c in ("Open", "High", "Low", "Close"):
            df[c] = df[c] * rate
    if inst.get("div"):
        for c in ("Open", "High", "Low", "Close"):
            df[c] = df[c] / inst["div"]
    return df.dropna(subset=["Close"])


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule, label="left", closed="left").agg(AGG).dropna(subset=["Close"])


def _tickers(insts: dict) -> tuple[str, ...]:
    return tuple(sorted({i["ticker"] for i in insts.values()} | {i["fx"] for i in insts.values() if i.get("fx")}))


def frames(insts: dict) -> dict[str, dict[str, pd.DataFrame]]:
    """{anahtar: {1h, 4h, 8h, 1d: DataFrame}} — senkron, to_thread ile çağır."""
    tickers = _tickers(insts)
    h1 = _download(tickers, "365d", "60m")
    d1 = _download(tickers, "2y", "1d")
    out = {}
    for key, inst in insts.items():
        hourly, daily = _compose(inst, h1), _compose(inst, d1)
        if hourly is None or daily is None:
            continue
        out[key] = {
            "1h": hourly.tail(LIMIT),
            "4h": _resample(hourly, "4h").tail(LIMIT),
            "8h": _resample(hourly, "8h").tail(LIMIT),
            "1d": daily.tail(LIMIT),
        }
    return out


async def candles(key: str, since_ms: int, until_ms: int) -> list[list]:
    """Tahmin takibi için 15 dk mumlar [[t_ms, o, h, l, c, v], ...] (Yahoo en fazla 60 gün geriye verir)."""
    inst = instruments().get(key)
    if not inst:
        return []
    data = await asyncio.to_thread(_download, _tickers({key: inst}), "60d", "15m")
    df = _compose(inst, data)
    if df is None:
        return []
    ms = df.index.as_unit("ms").asi8  # pandas 2: indeks birimi ns olmayabilir
    return [[int(t), o, h, lo, c, v] for t, (o, h, lo, c, v) in zip(ms, df[list(AGG)].itertuples(index=False))
            if since_ms <= t < until_ms]
