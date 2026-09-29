"""Tahmin kaydı ve isabet değerlendirmesi — kalıcı dosyalar (repoda saklanır, kaybolmaz):

  tracking/predictions.csv  her rapordaki her tahmin
  tracking/outcomes.csv     24 saati dolmuş tahminlerin kesin sonucu (bir kez hesaplanır)
  tracking/results.csv      gönderilen her dönem özetinin (günlük … yıllık) kaydı

Her tahmin, verildiği andan itibaren en fazla 24 saat boyunca 15 dakikalık mumlarla
izlenir: önce SL'ye değerse ✗, önce TP1'e değerse ✓, 24 saatte hiçbirine değmediyse
"açık". Aynı mumda ikisi birden görülürse temkinli olup SL sayılır.
"""
import csv
import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core import ROOT, data, tradfi

TZ = ZoneInfo("Europe/Istanbul")
TRACK_DIR = ROOT / "tracking"
PRED_FILE = TRACK_DIR / "predictions.csv"
OUT_FILE = TRACK_DIR / "outcomes.csv"
RESULTS_FILE = TRACK_DIR / "results.csv"
PRED_FIELDS = ["ts", "symbol", "side", "signal", "score", "rr", "entry", "sl", "tp1", "tp2", "market"]
OUT_FIELDS = ["ts", "symbol", "side", "market", "outcome", "tp2_hit", "pnl"]
RESULT_FIELDS = ["sent_at", "period", "title", "total", "tp", "sl", "open", "accuracy",
                 "acc_crypto", "acc_tradfi", "acc_bist"]
TF = "15m"
TF_MS = 15 * 60 * 1000
HORIZON = 24 * 3600  # tahmin başına izleme süresi
MARKET_LABEL = {"crypto": "Kripto", "tradfi": "Altın/Gümüş/Endeks", "bist": "BIST hisse"}

# dönem → (ay sayısı, hangi ay sonlarında gönderilir)
LONG_PERIODS = {"3m": (3, {3, 6, 9, 12}), "6m": (6, {6, 12}), "9m": (9, {9}), "12m": (12, {12})}
PERIOD_NAMES = {"daily": "Günlük", "weekly": "Haftalık", "monthly": "Aylık",
                "3m": "3 Aylık", "6m": "6 Aylık", "9m": "9 Aylık", "12m": "Yıllık"}


