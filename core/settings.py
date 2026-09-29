"""Çalışma zamanı ayarları: varsayılanlar + /settings ile SQLite'a yazılan değişiklikler."""
import copy

from core import db

DEFAULTS = {
    "buy_threshold": 65,
    "sell_threshold": 35,
    "min_rr": 1.5,
    "rr_penalty": 10,
    "report_hours": [3, 7, 11, 15, 19, 23],
    "margin_usd": 1000,
    "leverage": 10,
    # strateji: işlem adayları ve sanal hesap
    "capital_usd": 1000,
    "risk_pct": 1.0,
    "cand_min_rr": 2.5,  # backtest 29.09.2026: 2.5 hem eğitimde hem testte artı (tracking/backtest.md)
    "horizon_h": 72,  # strateji işlem süresi (saat); isabet ölçümü 24 saat kalır
    "max_open": 3,
    "max_same_dir_crypto": 2,
    "calc_url": "https://olgunkadirgulhan.github.io/moon-or-doom-calc/",
    "min_volume_usd": 20_000_000,  # likidite filtresi (kripto evreni)
    "regime_filter": True,  # BTC / BIST100 günlük trendine karşı işlem adayı yok
    "entry_mode": "limit",  # limit = en yakın güçlü seviyede 12 saat bekle (backtest'te tutarlı), market = güncel fiyat
    "result_hour": 20,
    "top_n": 10,
    "universe_size": 40,
    "alerts": False,
    "charts": False,
    "weights": {"trend": 25, "proximity": 25, "rsi": 15, "confluence": 15, "onchain": 20},
}


def all_settings() -> dict:
    merged = copy.deepcopy(DEFAULTS)
    stored = db.kv_get("settings", {})
    for k, v in stored.items():
        if k == "weights":
            merged["weights"].update(v)
        elif k in merged:
            merged[k] = v
    return merged


def get(key: str):
    return all_settings()[key]


def _parse(default, raw: str):
    if isinstance(default, bool):
        if raw.lower() in ("1", "true", "on", "acik", "açık", "evet"):
            return True
        if raw.lower() in ("0", "false", "off", "kapali", "kapalı", "hayir", "hayır"):
            return False
        raise ValueError("on/off bekleniyor")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, str):
        return raw
    if isinstance(default, list):
        return sorted({int(x) for x in raw.replace(" ", "").split(",") if x})
    raise ValueError("desteklenmeyen tip")


def set_value(key: str, raw: str) -> None:
    """`key` düz anahtar veya `weights.trend` gibi noktalı olabilir."""
    stored = db.kv_get("settings", {})
    if key.startswith("weights."):
        sub = key.split(".", 1)[1]
        if sub not in DEFAULTS["weights"]:
            raise KeyError(key)
        stored.setdefault("weights", {})[sub] = int(raw)
    else:
        if key not in DEFAULTS or key == "weights":
            raise KeyError(key)
        value = _parse(DEFAULTS[key], raw)
        if key == "report_hours":
            if len(value) < 4 or any(not 0 <= h <= 23 for h in value):
                raise ValueError("en az 4 saat, 0-23 arası")
        if key == "top_n" and value < 10:
            raise ValueError("top_n en az 10")
        stored[key] = value
    db.kv_set("settings", stored)
