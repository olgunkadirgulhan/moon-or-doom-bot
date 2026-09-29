"""Geçmiş on-chain borsa akışı (Etherscan tokentx) — tahmin gücü ölçümü ve backtest için.

Her (token, borsa cüzdanı) çifti için en yeniden geriye doğru blok blok sayfalanır (ücretsiz plan istek
başına en fazla 1.000 transfer döndürür; çift başına ≤MAX_CALLS istek). Bir tokenın verisi, TÜM cüzdanlarının kapsadığı en geç
başlangıçtan itibaren eksiksiz sayılır ("covered_from"); analiz yalnızca bu dönemde yapılır.
"""
import logging
import os
import pickle
import time

import httpx
import numpy as np
import pandas as pd

from core import ROOT, onchain

log = logging.getLogger(__name__)
CACHE = ROOT / "data" / "bt" / "onchain"
PAGE = 1_000  # ücretsiz planın gerçek sınırı (offset=10000 istense de 1000 döner)
MAX_CALLS = 60  # çift başına en fazla 60.000 transfer; yoğun cüzdanlarda kapsam kısa kalır ve raporlanır


async def fetch_pair(client: httpx.AsyncClient, chainid: int, contract: str, wallet: str,
                     since_ts: int, key: str) -> dict:
    path = CACHE / f"{chainid}_{contract.lower()[:12]}_{wallet[:12]}.pkl"
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        return pickle.loads(path.read_bytes())
    rows, endblock, complete, oldest = [], 99_999_999, False, None
    for _ in range(MAX_CALLS):
        batch = await onchain._get(client, {
            "chainid": chainid, "module": "account", "action": "tokentx", "contractaddress": contract,
            "address": wallet, "startblock": 0, "endblock": endblock, "page": 1, "offset": PAGE,
            "sort": "desc", "apikey": key}, timeout=180)
        if not batch:
            complete = True
            break
        rows += [(int(r["timeStamp"]), r["from"].lower(), r["to"].lower(),
                  int(r["value"]) / 10 ** int(r.get("tokenDecimal") or 18)) for r in batch]
        oldest = int(batch[-1]["timeStamp"])
        if len(batch) < PAGE or oldest < since_ts:
            complete = True
            break
        endblock = int(batch[-1]["blockNumber"]) - 1
    out = {"rows": [r for r in rows if r[0] >= since_ts],
           "covered_from": since_ts if complete else max(since_ts, oldest or since_ts)}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(out))
    return out


async def token_flows(symbol: str, since_ts: int) -> tuple[pd.DataFrame, int, int] | None:
    """(transferler: ts, signed_amount [+ borsadan çıkış, − borsaya giriş], kapsam başlangıcı, cüzdan sayısı)."""
    info = onchain.token_info(symbol)
    key = os.getenv("ETHERSCAN_API_KEY", "")
    if not info or not key:
        return None
    chainid = int(info["chainid"])
    wallets = onchain._wallets().get(chainid, {})
    if not wallets:
        return None
    covered, seen, flows = since_ts, set(), []
    async with httpx.AsyncClient() as client:
        for w in wallets:
            res = await fetch_pair(client, chainid, info["contract"], w, since_ts, key)
            covered = max(covered, res["covered_from"])
            for ts, frm, to, v in res["rows"]:
                if (ts, frm, to, v) in seen:
                    continue
                seen.add((ts, frm, to, v))
                from_ex, to_ex = frm in wallets, to in wallets
                if from_ex != to_ex:
                    flows.append((ts, v if from_ex else -v))
    df = pd.DataFrame(flows, columns=["ts", "amount"]).sort_values("ts")
    return df, covered, len(wallets)


def score_series(flows: pd.DataFrame, m15: pd.DataFrame, steps: list[int]) -> np.ndarray:
    """Her adım T için canlıdaki skorun aynısı: 100 × son 24s net akış $ ÷ (%5 × son 24s işlem hacmi $), ±100."""
    t15 = m15.index.as_unit("s").asi8
    close = m15["Close"].to_numpy()
    qvol = np.concatenate([[0.0], np.cumsum(m15["Volume"].to_numpy() * close)])
    ts = flows["ts"].to_numpy()
    idx = np.clip(np.searchsorted(t15, ts, side="right") - 1, 0, len(close) - 1)
    usd = np.concatenate([[0.0], np.cumsum(flows["amount"].to_numpy() * close[idx])])
    out = np.full(len(steps), np.nan)
    for i, T in enumerate(steps):
        net = usd[np.searchsorted(ts, T, side="left")] - usd[np.searchsorted(ts, T - 86400, side="left")]
        vol = qvol[np.searchsorted(t15, T, side="left")] - qvol[np.searchsorted(t15, T - 86400, side="left")]
        if vol > 0:
            out[i] = max(-100.0, min(100.0, 100 * net / (0.05 * vol)))
    return out
