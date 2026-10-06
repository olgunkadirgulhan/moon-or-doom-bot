"""Trend Kırılımı stratejisi — günlük kapanıştan sonra bir kez çalışır (`python -m bot.oneshot trend`).

Kural (core/trend.py, backtest: tracking/research_trend.md):
  GİRİŞ  günlük kapanış > önceki 20 günün en yükseği, hacim > 1.3 × 20g ort., fiyat > EMA200, BTC düşüş trendinde değil,
         önceki gün volatilite (ATR/fiyat) son 120 günün alt yarısında (sıkışmadan çıkan kırılım)
  STOP   giriş − 2 × ATR(14, günlük)
  ÇIKIŞ  avize stop: her günlük kapanışta stop = max(stop, en yüksek kapanış − 3 × ATR); en fazla 30 gün
  RİSK   işlem başına sermayenin %0.5'i, en fazla 6 açık pozisyon (sinyaller aynı günlerde kümelenir)

Durum: tracking/trend_positions.json · kapanan işlemler: tracking/trend_results.csv
"""
import csv
import json
import logging
import time

import numpy as np
from telegram.constants import ParseMode

from core import ROOT, data, onchain, settings, trend
from core.indicators import add_indicators

log = logging.getLogger(__name__)
STATE = ROOT / "tracking" / "trend_positions.json"
RESULTS = ROOT / "tracking" / "trend_results.csv"
FIELDS = ["symbol", "entry_ts", "exit_ts", "entry", "exit", "initial_stop", "r", "reason"]
RISK_PCT, MAX_OPEN, MAX_DAYS = 0.5, 6, 30


def _load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"open": []}


def _save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n")


def _record(rows: list[dict]) -> None:
    new = not RESULTS.exists()
    with RESULTS.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


async def _daily(symbol: str):
    df = await data.fetch_ohlcv(symbol, "1d", limit=300)
    df = df.iloc[:-1]  # son mum açık (bugün) → sadece kapanmış günler
    return add_indicators(df) if len(df) >= 210 else None


def _fmt(x: float) -> str:
    return f"{x:,.2f}" if x >= 100 else f"{x:.4g}"


async def run(bot, chat_id: int) -> None:
    state, now = _load(), int(time.time())
    btc = await _daily("BTC")
    btc_up = btc is not None and trend.daily_trend(btc)[-1] != -1
    msgs, closed = [], []

    # 1) açık pozisyonlar: stop vuruldu mu, stop güncelle, süre
    still = []
    for p in state["open"]:
        d1 = await _daily(p["symbol"])
        if d1 is None:
            still.append(p)
            continue
        new_days = d1[d1.index.as_unit("s").asi8 > p["last_day"]]
        exit_px, reason = None, None
        for ts, row in zip(new_days.index.as_unit("s").asi8, new_days.itertuples()):
            if row.Low <= p["stop"]:
                exit_px, reason = p["stop"], "stop"
                break
            p["best"] = max(p["best"], row.Close)
            if row.atr14 == row.atr14:
                p["stop"] = max(p["stop"], p["best"] - 3 * row.atr14)
            p["last_day"] = int(ts)
        if exit_px is None and now - p["entry_ts"] > MAX_DAYS * 86400:
            exit_px, reason = float(d1["Close"].iloc[-1]), "süre (30 gün)"
        if exit_px is not None:
            r = (exit_px - p["entry"]) / (p["entry"] - p["initial_stop"])
            closed.append({"symbol": p["symbol"], "entry_ts": p["entry_ts"], "exit_ts": now, "entry": p["entry"],
                           "exit": exit_px, "initial_stop": p["initial_stop"], "r": round(r, 2), "reason": reason})
            msgs.append(f"{'✅' if r > 0 else '❌'} <b>{p['symbol']}</b> kapandı ({reason}): {r:+.2f}R")
        else:
            if p["stop"] > p.get("notified_stop", p["initial_stop"]) * 1.001:
                msgs.append(f"🔼 <b>{p['symbol']}</b> stopu yükselt: {_fmt(p['stop'])} "
                            f"({100 * (p['stop'] / p['entry'] - 1):+.1f}% girişe göre)")
                p["notified_stop"] = p["stop"]
            still.append(p)
    state["open"] = still

    # 2) yeni kırılımlar
    universe = list(dict.fromkeys(["BTC"] + await data.top_by_volume(settings.get("universe_size"),
                                                                       settings.get("min_volume_usd"))
                                  + onchain.manual_coins()))
    cands = []
    if btc_up:
        for s in universe:
            if any(p["symbol"] == s for p in state["open"]):
                continue
            d1 = await _daily(s)
            if d1 is None:
                continue
            c, hi, vol, vma = d1["Close"].to_numpy(), d1["High"].to_numpy(), d1["Volume"].to_numpy(), \
                d1["vol_ma20"].to_numpy()
            atr, e200 = float(d1["atr14"].iloc[-1]), float(d1["ema200"].iloc[-1])
            n = trend.BREAKOUT["lookback"]
            if np.isnan(atr) or np.isnan(vma[-1]):
                continue
            sq = trend.squeeze_rank(d1)[-2]  # kırılımdan önceki gün
            if c[-1] > hi[-n - 1:-1].max() and vol[-1] > trend.BREAKOUT["vol_mult"] * vma[-1] and c[-1] > e200 \
                    and sq == sq and sq < trend.BREAKOUT["squeeze_max"]:
                cands.append((1 - sq, s, float(c[-1]), atr, int(d1.index.as_unit("s").asi8[-1]), vol[-1] / vma[-1], sq))
    slots = MAX_OPEN - len(state["open"])
    for _rank, s, close, atr, day, strength, sq in sorted(cands, reverse=True)[:max(0, slots)]:
        stop = close - trend.BREAKOUT["atr_stop"] * atr
        cap = float(settings.get("capital_usd"))
        size = cap * RISK_PCT / 100 / (close - stop) * close
        state["open"].append({"symbol": s, "entry": close, "initial_stop": stop, "stop": stop, "best": close,
                              "entry_ts": now, "last_day": day, "notified_stop": stop})
        msgs.append(f"🚀 <b>{s} — Trend Kırılımı (AL)</b>\n"
                    f"Giriş ~{_fmt(close)} · Stop {_fmt(stop)} ({100 * (stop / close - 1):.1f}%)\n"
                    f"Sıkışmadan çıkış (volatilite 120 günün %{100 * sq:.0f}'lik diliminde) · "
                    f"hacim 20g ort. {strength:.1f}×\nHedef yok: stop her gün "
                    f"en yüksek kapanış − 3 ATR'ye çekilir\n"
                    f"Risk %{RISK_PCT:g} → pozisyon ≈ {size:,.0f}$ ({cap:,.0f}$ sermayede)")
    if not btc_up:
        msgs.append("⏸ BTC günlük düşüş trendinde: yeni trend kırılımı sinyali yok.")
    elif slots <= 0 and cands:
        msgs.append(f"ℹ️ {len(cands)} kırılım var ama {MAX_OPEN} açık pozisyon dolu.")

    _record(closed)
    _save(state)
    if msgs:
        head = (f"📈 <b>Trend Kırılımı</b> · açık {len(state['open'])}/{MAX_OPEN}\n"
                "<i>Backtest: tracking/research_trend.md · Yatırım tavsiyesi değildir.</i>\n\n")
        await bot.send_message(chat_id, head + "\n\n".join(msgs), parse_mode=ParseMode.HTML)
    log.info("trend: %d mesaj, %d açık, %d kapandı", len(msgs), len(state["open"]), len(closed))
