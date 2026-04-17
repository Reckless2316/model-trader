"""Failure swing detector.

Groups swing highs/lows that cluster at similar price levels.
Multiple failures at a level = stronger draw on liquidity.
"""

from __future__ import annotations
from typing import TypedDict


class FailureSwing(TypedDict):
    level: float
    count: int
    type: str  # 'high' or 'low'


def detect_failure_swings(
    swings: list[dict], tolerance_pct: float = 0.1
) -> list[FailureSwing]:
    clusters: list[FailureSwing] = []
    used: set[int] = set()

    for i, swing in enumerate(swings):
        if i in used:
            continue

        cluster = [swing]
        used.add(i)

        for j, other in enumerate(swings):
            if j in used or swing["type"] != other["type"]:
                continue

            diff = abs(swing["price"] - other["price"]) / swing["price"]
            if diff <= tolerance_pct / 100:
                cluster.append(other)
                used.add(j)

        if len(cluster) >= 2:
            avg_price = sum(s["price"] for s in cluster) / len(cluster)
            clusters.append(
                FailureSwing(level=avg_price, count=len(cluster), type=swing["type"])
            )

    return clusters
