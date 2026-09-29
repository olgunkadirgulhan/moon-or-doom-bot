"""İşlem adayı seçimi (strateji kuralları) ve %risk'e göre pozisyon büyüklüğü.

Kurallar (hepsi birden):
  1. Sinyal AL veya SAT (BEKLE asla)
  2. R:R ≥ cand_min_rr (varsayılan 2)
  3. Stop mesafesi ≤ likidasyon mesafesinin yarısı
  4. En fazla max_open aday; aynı yönde en fazla max_same_dir_crypto kripto; her varlık bir kez
  5. BIST hisseleri sadece seans saatinde (hafta içi 10:00–18:00 İstanbul)
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from core.chart import LIQ_BUFFER

TZ = ZoneInfo("Europe/Istanbul")


def bist_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    return now.weekday() < 5 and 10 <= now.hour < 18


def stop_pct(r: dict) -> float:
    return 100 * abs(r["entry"] - r["sl"]) / r["entry"]


def rejection(r: dict, cfg: dict) -> str | None:
    """Kural dışı kalma nedeni; None → aday olabilir."""
    liq_pct = 100 * LIQ_BUFFER / cfg["leverage"]
    if r["signal"] == "BEKLE":
        return "BEKLE"
    if r["rr"] < cfg["cand_min_rr"]:
        return "R:R düşük"
    if stop_pct(r) > liq_pct / 2:
        return "stop likidasyona yakın"
    if r.get("market") == "bist" and not bist_open():
        return "BIST kapalı"
    return None


def conviction(r: dict) -> float:
    return abs(r["score"] - 50)


def select(pool: list[dict], cfg: dict) -> list[dict]:
    """Kuralları geçen, kanaati en güçlü adaylar; her birine pozisyon büyüklüğü eklenir."""
    ok = sorted((r for r in pool if rejection(r, cfg) is None), key=conviction, reverse=True)
    chosen, seen = [], set()
    for r in ok:
        key = (r.get("market"), r["symbol"])
        same_dir = sum(c.get("market") == "crypto" and c["side"] == r["side"] for c in chosen)
        if key in seen or (r.get("market") == "crypto" and same_dir >= cfg["max_same_dir_crypto"]):
            continue
        seen.add(key)
        chosen.append(r)
        if len(chosen) >= cfg["max_open"]:
            break
    for r in chosen:
        r.update(sizing(r, cfg))
    return chosen


def sizing(r: dict, cfg: dict) -> dict:
    """Sermayenin risk_pct'i kadar risk: pozisyon = risk $ ÷ stop %; teminat = pozisyon ÷ kaldıraç."""
    risk_usd = cfg["capital_usd"] * cfg["risk_pct"] / 100
    sp = stop_pct(r) / 100
    position = risk_usd / sp if sp else 0.0
    reward = lambda price: position * abs(price - r["entry"]) / r["entry"]  # noqa: E731
    return {"risk_usd": risk_usd, "stop_pct": sp * 100, "position_usd": position,
            "margin_usd": position / cfg["leverage"], "tp1_usd": reward(r["tp1"]), "tp2_usd": reward(r["tp2"])}
