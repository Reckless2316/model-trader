"""Pure detector functions over hand-built candles."""

from __future__ import annotations

import unittest

from model_trader.detectors import (
    detect_cisd,
    detect_cisd_breaker,
    detect_displacement,
    detect_failure_swings,
    detect_fvg,
    detect_smt,
    detect_swings,
    update_fvg_states,
)

from .helpers import candle


def bars(rows):
    return [candle(i * 60_000, *row) for i, row in enumerate(rows)]


class SwingTests(unittest.TestCase):
    def test_swing_high_and_low(self):
        highs = [10, 11, 12, 15, 12, 11, 10, 9, 8, 7, 8, 9, 10]
        lows = [h - 1 for h in highs]
        candles = [candle(i, h - 0.5, h, l, h - 0.5) for i, (h, l) in enumerate(zip(highs, lows))]
        swings = detect_swings(candles, lookback=3)
        self.assertIn({"type": "high", "price": 15, "index": 3, "strength": 3}, swings)
        self.assertIn({"type": "low", "price": 6, "index": 9, "strength": 3}, swings)

    def test_failure_swings_cluster_equal_levels(self):
        swings = [{"type": "high", "price": 100.0, "index": 1}, {"type": "high", "price": 100.05, "index": 9}, {"type": "low", "price": 90.0, "index": 5}]
        clusters = detect_failure_swings(swings, tolerance_pct=0.1)
        self.assertEqual(len(clusters), 1)
        self.assertEqual((clusters[0]["type"], clusters[0]["count"]), ("high", 2))
        self.assertAlmostEqual(clusters[0]["level"], 100.025)


class FvgTests(unittest.TestCase):
    def test_bullish_gap_and_fill_states(self):
        candles = bars([(10, 10.5, 9.5, 10.4), (10.4, 12, 10.4, 11.9), (11.9, 12.5, 11, 12.4), (12.4, 12.6, 10.8, 12.5)])
        fvgs = detect_fvg(candles)
        self.assertEqual(len(fvgs), 1)
        gap = fvgs[0]
        self.assertEqual((gap["type"], gap["low"], gap["high"]), ("bullish", 10.5, 11))
        update_fvg_states(fvgs, candles)
        self.assertTrue(gap["filled"])
        self.assertTrue(gap["respected"])
        self.assertFalse(gap["inversed"])

    def test_bearish_gap_inversion(self):
        candles = bars([(20, 20.5, 19.5, 19.6), (19.6, 19.6, 18, 18.1), (18.1, 19, 17.5, 17.6), (17.6, 21, 17.6, 20.8)])
        fvgs = update_fvg_states(detect_fvg(candles), candles)
        self.assertEqual(fvgs[0]["type"], "bearish")
        self.assertTrue(fvgs[0]["inversed"])


class StructureTests(unittest.TestCase):
    def test_cisd_and_breaker(self):
        candles = bars([(10, 10.2, 9.8, 10.1), (10.1, 10.3, 9.9, 9.95), (9.95, 10.1, 9.0, 9.1), (9.1, 9.5, 9.0, 9.4), (9.4, 11.0, 9.3, 10.9)])
        swings = [{"type": "high", "price": 10.3, "index": 1}]
        signals = detect_cisd(candles, swings)
        self.assertEqual(signals, [{"type": "bullish", "broken_level": 10.3, "swing_index": 1}])
        breaker = detect_cisd_breaker(candles, signals[0])
        self.assertIsNone(breaker)  # index 0 is outside the scan window (range stops before 0)
        swings = [{"type": "high", "price": 10.5, "index": 3}]
        breaker = detect_cisd_breaker(candles, detect_cisd(candles, swings)[0])
        self.assertEqual(breaker["type"], "bullish_breaker")
        self.assertEqual(breaker["index"], 2)
        self.assertIsNone(detect_cisd_breaker(candles, None))

    def test_smt_divergence(self):
        a = [{"type": "low", "price": 10, "index": 1}, {"type": "low", "price": 9, "index": 5}]
        b = [{"type": "low", "price": 20, "index": 1}, {"type": "low", "price": 21, "index": 6}]
        self.assertEqual(detect_smt(a, b), [{"type": "bullish", "strength": "strong"}])
        self.assertEqual(detect_smt(a, a), [])

    def test_displacement(self):
        rows = [(10, 10.2, 9.9, 10.1)] * 15 + [(10, 13, 9.9, 12.9)]
        found = detect_displacement(bars(rows), lookback=5, threshold_multiplier=2.0)
        self.assertEqual([(d["index"], d["direction"]) for d in found], [(15, "bullish")])


if __name__ == "__main__":
    unittest.main()
