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

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Callable, Any

from ..gates import SetupStatus, SetupResult


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
        scanner_factory: Callable returning a scanner with an `evaluate_at(symbol, data, step_ts)` method.
            The scanner should accept pre-fetched historical data and a "current" timestamp.
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

            # Evaluate the scanner at this point in time
            try:
                result: SetupResult = scanner.evaluate_at(symbol, hist, corr_hist, ts)
            except AttributeError:
                raise RuntimeError(
                    "Your scanner must implement evaluate_at(symbol, hist, corr_hist, ts) "
                    "to support backtesting. See docs/backtest.md."
                )

            if result.status == SetupStatus.TAKE and result.entry and result.stop:
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
