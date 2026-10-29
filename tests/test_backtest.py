"""Backtest runner: no lookahead, trade simulation, cooldown."""

from __future__ import annotations

import unittest

from model_trader.backtest import run_backtest
from model_trader.data import StaticAdapter
from model_trader.gates import ScannerBase, SetupResult, SetupStatus

from .helpers import TF_MS, candle, flat_series

DAY_MS = 86_400_000


class RecordingScanner(ScannerBase):
    """Never trades; records the newest candle close-time it was shown per TF."""

    instances: list["RecordingScanner"] = []

    def __init__(self, config, data):
        super().__init__(config, data)
        self.seen: list[tuple[int, dict[str, int]]] = []
        RecordingScanner.instances.append(self)

    def evaluate(self, symbol):  # pragma: no cover - live path unused
        return SetupResult(symbol=symbol)

    def evaluate_at(self, symbol, hist, corr_hist, ts):
        newest = {tf: c[-1]["timestamp"] + TF_MS[tf] for tf, c in hist.items() if c}
        newest.update({f"corr:{tf}": c[-1]["timestamp"] + TF_MS[tf] for tf, c in corr_hist.items() if c})
        self.seen.append((ts, newest))
        return SetupResult(symbol=symbol)


class PeekingScanner(ScannerBase):
    """Goes long iff the *next* 5m candle closes higher: only profitable with lookahead."""

    def evaluate(self, symbol):  # pragma: no cover
        return SetupResult(symbol=symbol)

    def evaluate_at(self, symbol, hist, corr_hist, ts):
        bars = hist["5m"]
        idx = next((i for i, c in enumerate(bars) if c["timestamp"] == ts), None)
        result = SetupResult(symbol=symbol)
        if idx is None or idx + 1 >= len(bars):
            return result
        nxt = bars[idx + 1]
        if nxt["close"] > bars[idx]["close"]:
            entry = bars[idx]["close"]
            result.status = SetupStatus.TAKE
            result.direction = "long"
            result.entry, result.stop, result.target = entry, entry - 1.0, entry + 0.5
        return result


def zigzag_5m(count: int) -> list[dict]:
    out = []
    price = 100.0
    for i in range(count):
        move = 0.6 if (i * 7919) % 3 else -0.6  # deterministic, irregular up/down
        o, c = price, price + move
        out.append(candle(i * TF_MS["5m"], o, max(o, c) + 0.05, min(o, c) - 0.05, c))
        price = c
    return out


