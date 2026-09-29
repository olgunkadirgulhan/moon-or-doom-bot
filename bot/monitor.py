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


def usd(v: float, sign: bool = True) -> str:
    """1.234,50 $ biçimi; sign=True ise + / − işaretli."""
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (("+" if v >= 0 else "−") if sign else "") + s + " $"


def money(p: dict, cfg: dict) -> float:
    """R sonucunu dolara çevirir: 1R = işlem başı risk (sermaye × risk %)."""
    return p["r"] * cfg["capital_usd"] * cfg["risk_pct"] / 100


def side_words(p: dict) -> tuple[str, str]:
    """(işlem adı, açılış fiili) — long: yükselişten kazanç, short: düşüşten kazanç."""
    return ("ALIŞ (long)", "alınacak") if p["side"] == "long" else ("SATIŞ (short)", "satılacak")


def _event_msg(p: dict, event: str, ts: int, cfg: dict) -> str:
    f = chart.fmt_price_tr
    name, _ = side_words(p)
    risk = cfg["capital_usd"] * cfg["risk_pct"] / 100
    head = f"<b>{html.escape(p['name'])} — {name}</b> · {_hhmm(ts)}"
    body = {
        "FILLED": ("🟡", f"Emrin gerçekleşti: {f(p['entry'])} fiyatından işleme girildi.\n"
                         f"👉 Zarar-kes (stop) emrin {f(p['sl'])} ve hedef emirlerin girili mi, kontrol et."),
        "EXPIRED": ("⌛", f"Fiyat 12 saat içinde {f(p['entry'])} seviyesine gelmedi, işleme girilmedi.\n"
                          "👉 Borsadaki bekleyen emrini İPTAL ET."),
        "TP1": ("🎯", f"1. hedef ({f(p['tp1'])}) geldi: pozisyonun yarısı kârla kapandı.\n"
                      f"👉 Zarar-kes emrini giriş fiyatına ({f(p['entry'])}) taşı. Artık bu işlemde zarar etmezsin.\n"
                      f"Şu anki durum: {usd(money(p, cfg))}"),
        "TP2": ("✅", f"2. hedef ({f(p['tp2'])}) geldi, işlem tamamen kârla kapandı.\nSonuç: {usd(money(p, cfg))}"),
        "SL": ("🛑", f"Fiyat zarar-kese ({f(p['sl'])}) geldi, işlem kapandı.\nSonuç: {usd(money(p, cfg))} "
                     f"(önceden planlanan en fazla {usd(risk, False)} kayıp — kural işledi, sorun yok)."),
        "BE": ("⚪", f"Fiyat giriş seviyesine ({f(p['entry'])}) geri döndü, kalan yarı zararsız kapandı.\n"
                     f"Sonuç: {usd(money(p, cfg))} (1. hedefte alınan kâr cepte)."),
        "TIME": ("⏱", f"{cfg['horizon_h'] // 24} günlük süre doldu, hedef gelmedi.\n"
                      f"👉 Pozisyonu şimdiki fiyattan KAPAT. Yaklaşık sonuç: {usd(money(p, cfg))}"),
    }[event]
    return f"{body[0]} {head}\n{html.escape(body[1])}"


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


def position_lines(pos: list[dict], now: int, cfg: dict) -> list[str]:
    """Her işlem için sade, 2 satırlık durum (HTML)."""
    f = chart.fmt_price_tr
    esc = html.escape
    risk = usd(cfg["capital_usd"] * cfg["risk_pct"] / 100, False)
    out = []
    for p in pos:
        name, verb = side_words(p)
        m = usd(money(p, cfg))
        levels = f"giriş {f(p['entry'])} · zarar-kes {f(p['sl'])} · hedef-1 {f(p['tp1'])} · hedef-2 {f(p['tp2'])}"
        state = p["state"]
        if state == "PENDING":
            hrs = max(0, (p["expiry"] - now) // 3600)
            direction = "düşerse" if p["side"] == "long" else "çıkarsa"
            line = f"⏳ Emir bekliyor: fiyat {f(p['entry'])} seviyesine {direction} {verb} ({hrs} saat içinde, yoksa iptal)"
        elif state == "OPEN":
            hrs = max(0, (p["end"] - now) // 3600)
            word = "kârda" if p["r"] >= 0 else "zararda"
            line = f"🟢 İşlemdesin · şu an {m} {word} (en fazla kayıp {risk}) · kapanışa {hrs} saat"
        elif state == "OPEN_BE":
            hrs = max(0, (p["end"] - now) // 3600)
            line = f"🟢 İşlemdesin · 1. hedef geldi, yarısı kârla kapandı, stop girişte (zarar yok) · şu an {m} · {hrs} saat"
        else:
            line = {"TP2": f"✅ Kapandı: 2. hedef geldi · {m}", "SL": f"🛑 Kapandı: zarar-kes çalıştı · {m}",
                    "BE": f"⚪ Kapandı: kalan yarı girişten döndü · {m}", "TIME": f"⏱ Kapandı: süre doldu · {m}",
                    "EXPIRED": "⌛ İşleme girilmedi: fiyat emre gelmedi"}[state]
        out.append(f"<b>{esc(p['name'])} — {name}</b>\n{esc(line)}\n<i>{esc(levels)}</i>")
    return out
