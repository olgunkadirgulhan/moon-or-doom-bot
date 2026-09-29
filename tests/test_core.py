"""Strateji mantığının otomatik testleri: `python -m unittest discover tests`"""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import levels, signal, strategy, tracker  # noqa: E402
from core.indicators import add_indicators  # noqa: E402

T = 1_000_000
FEE = 0.1 / 100 * 100 / 5  # giriş 100, risk 5 → komisyon 0.02R


def candle(i, high, low, close):
    return [(T + i * 900) * 1000, close, high, low, close, 0]


LONG = {"ts": T, "side": "long", "entry": 100.0, "sl": 95.0, "tp1": 110.0, "tp2": 120.0}  # TP1=2R, TP2=4R


class SimulateTest(unittest.TestCase):
    def r(self, candles, p=LONG):
        return tracker._simulate(p, candles)

    def test_stop(self):
        self.assertAlmostEqual(self.r([candle(0, 101, 94, 96)])["r"], -1 - FEE)

    def test_tp1_then_breakeven(self):
        out = self.r([candle(0, 111, 99, 108), candle(1, 105, 99.5, 100)])
        self.assertAlmostEqual(out["r"], 0.5 * 2 - FEE)
        self.assertEqual(out["outcome"], "TP")

    def test_tp1_then_tp2(self):
        self.assertAlmostEqual(self.r([candle(0, 111, 99, 108), candle(1, 121, 105, 119)])["r"], 0.5 * 2 + 0.5 * 4 - FEE)

    def test_same_candle_is_stop(self):
        self.assertEqual(self.r([candle(0, 111, 94, 100)])["outcome"], "SL")

    def test_time_stop(self):
        out = self.r([candle(0, 104, 99, 104)])
        self.assertAlmostEqual(out["r"], 4 / 5 - FEE)
        self.assertEqual(out["outcome"], "OPEN")

    def test_ignores_candles_after_horizon(self):
        late = candle(24 * 4 + 1, 200, 99, 150)  # 24 saat sonrası
        self.assertEqual(self.r([candle(0, 101, 99, 100), late])["outcome"], "OPEN")

    def test_short_mirror(self):
        s = {**LONG, "side": "short", "sl": 105.0, "tp1": 90.0, "tp2": 80.0}
        self.assertAlmostEqual(self.r([candle(0, 101, 89, 92), candle(1, 101, 88, 100)], s)["r"], 1 - FEE)


class LimitFillTest(unittest.TestCase):
    P = {**LONG, "entry": 98.0, "sl": 93.0, "tp1": 108.0, "tp2": 118.0, "price": 100.0, "mode": "limit"}

    def test_fills_when_price_touches(self):
        out = tracker.simulate_full(self.P, [candle(0, 100.5, 99, 99.5), candle(1, 99, 97.5, 98), candle(2, 109, 98, 108)])
        self.assertEqual(out["outcome"], "TP")
        self.assertIsNotNone(out["r"])

    def test_no_fill_is_not_a_trade(self):
        out = tracker.simulate_full(self.P, [candle(i, 101, 99, 100) for i in range(60)])
        self.assertEqual(out["outcome"], "NOFILL")
        self.assertIsNone(out["r"])
        self.assertEqual(tracker._stats([{**self.P, **out}])["total"], 0)

    def test_expires_after_12h(self):
        late = candle(12 * 4 + 1, 99, 97, 98)  # 12 saat sonra dokunuyor → geçersiz
        self.assertEqual(tracker.simulate_full(self.P, [candle(0, 101, 99, 100), late])["outcome"], "NOFILL")

    def test_market_mode_enters_immediately(self):
        p = {**self.P, "mode": "market", "entry": 100.0, "sl": 95.0}
        self.assertEqual(tracker.find_fill(p, [], "market"), p["ts"])