def _read(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append(path, fields: list[str], rows: list[dict]) -> None:
    TRACK_DIR.mkdir(exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def _migrate_predictions() -> None:
    """Eski başlıkta `market` sütunu yoksa ekle (eski kayıtlar kripto)."""
    if not PRED_FILE.exists():
        return
    with open(PRED_FILE, encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    if "market" in header:
        return
    rows = _read(PRED_FILE)
    with open(PRED_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PRED_FIELDS)
        w.writeheader()
        w.writerows({**r, "market": "crypto"} for r in rows)


def record(results: list[dict]) -> None:
    _migrate_predictions()
    now = int(time.time())
    _append(PRED_FILE, PRED_FIELDS, [
        {"ts": now, **{k: r.get(k, "crypto") for k in PRED_FIELDS[1:]}} for r in results
    ])


def _key(p: dict) -> tuple:
    return int(p["ts"]), p["symbol"], p["side"], p.get("market") or "crypto"


def _load(since: int, until: int) -> list[dict]:
    out = []
    for r in _read(PRED_FILE):
        ts = int(r["ts"])
        if since <= ts <= until:
            out.append({**r, "ts": ts, "market": r.get("market") or "crypto",
                        **{k: float(r[k]) for k in ("score", "rr", "entry", "sl", "tp1", "tp2")}})
    return out


async def _crypto_candles(symbol: str, since_ms: int, until_ms: int) -> list[list]:
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


async def _candles(market: str, symbol: str, since_ms: int, until_ms: int) -> list[list]:
    if market == "crypto":
        return await _crypto_candles(symbol, since_ms, until_ms)
    return await tradfi.candles(symbol, since_ms, until_ms)


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


def _month_start(now: datetime, months_back: int) -> datetime:
    y, m = now.year, now.month - months_back
    while m <= 0:
        m, y = m + 12, y - 1
    return now.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)


def period_bounds(period: str, now: datetime | None = None) -> tuple[int, int, str]:
    """(başlangıç_ts, bitiş_ts, başlık)."""
    now = now or datetime.now(TZ)
    if period == "daily":
        start = now - timedelta(days=1)
        title = f"Günlük Sonuç — {now:%d.%m.%Y}"
    elif period == "weekly":
        start = now - timedelta(days=7)
        title = f"Haftalık Sonuç — {start:%d.%m} – {now:%d.%m.%Y}"
    elif period == "monthly":
        start = _month_start(now, 0)
        title = f"Aylık Sonuç — {now:%m.%Y}"
    else:
        months = LONG_PERIODS[period][0]
        start = _month_start(now, months - 1)
        title = f"{PERIOD_NAMES[period]} Sonuç — {start:%m.%Y} – {now:%m.%Y}"
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
        periods += [p for p, (_, months) in LONG_PERIODS.items() if now.month in months]
    return periods


def _bucket(ts: int, span_days: float) -> tuple[str, str]:
    """(sıralama anahtarı, etiket): ≤31 gün → gün, ≤186 gün → hafta, üstü → ay."""
    d = datetime.fromtimestamp(ts, TZ)
    if span_days <= 31:
        return d.strftime("%Y-%m-%d"), d.strftime("%d.%m")
    if span_days <= 186:
        monday = d - timedelta(days=d.weekday())
        return monday.strftime("%Y-%m-%d"), monday.strftime("%d.%m") + " hf"
    return d.strftime("%Y-%m"), d.strftime("%m.%Y")


async def evaluate(since: int, until: int) -> dict:
    """[since, until] aralığında verilen tahminleri değerlendirir; 24 saati dolanları kalıcı kaydeder."""
    names = {k: v["name"] for k, v in tradfi.instruments().items()}
    preds = [{**p, "name": names.get(p["symbol"], p["symbol"]) if p["market"] != "crypto" else p["symbol"]}
             for p in _load(since, until)]
    known = {_key(o): o for o in _read(OUT_FILE)}
    now = int(time.time())

    items, pending = [], defaultdict(list)
    for p in preds:
        o = known.get(_key(p))
        if o:
            items.append({**p, "outcome": o["outcome"], "tp2_hit": o["tp2_hit"] == "True", "pnl": float(o["pnl"])})
        else:
            pending[(p["market"], p["symbol"])].append(p)

    resolved = []
    for (market, sym), ps in pending.items():
        try:
            candles = await _candles(market, sym, min(p["ts"] for p in ps) * 1000,
                                     min(max(p["ts"] for p in ps) + HORIZON, until) * 1000)
        except Exception:  # noqa: BLE001 — veri yoksa bu turda "açık" kalır
            candles = []
        for p in ps:
            outcome, tp2, pnl = _outcome(p, candles)
            items.append({**p, "outcome": outcome, "tp2_hit": tp2, "pnl": pnl})
            if candles and p["ts"] + HORIZON <= now:
                resolved.append({"ts": p["ts"], "symbol": sym, "side": p["side"], "market": market,
                                 "outcome": outcome, "tp2_hit": tp2, "pnl": round(pnl, 4)})
    if resolved:
        _append(OUT_FILE, OUT_FIELDS, resolved)

    by_market = {m: [i for i in items if i["market"] == m] for m in MARKET_LABEL}
    groups = {MARKET_LABEL[m]: v for m, v in by_market.items() if v}
    groups |= {
        "LONG": [i for i in items if i["side"] == "long"],
        "SHORT": [i for i in items if i["side"] == "short"],
        "AL/SAT": [i for i in items if i["signal"] != "BEKLE"],
        "BEKLE": [i for i in items if i["signal"] == "BEKLE"],
        "R:R ≥ 1.5": [i for i in items if i["rr"] >= 1.5],
        "R:R < 1.5": [i for i in items if i["rr"] < 1.5],
    }
    span_days = (until - since) / 86400
    buckets = defaultdict(list)
    for i in items:
        buckets[_bucket(i["ts"], span_days)].append(i)
    return {
        "overall": _stats(items),
        "groups": {k: _stats(v) for k, v in groups.items()},
        "by_market": {m: _stats(v) for m, v in by_market.items()},
        "by_day": [(label, _stats(v)) for (_, label), v in sorted(buckets.items())],
        "coins": len({(i["market"], i["symbol"]) for i in items}),
        "items": items,
    }


def save_result(period: str, title: str, summary: dict) -> None:
    o, bm = summary["overall"], summary["by_market"]
    _append(RESULTS_FILE, RESULT_FIELDS, [{
        "sent_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"), "period": period, "title": title,
        **{k: o[k] for k in ("total", "tp", "sl", "open", "accuracy")},
        "acc_crypto": bm["crypto"]["accuracy"], "acc_tradfi": bm["tradfi"]["accuracy"],
        "acc_bist": bm["bist"]["accuracy"],
    }])
