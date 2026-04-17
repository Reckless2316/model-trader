"""CISD (Change in State of Delivery) detector.

Detects market structure shifts when a swing high/low is broken.
Also detects the "breaker" candle that forms after CISD.
"""

from __future__ import annotations
from typing import TypedDict


class CISDSignal(TypedDict):
    type: str           # 'bullish' or 'bearish'
    broken_level: float
    swing_index: int


class Breaker(TypedDict):
    type: str   # 'bullish_breaker' or 'bearish_breaker'
    high: float
    low: float
    index: int


def detect_cisd(candles: list[dict], swings: list[dict]) -> list[CISDSignal]:
    signals: list[CISDSignal] = []
    current_price = candles[-1]["close"]

    recent_lows = [s for s in swings if s["type"] == "low"][-3:]
    recent_highs = [s for s in swings if s["type"] == "high"][-3:]

    for swing in recent_lows:
        if current_price < swing["price"]:
            signals.append(
                CISDSignal(
                    type="bearish",
                    broken_level=swing["price"],
                    swing_index=swing["index"],
                )
            )
            break

    for swing in recent_highs:
        if current_price > swing["price"]:
            signals.append(
                CISDSignal(
                    type="bullish",
                    broken_level=swing["price"],
                    swing_index=swing["index"],
                )
            )
            break

    return signals


def detect_cisd_breaker(
    candles: list[dict], cisd_signal: CISDSignal | None
) -> Breaker | None:
    if not cisd_signal:
        return None

    cisd_index = cisd_signal["swing_index"]

    if cisd_signal["type"] == "bearish":
        for i in range(cisd_index - 1, max(0, cisd_index - 10), -1):
            if i < len(candles) and candles[i]["close"] > candles[i]["open"]:
                return Breaker(
                    type="bearish_breaker",
                    high=candles[i]["high"],
                    low=candles[i]["low"],
                    index=i,
                )
    else:
        for i in range(cisd_index - 1, max(0, cisd_index - 10), -1):
            if i < len(candles) and candles[i]["close"] < candles[i]["open"]:
                return Breaker(
                    type="bullish_breaker",
                    high=candles[i]["high"],
                    low=candles[i]["low"],
                    index=i,
                )

    return None
