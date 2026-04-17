"""Paper trading engine.

Opens trades from qualifying SetupResults, tracks exits against live price,
writes everything to a JSON journal. Position sizing uses fixed % risk with
an optional leverage cap.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..gates import SetupResult, SetupStatus


@dataclass
class Trade:
    id: str
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    risk_amount: float
    rr_ratio: float
    status: str = "OPEN"
    entry_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    exit_time: str | None = None
    exit_price: float | None = None
    pnl: float | None = None
    r_multiple: float | None = None
    outcome: str | None = None
    notes: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


class PaperTrader:
    """Simulates a trading account and tracks open/closed trades.

    Args:
        journal_path: Where to persist trades as JSON.
        starting_balance: Initial account size (compounds from realised PnL).
        per_trade_pct: Risk per trade as % of current balance (default 1.0).
        max_leverage: Cap position size so notional <= balance * this (default 25).
        data_adapter: Used to fetch current price for exit checks.
    """

    def __init__(
        self,
        journal_path: str | Path,
        starting_balance: float = 150_000.0,
        per_trade_pct: float = 1.0,
        max_leverage: float = 25.0,
        data_adapter=None,
    ):
        self.journal_path = Path(journal_path)
        self.starting_balance = starting_balance
        self.per_trade_pct = per_trade_pct
        self.max_leverage = max_leverage
        self.data = data_adapter

    # ---------- Persistence ----------

    def _load(self) -> list[dict]:
        if self.journal_path.exists():
            with open(self.journal_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self, trades: list[dict]) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_path, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2, default=str)

    def get_open_trades(self) -> list[dict]:
        return [t for t in self._load() if t.get("status") == "OPEN"]

    def get_all_trades(self) -> list[dict]:
        return self._load()

    def get_balance(self) -> float:
        trades = self._load()
        realised = sum(t.get("pnl", 0) or 0 for t in trades if t.get("status") == "CLOSED")
        return self.starting_balance + realised

    # ---------- Entry ----------

    def execute(self, setup: SetupResult) -> Trade | None:
        """Open a paper trade from a TAKE SetupResult. Returns None if invalid."""
        if setup.status != SetupStatus.TAKE:
            return None
        if setup.entry is None or setup.stop is None or setup.target is None:
            return None
        if not setup.direction:
            return None

        entry = setup.entry
        stop = setup.stop
        target = setup.target
        stop_dist = abs(entry - stop)
        if stop_dist == 0:
            return None

        target_dist = abs(target - entry)
        rr = target_dist / stop_dist

        balance = self.get_balance()
        risk = balance * (self.per_trade_pct / 100)
        size = risk / stop_dist

        # Leverage cap
        notional = size * entry
        max_notional = balance * self.max_leverage
        if notional > max_notional:
            size = max_notional / entry
            risk = size * stop_dist

        trade = Trade(
            id=str(uuid.uuid4())[:8],
            symbol=setup.symbol,
            direction=setup.direction,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            position_size=size,
            risk_amount=risk,
            rr_ratio=round(rr, 2),
            extras=dict(setup.extras),
        )

        trades = self._load()
        trades.append(asdict(trade))
        self._save(trades)
        return trade

    # ---------- Exit ----------

    def check_exits(self) -> list[dict]:
        """Check each open trade against the latest 1m candle. Closes on SL or TP hit.

        Uses candle high/low (not just close) so wicks don't get missed. If both
        SL and TP hit in the same candle, SL takes priority (conservative).
        """
        if not self.data:
            return []

        trades = self._load()
        closed: list[dict] = []

        for t in trades:
            if t.get("status") != "OPEN":
                continue

            try:
                candles = self.data.fetch_candles(t["symbol"], "1m", limit=1)
                if not candles:
                    continue
            except Exception:
                continue

            candle = candles[-1]
            sl = t["stop_loss"]
            tp = t["take_profit"]

            hit_sl = False
            hit_tp = False

            if t["direction"] == "long":
                if candle["low"] <= sl:
                    hit_sl = True
                elif candle["high"] >= tp:
                    hit_tp = True
            else:
                if candle["high"] >= sl:
                    hit_sl = True
                elif candle["low"] <= tp:
                    hit_tp = True

            if hit_sl:
                self._close_trade(t, "SL_HIT", sl)
                closed.append(t)
            elif hit_tp:
                self._close_trade(t, "TP_HIT", tp)
                closed.append(t)

        if closed:
            self._save(trades)
        return closed

    def _close_trade(self, trade: dict, reason: str, exit_price: float) -> None:
        """Mutate `trade` dict in place with closed-state fields."""
        trade["status"] = "CLOSED"
        trade["exit_time"] = datetime.now(timezone.utc).isoformat()
        trade["exit_price"] = exit_price

        if trade["direction"] == "long":
            trade["pnl"] = (exit_price - trade["entry_price"]) * trade["position_size"]
        else:
            trade["pnl"] = (trade["entry_price"] - exit_price) * trade["position_size"]

        stop_dist = abs(trade["entry_price"] - trade["stop_loss"])
        if stop_dist > 0:
            trade["r_multiple"] = round(
                trade["pnl"] / (trade["position_size"] * stop_dist), 2
            )
        else:
            trade["r_multiple"] = 0

        if trade["pnl"] > 0:
            trade["outcome"] = "WIN"
        elif trade["pnl"] < 0:
            trade["outcome"] = "LOSS"
        else:
            trade["outcome"] = "BE"

        trade["notes"] = reason