class AccountTest(unittest.TestCase):
    def sig(self, ts, r, symbol="A", side="long", dur=3600):
        return {"ts": ts, "exit_ts": ts + dur, "r": r, "symbol": symbol, "side": side, "market": "crypto"}

    def test_compounding_and_drawdown(self):
        a = tracker.account([self.sig(0, -1), self.sig(10_000, 2)], 1000, 1)
        self.assertAlmostEqual(a["equity"], 1000 * 0.99 * 1.02)
        self.assertAlmostEqual(a["max_dd"], 1.0)

    def test_no_duplicate_symbol_while_open(self):
        a = tracker.account([self.sig(0, 1, dur=7200), self.sig(3600, 1)], 1000, 1)
        self.assertEqual(a["trades"], 1)

    def test_same_direction_crypto_limit(self):
        sigs = [self.sig(0, 1, s, dur=7200) for s in "ABC"]
        self.assertEqual(tracker.account(sigs, max_same_dir_crypto=2)["trades"], 2)


class ScoreTest(unittest.TestCase):
    def test_missing_onchain_weight_is_redistributed(self):
        comps = {"trend": 1, "proximity": 1, "rsi": 1, "confluence": 1, "onchain": 0}
        w = {"trend": 25, "proximity": 25, "rsi": 15, "confluence": 15, "onchain": 20}
        self.assertAlmostEqual(signal.raw_score(comps, w, onchain_available=False), 100)
        self.assertAlmostEqual(signal.raw_score(comps, w, onchain_available=True), 90)


class StrategyTest(unittest.TestCase):
    CFG = {"leverage": 10, "cand_min_rr": 2.0, "regime_filter": True, "max_open": 3, "max_same_dir_crypto": 2,
           "capital_usd": 1000, "risk_pct": 1.0}

    def cand(self, **kw):
        return {"symbol": "X", "market": "crypto", "signal": "AL", "side": "long", "score": 70, "rr": 2.5,
                "entry": 100.0, "sl": 97.0, "tp1": 107.5, "tp2": 110.0, **kw}

    def test_rules(self):
        self.assertIsNone(strategy.rejection(self.cand(), self.CFG))
        self.assertEqual(strategy.rejection(self.cand(signal="BEKLE"), self.CFG), "BEKLE")
        self.assertEqual(strategy.rejection(self.cand(rr=1.5), self.CFG), "R:R düşük")
        self.assertEqual(strategy.rejection(self.cand(sl=94.0), self.CFG), "stop likidasyona yakın")  # %6 > %4.5

    def test_regime_blocks_counter_trend(self):
        self.assertIsNotNone(strategy.rejection(self.cand(), self.CFG, {"crypto": "down"}))
        self.assertIsNone(strategy.rejection(self.cand(), self.CFG, {"crypto": "up"}))
        short = self.cand(side="short", signal="SAT", sl=103.0, tp1=92.5, tp2=90.0)
        self.assertIsNotNone(strategy.rejection(short, self.CFG, {"crypto": "up"}))

    def test_sizing(self):
        s = strategy.sizing(self.cand(), self.CFG)
        self.assertAlmostEqual(s["risk_usd"], 10)
        self.assertAlmostEqual(s["position_usd"], 10 / 0.03)
        self.assertAlmostEqual(s["margin_usd"], 10 / 0.03 / 10)


class LevelsTest(unittest.TestCase):
    def test_no_lookahead_in_swings(self):
        """Son n mum swing olamaz: sağında n kapanmış mum yok (canlı ve backtest aynı kural)."""
        rng = np.random.default_rng(1)
        close = 100 + rng.standard_normal(200).cumsum()
        df = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1.0},
                          index=pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC"))
        n = levels.FRACTAL["1h"]
        self.assertTrue(all(i < len(df) - n for _, i in levels.swing_points(df, n)))

    def test_levels_sides(self):
        idx = pd.date_range("2024-01-01", periods=300, freq="h", tz="UTC")
        wave = 100 + 5 * np.sin(np.arange(300) / 8)
        df = add_indicators(pd.DataFrame({"Open": wave, "High": wave + 0.5, "Low": wave - 0.5, "Close": wave,
                                          "Volume": 1.0}, index=idx))
        price = float(df["Close"].iloc[-1])
        lv = levels.compute_levels(df, "1h", price)
        self.assertTrue(all(p < price for p, _, _ in lv["supports"]))
        self.assertTrue(all(p > price for p, _, _ in lv["resistances"]))


if __name__ == "__main__":
    unittest.main()
