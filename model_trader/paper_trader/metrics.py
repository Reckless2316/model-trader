"""Performance metrics calculated from the trade journal."""

from __future__ import annotations

import json
from pathlib import Path


def calculate_metrics(journal_path: str | Path) -> dict:
    """Compute W/L, win rate, avg R, profit factor, total PnL, max drawdown.

    Returns a dict with all metrics. Values default to 0 when no closed trades
    exist, except profit_factor which returns inf when there are only wins.
    """
    path = Path(journal_path)
    if not path.exists():
        return _empty_metrics()

    with open(path, encoding="utf-8") as f:
        trades = json.load(f)

    closed = [t for t in trades if t.get("status") == "CLOSED"]
    if not closed:
        return _empty_metrics()

    wins = [t for t in closed if t.get("outcome") == "WIN"]
    losses = [t for t in closed if t.get("outcome") == "LOSS"]

    total_wins_pnl = sum(t["pnl"] for t in wins)
    total_losses_pnl = abs(sum(t["pnl"] for t in losses))

    # Max drawdown from equity curve
    peak = 0.0
    running = 0.0
    max_dd = 0.0
    for t in closed:
        running += t.get("pnl", 0) or 0
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "avg_rr": round(sum(t.get("r_multiple", 0) or 0 for t in closed) / len(closed), 2),
        "profit_factor": (
            round(total_wins_pnl / total_losses_pnl, 2)
            if total_losses_pnl > 0
            else float("inf")
        ),
        "total_pnl": round(sum(t["pnl"] for t in closed), 2),
        "max_drawdown": round(max_dd, 2),
    }


def _empty_metrics() -> dict:
    return {
        "total_trades": 0, "wins": 0, "losses": 0,
        "win_rate": 0, "avg_rr": 0, "profit_factor": 0,
        "total_pnl": 0, "max_drawdown": 0,
    }
