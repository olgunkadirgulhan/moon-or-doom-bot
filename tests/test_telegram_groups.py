"""Telegram düzeni: kripto, BIST ve altın/gümüş panoları ve grafikleri birbirine karışmadan ayrı gider."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import market_map  # noqa: E402


def asset(symbol, market, side="long", score=70, name=None):
    return {"symbol": symbol, "market": market, "side": side, "score": score, "raw_score": score, "name": name, "frames": {"1d": None},
            "price": 1.0, "entry": 1.0, "sl": 0.9, "tp1": 1.2, "tp2": 1.3, "rr": 2.5}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.sent.append(("photo", [photo], caption))

    async def send_media_group(self, chat_id, media, **kw):
        self.sent.append(("album", [getattr(m.media, "input_file_content", m.media) for m in media], media[0].caption))


class TestGroups(unittest.TestCase):
    def test_group_of(self):
        self.assertEqual(market_map.group_of(asset("BTC", "crypto")), "crypto")
        self.assertEqual(market_map.group_of(asset("THYAO", "bist")), "bist")
        self.assertEqual(market_map.group_of(asset("BIST100", "tradfi")), "bist")
        self.assertEqual(market_map.group_of(asset("ALTIN_GR_TL", "tradfi")), "metal")

    def test_board_and_charts_separated(self):
        crypto = {s: asset(s, "crypto") for s in ("BTC", "ETH", "SOL")}
        fixed = [asset("ALTIN_GR_TL", "tradfi"), asset("BIST100", "tradfi")]
        ranked = {"crypto_long": [asset("PEPE", "crypto")], "crypto_short": [asset("XRP", "crypto", "short", 20)],
                  "bist_long": [asset("THYAO", "bist")], "bist_short": [asset("SASA", "bist", "short", 20)]}
        cfg = {"key_assets": ["BTC", "ETH", "SOL", "ALTIN_GR_TL", "BIST100"]}
        boards = []

        def fake_board(sections, title):
            boards.append((title, {r["name"] for _, rows in sections for r in rows}))
            return b"board"

        bot = FakeBot()
        with mock.patch.object(market_map.chart, "board", fake_board), \
                mock.patch.object(market_map.chart, "coin_chart", lambda r: r["symbol"].encode()), \
                mock.patch.object(market_map.signal, "with_side", lambda a, side, cfg: {**a, "side": side}), \
                mock.patch.object(market_map.strategy, "rejection", lambda r, cfg, regs: "BEKLE"), \
                mock.patch.object(market_map.strategy, "regime", lambda frame: "neutral"):
            asyncio.run(market_map.send_board(bot, 1, cfg, {"crypto": "up", "bist": "down"}, crypto, fixed, ranked,
                                              [], [], with_charts=True))

        self.assertEqual([t for t, _ in boards], ["Moon or Doom — ₿ Kripto Panosu", "Moon or Doom — 🏛 BIST Panosu",
                                                  "Moon or Doom — 🥇 Altın · Gümüş Panosu"])
        self.assertEqual(boards[0][1], {"BTC", "ETH", "SOL", "PEPE", "XRP"})
        self.assertEqual(boards[1][1], {"BIST100", "THYAO", "SASA"})
        self.assertEqual(boards[2][1], {"ALTIN_GR_TL"})
        # sıra: kripto panosu, kripto albümü, BIST panosu, BIST grafiği, altın panosu, altın grafiği
        kinds = [(k, files) for k, files, _ in bot.sent]
        self.assertEqual(kinds, [("photo", [b"board"]), ("album", [b"BTC", b"ETH", b"SOL"]),
                                 ("photo", [b"board"]), ("photo", [b"BIST100"]),
                                 ("photo", [b"board"]), ("photo", [b"ALTIN_GR_TL"])])


if __name__ == "__main__":
    unittest.main()
