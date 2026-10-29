"""Historical backtest runner.

The backtest replays historical candles through your scanner, simulating
trades exactly like the live paper trader would. Useful for validating gate
logic before going live and for tuning parameters.

Usage:
    from model_trader.backtest import run_backtest
    run_backtest(scanner_class, config, days=7)

The scanner class must accept (config, data_adapter) and expose evaluate_at(ts).
See docs/backtest.md for details on implementing evaluate_at for your scanner.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable, Any

from ..gates import SetupStatus, SetupResult


_TF_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
    "3d": 259_200_000, "1w": 604_800_000,
}


def _timeframe_ms(timeframe: str, candles: list) -> int:
    """Known timeframe length, else the smallest spacing seen in the data."""
    if timeframe in _TF_MS:
        return _TF_MS[timeframe]
    gaps = [b["timestamp"] - a["timestamp"] for a, b in zip(candles, candles[1:]) if b["timestamp"] > a["timestamp"]]
    if not gaps:
        raise ValueError(f"cannot infer candle length for timeframe {timeframe!r}")
    return min(gaps)


class _ClosedView:
    """Per-timeframe slices of history containing only candles closed by a time.

    Candle timestamps are *open* times, so a 4h candle that opened before the
    decision time is still forming and must not be visible: its high/low/close
    are in the future. A candle is visible iff open_time + length <= now.
    """

    def __init__(self, hist: dict[str, list]):
        self.hist = hist
        self.close_times: dict[str, list[int]] = {}
        for tf, candles in hist.items():
            length = _timeframe_ms(tf, candles) if candles else 0
            self.close_times[tf] = [c["timestamp"] + length for c in candles]

    def at(self, now_ms: int) -> dict[str, list]:
        return {
            tf: candles[: bisect_right(self.close_times[tf], now_ms)]
            for tf, candles in self.hist.items()
        }


@dataclass
class BacktestTrade:
    timestamp: int
    symbol: str
    direction: str
    entry: float
    stop: float
    target: float
    outcome: str | None = None  # "WIN" | "LOSS" | "OPEN"
    pnl_r: float = 0.0
    exit_reason: str = ""


def run_backtest(
    scanner_factory: Callable[..., Any],
    config: dict,
    data_adapter,
    days: int = 7,
    step_timeframe: str = "5m",
    cooldown_bars: int = 6,
    evaluate_every_n_bars: int = 1,
) -> dict:
    """Replay history and simulate trades.

    Args:
        scanner_factory: Callable returning a scanner with an
            `evaluate_at(symbol, hist, corr_hist, ts)` method. `hist`/`corr_hist`
            contain only candles that had closed by the end of step bar `ts`
            (no lookahead); entries are assumed at that bar's close and exits
            are checked from the next bar.
        config: Config dict with symbols, timeframes, etc.
        data_adapter: DataAdapter for fetching historical candles.
        days: How many days of history to test.
        step_timeframe: Timeframe to walk forward on (default 5m).
        cooldown_bars: Bars to skip after a trade closes (prevents immediate re-entry).
        evaluate_every_n_bars: Only call evaluate every N bars (performance tuning).

    Returns:
        dict with per-symbol breakdown, overall metrics, and trade list.
    """
    scanner = scanner_factory(config, data_adapter)
    if not callable(getattr(scanner, "evaluate_at", None)):
        raise RuntimeError(
            "Your scanner must implement evaluate_at(symbol, hist, corr_hist, ts) "
            "to support backtesting. See docs/backtest.md."
        )
    all_trades: list[BacktestTrade] = []
    per_symbol: dict[str, dict] = {}

    for symbol in config.get("symbols", []):
        # Fetch all timeframes of historical data for this symbol
        hist: dict[str, list] = {}
        for tf in config.get("timeframes", ["1m", "5m", "15m", "1h", "4h"]):
            try:
                hist[tf] = data_adapter.fetch_historical(symbol, tf, days)
            except Exception as e:
                hist[tf] = []
                print(f"  [{symbol} {tf}] fetch failed: {e}")

        # Correlation data
        corr_hist: dict[str, list] = {}
        corr = config.get("correlations", {}).get(symbol)
        if corr:
            for tf in config.get("timeframes", []):
                try:
                    corr_hist[tf] = data_adapter.fetch_historical(corr, tf, days)
                except Exception:
                    corr_hist[tf] = []

        step_candles = hist.get(step_timeframe, [])
        if not step_candles:
            print(f"  [{symbol}] no {step_timeframe} data, skipping")
            continue
        step_ms = _timeframe_ms(step_timeframe, step_candles)
        hist_view = _ClosedView(hist)
        corr_view = _ClosedView(corr_hist)

        trades_for_symbol: list[BacktestTrade] = []
        open_trade: BacktestTrade | None = None
        cooldown_until = 0

        for i in range(200, len(step_candles)):
            ts = step_candles[i]["timestamp"]

            # Check if open trade exited this bar
            if open_trade is not None:
                candle = step_candles[i]
                if open_trade.direction == "long":
                    if candle["low"] <= open_trade.stop:
                        open_trade.outcome = "LOSS"
                        open_trade.pnl_r = -1.0
                        open_trade.exit_reason = "SL"
                        trades_for_symbol.append(open_trade)
                        open_trade = None
                        cooldown_until = i + cooldown_bars
                    elif candle["high"] >= open_trade.target:
                        open_trade.outcome = "WIN"
                        open_trade.pnl_r = round(
                            abs(open_trade.target - open_trade.entry) /
                            abs(open_trade.entry - open_trade.stop), 2
                        )
                        open_trade.exit_reason = "TP"
                        trades_for_symbol.append(open_trade)
                        open_trade = None
                        cooldown_until = i + cooldown_bars
                else:
                    if candle["high"] >= open_trade.stop:
                        open_trade.outcome = "LOSS"
                        open_trade.pnl_r = -1.0
                        open_trade.exit_reason = "SL"
                        trades_for_symbol.append(open_trade)
                        open_trade = None
                        cooldown_until = i + cooldown_bars
                    elif candle["low"] <= open_trade.target:
                        open_trade.outcome = "WIN"
                        open_trade.pnl_r = round(
                            abs(open_trade.entry - open_trade.target) /
                            abs(open_trade.entry - open_trade.stop), 2
                        )
                        open_trade.exit_reason = "TP"
                        trades_for_symbol.append(open_trade)
                        open_trade = None
                        cooldown_until = i + cooldown_bars

                if open_trade is not None:
                    continue  # still in trade

            if i < cooldown_until:
                continue
            if i % evaluate_every_n_bars != 0:
                continue

            # Evaluate at the close of step bar i, seeing only closed candles.
            decision_ms = ts + step_ms
            result: SetupResult = scanner.evaluate_at(
                symbol, hist_view.at(decision_ms), corr_view.at(decision_ms), ts
            )

            if (
                result.status == SetupStatus.TAKE
                and result.direction in ("long", "short")
                and None not in (result.entry, result.stop, result.target)
            ):
                open_trade = BacktestTrade(
                    timestamp=ts,
                    symbol=symbol,
                    direction=result.direction,
                    entry=result.entry,
                    stop=result.stop,
                    target=result.target,
                )

        if open_trade is not None:
            open_trade.outcome = "OPEN"
            trades_for_symbol.append(open_trade)

        all_trades.extend(trades_for_symbol)
        wins = sum(1 for t in trades_for_symbol if t.outcome == "WIN")
        losses = sum(1 for t in trades_for_symbol if t.outcome == "LOSS")
        per_symbol[symbol] = {
            "trades": len(trades_for_symbol),
            "wins": wins,
            "losses": losses,
            "total_r": sum(t.pnl_r for t in trades_for_symbol),
        }
        print(f"  {symbol}: {len(trades_for_symbol)} trades (W={wins} L={losses})")

    closed = [t for t in all_trades if t.outcome in ("WIN", "LOSS")]
    wins = [t for t in closed if t.outcome == "WIN"]
    losses = [t for t in closed if t.outcome == "LOSS"]
    total_r = sum(t.pnl_r for t in closed)
    win_pnl = sum(t.pnl_r for t in wins)
    loss_pnl = abs(sum(t.pnl_r for t in losses))

    return {
        "total_trades": len(all_trades),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "total_r": round(total_r, 2),
        "avg_r": round(total_r / len(closed), 2) if closed else 0,
        "profit_factor": round(win_pnl / loss_pnl, 2) if loss_pnl > 0 else float("inf"),
        "per_symbol": per_symbol,
        "trades": all_trades,
    }
