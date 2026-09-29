"""Etherscan API V2 ile borsa giriş/çıkış (netflow) ve balina transferleri.

Her (token, borsa cüzdanı) çifti için `tokentx` çekilir; son 7 günlük transferler
giriş (→ borsa, satış baskısı) / çıkış (borsa →, birikim) olarak toplanır.
"""
import asyncio
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import httpx
import yaml

from core import ROOT, db

API = "https://api.etherscan.io/v2/api"
CACHE_TTL = 900
DAYS = 7
MIN_INTERVAL = 0.22  # free tier: 5 çağrı/sn
WHALE_USD = 250_000
WHALE_VOL_PCT = 0.005
TZ = ZoneInfo("Europe/Istanbul")

_sem = asyncio.Semaphore(4)
_rate_lock = asyncio.Lock()
_last_call = 0.0


@lru_cache
def _coins() -> dict:
    with open(ROOT / "config" / "coins.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def _wallets() -> dict[int, dict[str, str]]:
    """{chainid: {adres_lower: borsa}}"""
    with open(ROOT / "config" / "exchange_wallets.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {
        int(chain): {a.lower(): ex for ex, addrs in exchanges.items() for a in addrs}
        for chain, exchanges in raw.items()
    }


def manual_coins() -> list[str]:
    return [c.upper() for c in _coins().get("manual", [])]


def token_info(symbol: str) -> dict | None:
    return (_coins().get("tokens") or {}).get(symbol)


def _unavailable(reason: str) -> dict:
    return {"available": False, "score": 0, "reason": reason, "netflow_24h": None, "daily": [], "whales": []}


async def _get(client: httpx.AsyncClient, params: dict) -> list[dict]:
    global _last_call
    async with _sem:
        for attempt in range(3):
            async with _rate_lock:
                wait = MIN_INTERVAL - (time.monotonic() - _last_call)
                if wait > 0:
                    await asyncio.sleep(wait)
                _last_call = time.monotonic()
            r = await client.get(API, params=params, timeout=20)
            r.raise_for_status()
            body = r.json()
            result = body.get("result")
            if body.get("status") == "1" and isinstance(result, list):
                return result
            if isinstance(result, list) or "No transactions" in str(body.get("message")):
                return []
            if "rate limit" in str(result).lower() and attempt < 2:
                await asyncio.sleep(1.0 + attempt)
                continue
            raise RuntimeError(str(result or body.get("message"))[:120])
    return []


async def _transfers(chainid: int, contract: str, wallet: str, key: str) -> list[dict]:
    ck = f"tokentx:{chainid}:{contract.lower()}:{wallet}"
    cached = db.cache_get(ck, CACHE_TTL)
    if cached is not None:
        return cached
    params = {
        "chainid": chainid, "module": "account", "action": "tokentx",
        "contractaddress": contract, "address": wallet,
        "page": 1, "offset": 1000, "sort": "desc", "apikey": key,
    }
    async with httpx.AsyncClient() as client:
        rows = await _get(client, params)
    cutoff = time.time() - DAYS * 86400
    slim = [
        {"t": int(r["timeStamp"]), "from": r["from"].lower(), "to": r["to"].lower(),
         "v": int(r["value"]) / 10 ** int(r.get("tokenDecimal") or 18)}
        for r in rows if int(r["timeStamp"]) >= cutoff
    ]
    db.cache_set(ck, slim)
    return slim


async def analyze(symbol: str, price: float, volume_24h: float) -> dict:
    info = token_info(symbol)
    key = os.getenv("ETHERSCAN_API_KEY", "")
    if not info:
        return _unavailable("EVM kontrat yok")
    if not key:
        return _unavailable("API key yok")
    chainid = int(info["chainid"])
    wallets = _wallets().get(chainid, {})
    if not wallets:
        return _unavailable(f"chain {chainid} için borsa cüzdanı yok")

    try:
        batches = await asyncio.gather(
            *(_transfers(chainid, info["contract"], w, key) for w in wallets)
        )
    except Exception as e:  # noqa: BLE001 — ağ/API hatası skoru bozmasın
        return _unavailable(f"API: {str(e)[:40]}")

    # Aynı transfer iki cüzdanın sorgusunda da görünebilir → tekilleştir
    seen, txs = set(), []
    for batch in batches:
        for t in batch:
            k = (t["t"], t["from"], t["to"], t["v"])
            if k not in seen:
                seen.add(k)
                txs.append(t)

    now = time.time()
    whale_min = min(WHALE_USD, WHALE_VOL_PCT * volume_24h) if volume_24h else WHALE_USD
    today = datetime.now(TZ).date()
    daily = {today - timedelta(days=i): 0.0 for i in range(DAYS - 1, -1, -1)}
    inflow = outflow = 0.0
    whales = []

    for t in txs:
        from_ex, to_ex = wallets.get(t["from"]), wallets.get(t["to"])
        if bool(from_ex) == bool(to_ex):
            continue  # borsa içi veya borsa dışı transfer
        usd = t["v"] * price
        signed = usd if from_ex else -usd  # çıkış +, giriş −
        day = datetime.fromtimestamp(t["t"], TZ).date()
        if day in daily:
            daily[day] += signed
        if now - t["t"] <= 86400:
            if from_ex:
                outflow += usd
            else:
                inflow += usd
        if usd >= whale_min and now - t["t"] <= 86400:
            whales.append({"usd": usd, "dir": "out" if from_ex else "in", "exchange": from_ex or to_ex})

    netflow = outflow - inflow
    # netflow, 24s hacmin %5'ine ulaşınca skor ±100'e doyar (%1'de büyük tokenların çoğu hep ±100 çıkıyordu)
    scale = max(volume_24h * 0.05, 1.0)
    score = max(-100.0, min(100.0, 100.0 * netflow / scale))
    return {
        "available": True,
        "score": round(score, 1),
        "netflow_24h": netflow,
        "inflow_24h": inflow,
        "outflow_24h": outflow,
        "daily": [(d.strftime("%d.%m"), v) for d, v in daily.items()],
        "whales": sorted(whales, key=lambda w: -w["usd"])[:5],
        "reason": "",
    }
