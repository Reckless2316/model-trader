"""Paper trader sizing/exits, journal filters, and metrics."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from model_trader.data import StaticAdapter
from model_trader.gates import SetupResult, SetupStatus
from model_trader.paper_trader import PaperTrader, calculate_metrics, is_duplicate_setup, is_invalidated_level

from .helpers import candle


def take(entry=100.0, stop=99.0, target=102.0, direction="long", symbol="BTC"):
    return SetupResult(symbol=symbol, status=SetupStatus.TAKE, direction=direction, entry=entry, stop=stop, target=target, extras={"why": "test"})


class PaperTraderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Path(self.tmp.name) / "trades.json"
        self.last = candle(0, 100, 100.5, 99.5, 100)
        self.data = StaticAdapter({"BTC": {"1m": [self.last]}})

    def tearDown(self):
        self.tmp.cleanup()

    def trader(self, **kw):
        return PaperTrader(self.journal, starting_balance=10_000, data_adapter=self.data, **kw)

    def test_risk_based_size(self):
        trade = self.trader(per_trade_pct=1.0).execute(take())
        self.assertAlmostEqual(trade.risk_amount, 100.0)
        self.assertAlmostEqual(trade.position_size, 100.0)
        self.assertEqual(trade.rr_ratio, 2.0)
        self.assertEqual(trade.extras, {"why": "test"})

    def test_leverage_cap_shrinks_size_and_risk(self):
        trade = self.trader(per_trade_pct=1.0, max_leverage=2).execute(take(entry=100, stop=99.9, target=100.2))
        self.assertAlmostEqual(trade.position_size * 100, 20_000)
        self.assertLess(trade.risk_amount, 100.0)

    def test_rejects_non_actionable(self):
        t = self.trader()
        self.assertIsNone(t.execute(SetupResult(symbol="BTC", status=SetupStatus.WAIT)))
        self.assertIsNone(t.execute(take(stop=100.0)))
        self.assertIsNone(t.execute(SetupResult(symbol="BTC", status=SetupStatus.TAKE, direction="long", entry=1, stop=0.5)))
        self.assertEqual(t.get_all_trades(), [])

    def test_exit_sl_has_priority_and_balance_compounds(self):
        t = self.trader()
        t.execute(take())
        self.data.candles["BTC"]["1m"] = [candle(60_000, 100, 102.5, 98.5, 100)]
        closed = t.check_exits()
        self.assertEqual([(c["notes"], c["outcome"], c["r_multiple"]) for c in closed], [("SL_HIT", "LOSS", -1.0)])
        self.assertAlmostEqual(t.get_balance(), 9_900.0)

    def test_short_target(self):
        t = self.trader()
        t.execute(take(entry=100, stop=101, target=98, direction="short"))
        self.data.candles["BTC"]["1m"] = [candle(60_000, 99, 99.5, 97.9, 98)]
        closed = t.check_exits()
        self.assertEqual((closed[0]["notes"], closed[0]["r_multiple"]), ("TP_HIT", 2.0))
        self.assertEqual(t.get_open_trades(), [])


class FilterAndMetricTests(unittest.TestCase):
    def write(self, trades):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(trades, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return tmp.name

    def closed(self, minutes_ago, notes="TP_HIT", pnl=100.0, outcome="WIN", r=1.0, stop=99.0, direction="long"):
        exit_time = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
        return {"symbol": "BTC", "direction": direction, "status": "CLOSED", "exit_time": exit_time, "entry_price": 100.0, "stop_loss": stop, "take_profit": 102.0, "notes": notes, "pnl": pnl, "outcome": outcome, "r_multiple": r}

    def test_duplicate_setup_window(self):
        path = self.write([self.closed(5)])
        self.assertTrue(is_duplicate_setup(path, "BTC", 100.0, 99.0, 102.0, lookback_minutes=15))
        self.assertFalse(is_duplicate_setup(path, "BTC", 100.0, 99.0, 102.0, lookback_minutes=3))
        self.assertFalse(is_duplicate_setup(path, "ETH", 100.0, 99.0, 102.0))
        self.assertFalse(is_duplicate_setup(path, "BTC", 101.0, 99.0, 102.0))

    def test_invalidated_level_until_price_moves_away(self):
        path = self.write([self.closed(30, notes="SL_HIT", pnl=-100, outcome="LOSS", r=-1)])
        self.assertTrue(is_invalidated_level(path, "BTC", "long", 99.0, current_price=99.2))
        self.assertFalse(is_invalidated_level(path, "BTC", "long", 99.0, current_price=100.0))
        self.assertFalse(is_invalidated_level(path, "BTC", "short", 99.0, current_price=99.2))
        self.assertFalse(is_invalidated_level(path, "BTC", "long", 99.0, current_price=99.2, max_age_hours=0))

    def test_missing_journal_is_empty(self):
        self.assertFalse(is_duplicate_setup("/nonexistent/trades.json", "BTC", 1, 1, 1))
        self.assertEqual(calculate_metrics("/nonexistent/trades.json")["total_trades"], 0)

    def test_metrics(self):
        path = self.write([
            self.closed(1, pnl=200, r=2.0),
            self.closed(1, notes="SL_HIT", pnl=-100, outcome="LOSS", r=-1.0),
            self.closed(1, notes="SL_HIT", pnl=-100, outcome="LOSS", r=-1.0),
            self.closed(1, pnl=300, r=3.0),
        ])
        m = calculate_metrics(path)
        self.assertEqual((m["wins"], m["losses"], m["win_rate"]), (2, 2, 50.0))
        self.assertEqual((m["profit_factor"], m["total_pnl"], m["max_drawdown"], m["avg_rr"]), (2.5, 300.0, 200.0, 0.75))


if __name__ == "__main__":
    unittest.main()
