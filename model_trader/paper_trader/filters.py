"""Filters that plug into the monitor loop before execute_paper_trade().

These prevent two common failure modes:
  - Scalp duplicates: same setup re-firing after a TP hit while price
    oscillates in the same range.
  - Death-by-a-thousand-cuts: re-entering the same losing level over and
    over when the structure has failed but price hasn't moved away.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _load_trades(journal_path: str | Path) -> list[dict]:
    path = Path(journal_path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_duplicate_setup(
    journal_path: str | Path,
    symbol: str,
    entry: float,
    stop: float,
    target: float,
    lookback_minutes: int = 15,
    tolerance_pct: float = 0.02,
) -> bool:
    """Check if this exact setup (same entry/sl/tp within tolerance) was
    recently traded.

    Prevents re-entering the identical breaker level when price oscillates
    through it multiple times.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=lookback_minutes)

    tol_entry = abs(entry) * tolerance_pct / 100
    tol_stop = abs(stop) * tolerance_pct / 100
    tol_target = abs(target) * tolerance_pct / 100

    for t in _load_trades(journal_path):
        if t.get("symbol") != symbol:
            continue
        if t.get("status") != "CLOSED" or not t.get("exit_time"):
            continue
        try:
            exit_time = datetime.fromisoformat(t["exit_time"])
            if exit_time <= cutoff:
                continue
        except Exception:
            continue

        if (abs(t["entry_price"] - entry) <= tol_entry
                and abs(t["stop_loss"] - stop) <= tol_stop
                and abs(t["take_profit"] - target) <= tol_target):
            return True

    return False


def is_invalidated_level(
    journal_path: str | Path,
    symbol: str,
    direction: str,
    stop: float,
    current_price: float,
    max_age_hours: int = 6,
    tolerance_pct: float = 0.2,
    required_distance_pct: float = 0.5,
) -> bool:
    """Structural check: is the proposed stop near a recently-blown level
    AND price hasn't moved meaningfully away from it?

    After a SL hits, the level has been violated. We only allow re-engagement
    when price has traveled required_distance_pct in the trade's favor away
    from the blown level — proving the structure has actually changed.

    For a new short: need current price at least required_distance_pct BELOW
    the blown level. For a long: ABOVE.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    tolerance = abs(stop) * tolerance_pct / 100

    for t in _load_trades(journal_path):
        if t.get("symbol") != symbol:
            continue
        if t.get("direction") != direction:
            continue
        if t.get("notes") != "SL_HIT":
            continue
        if not t.get("exit_time"):
            continue
        try:
            exit_time = datetime.fromisoformat(t["exit_time"])
            if exit_time <= cutoff:
                continue
        except Exception:
            continue

        blown_level = t["stop_loss"]
        if abs(blown_level - stop) > tolerance:
            continue

        required_distance = abs(blown_level) * required_distance_pct / 100

        if direction == "short":
            distance_moved = blown_level - current_price
            if distance_moved < required_distance:
                return True
        else:
            distance_moved = current_price - blown_level
            if distance_moved < required_distance:
                return True

    return False
