"""Tahmin kaydı (tracking/predictions.csv) ve haftalık/aylık isabet değerlendirmesi.

Her tahmin, verildiği andan itibaren en fazla 24 saat boyunca 15 dakikalık mumlarla
izlenir: önce SL'ye değerse ✗, önce TP1'e değerse ✓, 24 saatte hiçbirine değmediyse
"açık". Aynı mumda ikisi birden görülürse temkinli olup SL sayılır.
"""
import csv
import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core import ROOT, data

TZ = ZoneInfo("Europe/Istanbul")
TRACK_DIR = ROOT / "tracking"
PRED_FILE = TRACK_DIR / "predictions.csv"
PRED_FIELDS = ["ts", "symbol", "side", "signal", "score", "rr", "entry", "sl", "tp1", "tp2"]
TF = "15m"
TF_MS = 15 * 60 * 1000
HORIZON = 24 * 3600  # tahmin başına izleme süresi


def record(results: list[dict]) -> None:
    TRACK_DIR.mkdir(exist_ok=True)
    new = not PRED_FILE.exists()
    now = int(time.time())
    with open(PRED_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PRED_FIELDS)
        if new:
            w.writeheader()
        for r in results:
            w.writerow({"ts": now, **{k: r[k] for k in PRED_FIELDS[1:]}})


def _load(since: int, until: int) -> list[dict]:
    if not PRED_FILE.exists():
        return []
    with open(PRED_FILE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        ts = int(r["ts"])
        if since <= ts <= until:
            out.append({**r, "ts": ts, **{k: float(r[k]) for k in ("score", "rr", "entry", "sl", "tp1", "tp2")}})
    return out


async def _candles(symbol: str, since_ms: int, until_ms: int) -> list[list]:
    rows, cursor = [], since_ms
    while cursor < until_ms:
        batch = await data.exchange().fetch_ohlcv(f"{symbol}/USDT", TF, since=cursor, limit=1000)
        if not batch:
            break
        rows += [b for b in batch if b[0] < until_ms]
        cursor = batch[-1][0] + TF_MS
        if len(batch) < 1000:
            break
    return rows


def _outcome(p: dict, candles: list[list]) -> tuple[str, bool, float]:
    """(TP/SL/OPEN, tp2'ye ulaştı mı, son fiyata göre % kâr/zarar)."""
    long = p["side"] == "long"
    start, end = p["ts"] * 1000, (p["ts"] + HORIZON) * 1000
    tp2_hit = False
    last = p["entry"]
    for t, _o, high, low, close, _v in candles:
        if t < start:
            continue
        if t >= end:
            break
        last = close
        hit_sl = low <= p["sl"] if long else high >= p["sl"]
        hit_tp = high >= p["tp1"] if long else low <= p["tp1"]
        if hit_sl:
            return "SL", tp2_hit, _pnl(p, p["sl"])
        if hit_tp:
            tp2_hit = high >= p["tp2"] if long else low <= p["tp2"]
            return "TP", tp2_hit, _pnl(p, p["tp2"] if tp2_hit else p["tp1"])
    return "OPEN", False, _pnl(p, last)


def _pnl(p: dict, price: float) -> float:
    change = (price - p["entry"]) / p["entry"] * 100
    return change if p["side"] == "long" else -change


def _stats(items: list[dict]) -> dict:
    tp = sum(i["outcome"] == "TP" for i in items)
    sl = sum(i["outcome"] == "SL" for i in items)
    op = sum(i["outcome"] == "OPEN" for i in items)
    return {"total": len(items), "tp": tp, "sl": sl, "open": op,
            "accuracy": round(100 * tp / (tp + sl), 1) if tp + sl else None}


def period_bounds(period: str, now: datetime | None = None) -> tuple[int, int, str]:
    """(başlangıç_ts, bitiş_ts, başlık) — daily: son 24 saat, weekly: son 7 gün, monthly: ayın 1'inden bugüne."""
    now = now or datetime.now(TZ)
    if period == "daily":
        start = now - timedelta(days=1)
        title = f"Günlük Sonuç — {now:%d.%m.%Y}"
    elif period == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        title = f"Aylık Sonuç — {now:%m.%Y}"
    else:
        start = now - timedelta(days=7)
        title = f"Haftalık Sonuç — {start:%d.%m} – {now:%d.%m.%Y}"
    return int(start.timestamp()), int(now.timestamp()), title


def is_last_day_of_month(now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    return (now + timedelta(days=1)).month != now.month


def due_periods(now: datetime | None = None) -> list[str]:
    """Akşam sonuç çalışmasında bugün gönderilecek dönemler."""
    now = now or datetime.now(TZ)
    periods = ["daily"]
    if now.weekday() == 5:  # cumartesi
        periods.append("weekly")
    if is_last_day_of_month(now):
        periods.append("monthly")
    return periods


async def evaluate(since: int, until: int) -> dict:
    """[since, until] aralığında verilen tahminleri değerlendirir."""
    preds = _load(since, until)
    by_symbol = defaultdict(list)
    for p in preds:
        by_symbol[p["symbol"]].append(p)

    items = []
    for sym, ps in by_symbol.items():
        try:
            candles = await _candles(sym, min(p["ts"] for p in ps) * 1000,
                                     min(max(p["ts"] for p in ps) + HORIZON, until) * 1000)
        except Exception:  # noqa: BLE001 — veri yoksa o coin "açık" kalır
            candles = []
        for p in ps:
            outcome, tp2, pnl = _outcome(p, candles)
            items.append({**p, "outcome": outcome, "tp2_hit": tp2, "pnl": pnl})

    groups = {
        "LONG": [i for i in items if i["side"] == "long"],
        "SHORT": [i for i in items if i["side"] == "short"],
        "AL/SAT": [i for i in items if i["signal"] != "BEKLE"],
        "BEKLE": [i for i in items if i["signal"] == "BEKLE"],
        "R:R ≥ 1.5": [i for i in items if i["rr"] >= 1.5],
        "R:R < 1.5": [i for i in items if i["rr"] < 1.5],
    }
    by_day = defaultdict(list)
    for i in items:
        by_day[datetime.fromtimestamp(i["ts"], TZ).strftime("%d.%m")].append(i)
    return {
        "overall": _stats(items),
        "groups": {k: _stats(v) for k, v in groups.items()},
        # tahminin verildiği güne göre doğruluk (grafikteki çizgi)
        "by_day": [(d, _stats(v)) for d, v in sorted(by_day.items(), key=lambda kv: kv[1][0]["ts"])],
        "coins": len(by_symbol),
        "items": items,
    }
