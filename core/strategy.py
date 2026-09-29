"""İşlem adayı seçimi (strateji kuralları) ve %risk'e göre pozisyon büyüklüğü.

Kurallar (hepsi birden):
  1. Sinyal AL veya SAT (BEKLE asla)
  2. R:R ≥ cand_min_rr (varsayılan 2)
  3. Stop mesafesi ≤ likidasyon mesafesinin yarısı
  4. En fazla max_open aday; aynı yönde en fazla max_same_dir_crypto kripto; her varlık bir kez
  5. BIST hisseleri sadece seans saatinde (hafta içi 10:00–18:00 İstanbul)
  6. Rejim: BTC (kripto) / BIST100 (hisse) günlük trendi düşüşteyse long, yükselişteyse short yok
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


def regime(df_1d) -> str:
    """Günlük trend: up (fiyat ve EMA50 > EMA200), down (ikisi de altında), aksi halde neutral."""
    row = df_1d.iloc[-1]
    close, e50, e200 = row["Close"], row["ema50"], row["ema200"]
    if e200 != e200 or e50 != e50:  # NaN: yeterli geçmiş yok
        return "neutral"
    if close > e200 and e50 > e200:
        return "up"
    if close < e200 and e50 < e200:
        return "down"
    return "neutral"


REGIME_KEY = {"crypto": "crypto", "bist": "bist"}  # altın/gümüş/endeks sabit listesi rejim filtresiz


def rejection(r: dict, cfg: dict, regimes: dict | None = None, check_session: bool = True) -> str | None:
    """Kural dışı kalma nedeni; None → aday olabilir."""
    liq_pct = 100 * LIQ_BUFFER / cfg["leverage"]
    if r["signal"] == "BEKLE":
        return "BEKLE"
    if r["rr"] < cfg["cand_min_rr"]:
        return "R:R düşük"
    if stop_pct(r) > liq_pct / 2:
        return "stop likidasyona yakın"
    if check_session and r.get("market") == "bist" and not bist_open():
        return "BIST kapalı"
    if cfg.get("regime_filter") and regimes:
        reg = regimes.get(REGIME_KEY.get(r.get("market") or "crypto"))
        if r["side"] == "long" and reg == "down":
            return "piyasa düşüş trendinde"
        if r["side"] == "short" and reg == "up":
            return "piyasa yükseliş trendinde"
    return None


def conviction(r: dict) -> float:
    return abs(r["score"] - 50)


def select(pool: list[dict], cfg: dict, regimes: dict | None = None, check_session: bool = True,
           active: list[dict] | None = None, enforce_limits: bool = True) -> list[dict]:
    """Kuralları geçen, kanaati en güçlü adaylar; her birine pozisyon büyüklüğü eklenir.
    active: zaten açık/bekleyen işlemler — aynı varlık yeniden önerilmez; enforce_limits=True ise
    işlem sayısı ve aynı yön limitlerine de sayılır. enforce_limits=False: kuralı geçen herkes (seçim kullanıcıda)."""
    active = active or []
    cap = cfg["max_open"] if enforce_limits else cfg.get("max_candidates", 10)
    if enforce_limits and len(active) >= cap:
        return []
    ok = sorted((r for r in pool if rejection(r, cfg, regimes, check_session) is None), key=conviction, reverse=True)
    chosen, seen = [], {(a.get("market"), a["symbol"]) for a in active}
    for r in ok:
        key = (r.get("market"), r["symbol"])
        if key in seen:
            continue
        if enforce_limits:
            same_dir = sum(c.get("market") == "crypto" and c["side"] == r["side"] for c in chosen + active)
            if r.get("market") == "crypto" and same_dir >= cfg["max_same_dir_crypto"]:
                continue
        seen.add(key)
        chosen.append(r)
        if len(chosen) + (len(active) if enforce_limits else 0) >= cap:
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
