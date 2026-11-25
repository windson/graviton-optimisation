"""Latency histograms in the layout used by Distributed Load Testing on AWS (v4.3).

DLT's native run mode stores, for every request name, a histogram whose buckets are
about 1% wide relative to the latency they hold, so that the representative value of a
bucket is within about 0.5% of any latency in it. This module rebuilds the same bucket
table so that the histograms of all load generator tasks can be added together and
percentiles read from the combined distribution, instead of averaging per-task
percentiles.

The construction follows source/common/src/streaming-statistics/latency-layout.ts in
the DLT repository at tag v4.3.4, and the table is checked against the SHA-256 that
file publishes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache

LAYOUT_ID = "dlt.latency-us.rel-0p5pct.0-24h.v1"
MAX_LATENCY_US = 86_400_000_000
BUCKET_COUNT = 2_184
LAYOUT_SHA256 = "f4f2711a805b2fee2e607d6e93182be0d86b7ff9c93d99a2f23d75e4f2c40c53"


@lru_cache(maxsize=1)
def layout() -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """Returns (lower, upper, representative) bounds in microseconds for every bucket."""
    lower, upper, representative = [], [], []
    low = 1
    while low <= MAX_LATENCY_US:
        rep = min((201 * low) // 200, MAX_LATENCY_US)
        up = min((200 * rep) // 199, MAX_LATENCY_US)
        lower.append(low)
        upper.append(up)
        representative.append(rep)
        low = up + 1
    if len(lower) != BUCKET_COUNT:
        raise AssertionError(f"layout has {len(lower)} buckets, expected {BUCKET_COUNT}")
    rows = "".join(f"{lo},{up},{rep}\n" for lo, up, rep in zip(lower, upper, representative))
    if hashlib.sha256(rows.encode("ascii")).hexdigest() != LAYOUT_SHA256:
        raise AssertionError("latency layout does not match the DLT layout checksum")
    return tuple(lower), tuple(upper), tuple(representative)


@dataclass
class Distribution:
    """Request counts and a latency histogram that can be merged across tasks and labels."""

    total: int = 0
    failed: int = 0
    codes: dict[str, int] = field(default_factory=dict)
    latency_count: int = 0
    latency_sum_us: float = 0.0
    min_us: int | None = None
    max_us: int | None = None
    zero_count: int = 0
    bins: dict[int, int] = field(default_factory=dict)

    def add(self, state: dict) -> None:
        """Adds one entry of a DLT result's `statistics` (the summary or one label)."""
        requests = state["requests"]
        self.total += requests["total"]
        self.failed += requests["failure"]
        for code in state.get("responseCodes", []):
            self.codes[code["code"]] = self.codes.get(code["code"], 0) + code["count"]
        latency = state.get("latency")
        if not latency or latency["count"] == 0:
            return
        self.latency_count += latency["count"]
        self.latency_sum_us += latency["meanUs"] * latency["count"]
        self.min_us = latency["minUs"] if self.min_us is None else min(self.min_us, latency["minUs"])
        self.max_us = latency["maxUs"] if self.max_us is None else max(self.max_us, latency["maxUs"])
        self.zero_count += latency["histogram"]["zeroCount"]
        for index, count in latency["histogram"]["bins"]:
            self.bins[index] = self.bins.get(index, 0) + count

    def merge(self, other: "Distribution") -> None:
        self.total += other.total
        self.failed += other.failed
        for code, count in other.codes.items():
            self.codes[code] = self.codes.get(code, 0) + count
        self.latency_count += other.latency_count
        self.latency_sum_us += other.latency_sum_us
        for value in (other.min_us,):
            if value is not None:
                self.min_us = value if self.min_us is None else min(self.min_us, value)
        for value in (other.max_us,):
            if value is not None:
                self.max_us = value if self.max_us is None else max(self.max_us, value)
        self.zero_count += other.zero_count
        for index, count in other.bins.items():
            self.bins[index] = self.bins.get(index, 0) + count

    def quantile_ms(self, numerator: int, denominator: int) -> float | None:
        """Nearest-rank percentile in milliseconds, clamped to the observed minimum and maximum."""
        if self.latency_count == 0:
            return None
        rank = -(-numerator * self.latency_count // denominator)  # ceiling division
        cumulative = self.zero_count
        value_us = 0
        if cumulative < rank:
            _, _, representative = layout()
            for index in sorted(self.bins):
                cumulative += self.bins[index]
                if cumulative >= rank:
                    value_us = representative[index]
                    break
        value_us = min(max(value_us, self.min_us or 0), self.max_us or value_us)
        return value_us / 1000.0

    def mean_ms(self) -> float | None:
        return None if self.latency_count == 0 else self.latency_sum_us / self.latency_count / 1000.0

    def summary(self) -> dict:
        def q(n: int, d: int) -> float | None:
            value = self.quantile_ms(n, d)
            return None if value is None else round(value, 3)

        mean = self.mean_ms()
        return {
            "requests": self.total,
            "failed": self.failed,
            "error_rate": (self.failed / self.total) if self.total else None,
            "codes": dict(sorted(self.codes.items())),
            "mean_ms": None if mean is None else round(mean, 3),
            "min_ms": None if self.min_us is None else self.min_us / 1000.0,
            "p50_ms": q(50, 100),
            "p90_ms": q(90, 100),
            "p95_ms": q(95, 100),
            "p99_ms": q(99, 100),
            "p99_9_ms": q(999, 1000),
            "max_ms": None if self.max_us is None else self.max_us / 1000.0,
        }

    def to_state(self) -> dict:
        """Compact form stored with a run so percentiles can be recomputed later."""
        return {
            "layout": LAYOUT_ID,
            "total": self.total,
            "failed": self.failed,
            "codes": dict(sorted(self.codes.items())),
            "latency_count": self.latency_count,
            "latency_sum_us": self.latency_sum_us,
            "min_us": self.min_us,
            "max_us": self.max_us,
            "zero_count": self.zero_count,
            "bins": sorted(self.bins.items()),
        }

    @classmethod
    def from_state(cls, state: dict) -> "Distribution":
        return cls(
            total=state["total"],
            failed=state["failed"],
            codes=dict(state["codes"]),
            latency_count=state["latency_count"],
            latency_sum_us=state["latency_sum_us"],
            min_us=state["min_us"],
            max_us=state["max_us"],
            zero_count=state["zero_count"],
            bins={int(index): count for index, count in state["bins"]},
        )
