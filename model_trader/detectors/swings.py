"""Swing high/low detector.

A swing high has lower highs on both sides; swing low has higher lows on both sides.
"""

from __future__ import annotations
from typing import TypedDict


class Swing(TypedDict):
    type: str      # 'high' or 'low'
    price: float
    index: int
    strength: int  # number of confirming candles on each side


def detect_swings(candles: list[dict], lookback: int = 3) -> list[Swing]:
    swings: list[Swing] = []

    for i in range(lookback, len(candles) - lookback):
        is_swing_high = all(
            candles[i]["high"] > candles[i - j]["high"]
            and candles[i]["high"] > candles[i + j]["high"]
            for j in range(1, lookback + 1)
        )

        is_swing_low = all(
            candles[i]["low"] < candles[i - j]["low"]
            and candles[i]["low"] < candles[i + j]["low"]
            for j in range(1, lookback + 1)
        )

        if is_swing_high:
            swings.append(
                Swing(type="high", price=candles[i]["high"], index=i, strength=lookback)
            )
        if is_swing_low:
            swings.append(
                Swing(type="low", price=candles[i]["low"], index=i, strength=lookback)
            )

    return swings
