"""İşlem adaylarının canlı takibi: limit doldu mu, TP1 (stopu girişe çek), TP2/stop/başabaş/süre doldu.

Her olay bir kez bildirilir (tracking/positions_state.json repoda saklanır). Aynı varlıkta ve yönde
aktif bir aday varken sonraki raporların aynı adayı yeni işlem sayılmaz (tek pozisyon).
"""
import html
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Bot
from telegram.constants import ParseMode

from core import chart, tracker

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Istanbul")
STATE_FILE = tracker.TRACK_DIR / "positions_state.json"
ACTIVE = {"PENDING", "OPEN", "OPEN_BE"}
CLOSED = {"TP2", "SL", "BE", "TIME", "EXPIRED"}


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    tracker.TRACK_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _key(p: dict) -> str:
    return f"{p['ts']}|{p['market']}|{p['symbol']}|{p['side']}"


def _hhmm(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m %H:%M")


async def positions(cfg: dict, now: int | None = None) -> list[dict]:
    """Takipteki tüm adayların güncel durumu (en yenisi önce). Aynı varlık+yönde aktif olan ilk aday esas alınır."""
    now = now or int(time.time())
    horizon = cfg["horizon_h"] * 3600
    window = tracker.FILL_H * 3600 + horizon + 12 * 3600
    cands = sorted((p for p in tracker._load(now - window, now) if p["candidate"]), key=lambda p: p["ts"])
    groups = defaultdict(list)
    for p in cands:
        groups[(p["market"], p["symbol"])].append(p)

    out = []
    for (market, sym), ps in groups.items():
        try:
            candles = await tracker._candles(market, sym, ps[0]["ts"] * 1000, now * 1000)
        except Exception:  # noqa: BLE001
            log.exception("mum alınamadı %s", sym)
            continue
        busy_until = {}  # yön → aktif pozisyonun bittiği an
        for p in ps:
            if busy_until.get(p["side"], 0) > p["ts"]:
                continue  # aynı işlem zaten takipte: tekrar eden aday
            lc = tracker.lifecycle(p, candles, now, horizon)
            done_at = max([ts for _, ts in lc["events"]], default=now) if lc["state"] in CLOSED else now + horizon
            busy_until[p["side"]] = done_at
            out.append({**p, **lc})
    return sorted(out, key=lambda x: -x["ts"])


EVENT_TEXT = {
    "FILLED": ("🟡", "LİMİT EMİR DOLDU", "Stop ve TP emirlerinin girili olduğunu kontrol et."),
    "EXPIRED": ("⌛", "LİMİT EMİR 12 SAATTE DOLMADI", "Emri İPTAL ET."),
    "TP1": ("🎯", "TP1 GELDİ", "Pozisyonun yarısı kapandı → STOPU GİRİŞE ÇEK: {entry}"),
    "TP2": ("✅", "TP2 GELDİ — İŞLEM KAPANDI", "Sonuç: {r}"),
    "SL": ("🛑", "STOP OLDU — İŞLEM KAPANDI", "Sonuç: {r}. Planlanan kayıp, kural işledi."),
    "BE": ("⚪", "BAŞABAŞ — KALAN YARI GİRİŞTEN KAPANDI", "Sonuç: {r} (TP1'de alınan kâr cepte)."),
    "TIME": ("⏱", "SÜRE DOLDU ({h} saat)", "Pozisyonu KAPAT. Anlık sonuç: {r}"),
}


def _event_msg(p: dict, event: str, ts: int, cfg: dict) -> str:
    icon, title, action = EVENT_TEXT[event]
    f = chart.fmt_price
    side = "LONG" if p["side"] == "long" else "SHORT"
    action = action.format(entry=f(p["entry"]), r=f"{p['r']:+.2f}R", h=cfg["horizon_h"])
    return (f"{icon} <b>{html.escape(p['name'])} {side}</b> — {title} ({_hhmm(ts)})\n{html.escape(action)}\n"
            f"<i>giriş {f(p['entry'])} · SL {f(p['sl'])} · TP1 {f(p['tp1'])} · TP2 {f(p['tp2'])}</i>")


async def check(bot: Bot, chat_id: int, cfg: dict) -> list[dict]:
    """Yeni olayları bildirir, güncel durumları döner."""
    now = int(time.time())
    pos = await positions(cfg, now)
    state = _load_state()
    msgs = []
    for p in sorted(pos, key=lambda x: x["ts"]):
        seen = set(state.get(_key(p), []))
        for event, ts in p["events"]:
            if event not in seen:
                msgs.append(_event_msg(p, event, ts, cfg))
                seen.add(event)
        state[_key(p)] = sorted(seen)
    cutoff = now - 14 * 86400
    state = {k: v for k, v in state.items() if int(k.split("|")[0]) >= cutoff}
    _save_state(state)
    for m in msgs:
        await bot.send_message(chat_id, m, parse_mode=ParseMode.HTML)
    return pos


STATE_TEXT = {"PENDING": "limit bekliyor", "OPEN": "açık", "OPEN_BE": "açık · TP1 ✓ stop girişte",
              "TP2": "kapandı · TP2", "SL": "kapandı · stop", "BE": "kapandı · başabaş",
              "TIME": "kapandı · süre", "EXPIRED": "iptal · dolmadı"}


def position_lines(pos: list[dict], now: int) -> list[str]:
    lines = []
    for p in pos:
        side = "LONG " if p["side"] == "long" else "SHORT"
        extra = ""
        if p["state"] == "PENDING":
            extra = f"{chart.fmt_price(p['entry'])}, {max(0, (p['expiry'] - now) // 3600)}s kaldı"
        elif p["state"] in ("OPEN", "OPEN_BE"):
            extra = f"{p['r']:+.2f}R, {max(0, (p['end'] - now) // 3600)}s kaldı"
        elif p["state"] != "EXPIRED":
            extra = f"{p['r']:+.2f}R"
        lines.append(f"{p['name'][:8]:<8} {side} {STATE_TEXT[p['state']]}" + (f" ({extra})" if extra else ""))
    return lines
