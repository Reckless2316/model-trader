"""Displacement detector.

Identifies strong, aggressive price moves (candles significantly larger than average).
"""

from __future__ import annotations
from typing import TypedDict


class Displacement(TypedDict):
    index: int
    direction: str   # 'bullish' or 'bearish'
    size_ratio: float


def detect_displacement(
    candles: list[dict], lookback: int = 5, threshold_multiplier: float = 2.0
) -> list[Displacement]:
    sizes = [abs(c["close"] - c["open"]) for c in candles[-lookback * 3 : -lookback]]
    avg_size = sum(sizes) / len(sizes) if sizes else 0

    displacements: list[Displacement] = []
    for i, c in enumerate(candles[-lookback:]):
        size = abs(c["close"] - c["open"])
        if avg_size > 0 and size > avg_size * threshold_multiplier:
            displacements.append(
                Displacement(
                    index=len(candles) - lookback + i,
                    direction="bullish" if c["close"] > c["open"] else "bearish",
                    size_ratio=size / avg_size,
                )
            )

    return displacements