class NoLookaheadTests(unittest.TestCase):
    def test_scanner_only_sees_closed_candles(self):
        RecordingScanner.instances.clear()
        bars = 400
        data = StaticAdapter({
            "BTC": {"5m": flat_series("5m", bars), "1h": flat_series("1h", bars // 12 + 2), "4h": flat_series("4h", bars // 48 + 2)},
            "ETH": {"5m": flat_series("5m", bars), "1h": flat_series("1h", bars // 12 + 2), "4h": flat_series("4h", bars // 48 + 2)},
        })
        config = {"symbols": ["BTC"], "timeframes": ["5m", "1h", "4h"], "correlations": {"BTC": "ETH"}}
        run_backtest(RecordingScanner, config, data, days=2, step_timeframe="5m")
        seen = RecordingScanner.instances[-1].seen
        self.assertGreater(len(seen), 100)
        for ts, newest in seen:
            decision_time = ts + TF_MS["5m"]
            for tf, closed_at in newest.items():
                self.assertLessEqual(closed_at, decision_time, f"{tf} candle closing at {closed_at} leaked into decision at {decision_time}")
            # every timeframe is still present: truncation must not drop all history
            self.assertEqual(set(newest), {"5m", "1h", "4h", "corr:5m", "corr:1h", "corr:4h"})

    def test_peeking_strategy_cannot_profit(self):
        data = StaticAdapter({"BTC": {"5m": zigzag_5m(600)}})
        results = run_backtest(PeekingScanner, {"symbols": ["BTC"], "timeframes": ["5m"]}, data, days=3, step_timeframe="5m", cooldown_bars=0)
        self.assertEqual(results["total_trades"], 0)


class FixedSetupScanner(ScannerBase):
    """TAKEs a long at the step bar's close with fixed distances."""

    def __init__(self, config, data):
        super().__init__(config, data)
        self.stop_dist = config["stop_dist"]
        self.target_dist = config["target_dist"]

    def evaluate(self, symbol):  # pragma: no cover
        return SetupResult(symbol=symbol)

    def evaluate_at(self, symbol, hist, corr_hist, ts):
        entry = hist["5m"][-1]["close"]
        return SetupResult(symbol=symbol, status=SetupStatus.TAKE, direction="long", entry=entry, stop=entry - self.stop_dist, target=entry + self.target_dist)


class SimulationTests(unittest.TestCase):
    def series(self, path_after_entry: list[tuple[float, float]]) -> list[dict]:
        bars = flat_series("5m", 200)
        ts = 200 * TF_MS["5m"]
        for hi, lo in path_after_entry:
            bars.append(candle(ts, 100, hi, lo, 100))
            ts += TF_MS["5m"]
        return bars

    def run_once(self, path, **cfg):
        config = {"symbols": ["BTC"], "timeframes": ["5m"], "stop_dist": 1.0, "target_dist": 2.0, **cfg}
        return run_backtest(FixedSetupScanner, config, StaticAdapter({"BTC": {"5m": self.series(path)}}), step_timeframe="5m", cooldown_bars=10_000)

    def test_target_hit_records_r_multiple(self):
        r = self.run_once([(100.4, 99.6), (102.5, 99.5)])
        self.assertEqual((r["wins"], r["losses"]), (1, 0))
        self.assertEqual(r["trades"][0].pnl_r, 2.0)

    def test_stop_wins_tie_in_same_bar(self):
        r = self.run_once([(100.4, 99.6), (102.5, 98.5)])
        self.assertEqual((r["wins"], r["losses"]), (0, 1))
        self.assertEqual(r["total_r"], -1.0)

    def test_unfinished_trade_is_open(self):
        r = self.run_once([(100.2, 99.8)] * 3)
        self.assertEqual(r["trades"][0].outcome, "OPEN")
        self.assertEqual(r["closed"], 0)


if __name__ == "__main__":
    unittest.main()


class ContractTests(unittest.TestCase):
    data = StaticAdapter({"BTC": {"5m": flat_series("5m", 250)}})
    config = {"symbols": ["BTC"], "timeframes": ["5m"]}

    def test_scanner_without_evaluate_at_is_explained(self):
        class LiveOnly(ScannerBase):
            def evaluate(self, symbol):
                return SetupResult(symbol=symbol)

        with self.assertRaisesRegex(RuntimeError, "evaluate_at"):
            run_backtest(LiveOnly, self.config, self.data)

    def test_bug_inside_evaluate_at_is_not_masked(self):
        class Buggy(ScannerBase):
            def evaluate(self, symbol):  # pragma: no cover
                return SetupResult(symbol=symbol)

            def evaluate_at(self, symbol, hist, corr_hist, ts):
                return None.status  # genuine AttributeError in user gate code

        with self.assertRaises(AttributeError):
            run_backtest(Buggy, self.config, self.data)


class UnknownTimeframeTests(unittest.TestCase):
    def test_unlisted_timeframe_is_inferred_once_and_truncated(self):
        import time

        step = 120_000  # "2m" is not in the runner's table, so its length is inferred
        bars = [candle(i * step, 100, 100.5, 99.5, 100) for i in range(20_000)]
        seen: list[tuple[int, int]] = []

        class Probe(ScannerBase):
            def evaluate(self, symbol):  # pragma: no cover
                return SetupResult(symbol=symbol)

            def evaluate_at(self, symbol, hist, corr_hist, ts):
                seen.append((ts, hist["2m"][-1]["timestamp"]))
                return SetupResult(symbol=symbol)

        start = time.perf_counter()
        run_backtest(Probe, {"symbols": ["BTC"], "timeframes": ["2m"]}, StaticAdapter({"BTC": {"2m": bars}}), step_timeframe="2m", evaluate_every_n_bars=1000)
        self.assertLess(time.perf_counter() - start, 5.0)  # quadratic inference took minutes here
        self.assertTrue(seen)
        for ts, newest_open in seen:
            self.assertEqual(newest_open, ts)  # the step bar itself has closed; nothing later is visible
