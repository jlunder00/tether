"""Lightweight Prometheus-format metrics registry for the agent pool manager.

No external dependency — renders the standard Prometheus text exposition format
(https://prometheus.io/docs/instrumenting/exposition_formats/).

Intended usage:
    metrics = PoolMetrics()
    metrics.acquire_total.inc()
    metrics.acquire_latency_seconds.observe(0.123)
    text = metrics.render_text()   # feed to GET /metrics
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Primitive metric types
# ---------------------------------------------------------------------------

class Counter:
    """Monotonically increasing counter."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self._value: float = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        return self._value

    def render_text(self) -> str:
        return (
            f"# HELP {self.name} {self.help_text}\n"
            f"# TYPE {self.name} counter\n"
            f"{self.name} {self._value}\n"
        )


_DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Histogram:
    """Prometheus-style histogram with configurable bucket boundaries."""

    def __init__(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...] = _DEFAULT_BUCKETS,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self._buckets = sorted(buckets)
        self._counts: list[float] = [0.0] * len(self._buckets)
        self._inf_count: float = 0.0
        self._sum: float = 0.0
        self._total_count: float = 0.0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._total_count += 1.0
            self._inf_count += 1.0
            # _counts[i] stores the *cumulative* count of observations <= bound[i].
            # Every observation increments all buckets whose bound it fits within.
            # render_text() emits _counts[i] directly — no re-accumulation needed.
            for i, bound in enumerate(self._buckets):
                if value <= bound:
                    self._counts[i] += 1.0

    def render_text(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        # _counts[i] is already the cumulative count for le=bound[i] —
        # emit directly without re-accumulating (which would double-count).
        for i, bound in enumerate(self._buckets):
            lines.append(f'{self.name}_bucket{{le="{bound}"}} {self._counts[i]}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._inf_count}')
        lines.append(f"{self.name}_sum {self._sum}")
        lines.append(f"{self.name}_count {self._total_count}")
        return "\n".join(lines) + "\n"


class Gauge:
    """Point-in-time gauge, driven by a callable for dynamic values."""

    def __init__(self, name: str, help_text: str, fn: Callable[[], float]) -> None:
        self.name = name
        self.help_text = help_text
        self._fn = fn

    def render_text(self) -> str:
        value = self._fn()
        return (
            f"# HELP {self.name} {self.help_text}\n"
            f"# TYPE {self.name} gauge\n"
            f"{self.name} {value}\n"
        )


# ---------------------------------------------------------------------------
# PoolMetrics — the registry
# ---------------------------------------------------------------------------

class PoolMetrics:
    """All Prometheus metrics for the agent pool manager.

    Attach to a Pool instance via ``pool._metrics = metrics`` so the pool can
    record events.  The server renders via ``metrics.render_text()``.
    """

    def __init__(self, pool: "Pool | None" = None) -> None:  # type: ignore[name-defined]
        self._pool = pool

        self.acquire_total = Counter(
            "pool_acquire_total",
            "Total successful subprocess acquisitions",
        )
        self.acquire_timeout_total = Counter(
            "pool_acquire_timeout_total",
            "Total acquire attempts that timed out (PoolExhausted)",
        )
        self.release_total = Counter(
            "pool_release_total",
            "Total subprocess releases",
        )
        self.expire_total = Counter(
            "pool_expire_total",
            "Total subprocesses drained due to TTL expiry",
        )
        self.refill_total = Counter(
            "pool_refill_total",
            "Total subprocess spawns triggered by refill loop",
        )
        self.spawn_guard_rejection_total = Counter(
            "pool_spawn_guard_rejection_total",
            "Total spawn attempts rejected by the auth guard (missing CLAUDE_CODE_OAUTH_TOKEN)",
        )
        self.acquire_latency_seconds = Histogram(
            "pool_acquire_latency_seconds",
            "Time from acquire() call to handle returned (seconds)",
        )

    def attach_pool(self, pool: "Pool") -> None:  # type: ignore[name-defined]
        """Attach this metrics instance to a pool for gauge rendering."""
        self._pool = pool

    def render_text(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        parts = [
            self.acquire_total.render_text(),
            self.acquire_timeout_total.render_text(),
            self.release_total.render_text(),
            self.expire_total.render_text(),
            self.refill_total.render_text(),
            self.spawn_guard_rejection_total.render_text(),
            self.acquire_latency_seconds.render_text(),
        ]

        # Dynamic gauges from pool state (if attached)
        if self._pool is not None:
            status = self._pool.status()
            parts += [
                _gauge_text("pool_size_warm", "Current warm subprocess count", status.get("total_warm", 0)),
                _gauge_text("pool_size_active", "Current active (handed-out) subprocess count", status.get("total_active", 0)),
                _gauge_text("pool_size_warming", "Current subprocesses being spawned/primed", status.get("total_warming", 0)),
                _gauge_text("pool_capacity_total", "Configured total subprocess capacity", status.get("capacity_total", 0)),
            ]

        return "".join(parts)


def _gauge_text(name: str, help_text: str, value: float) -> str:
    return (
        f"# HELP {name} {help_text}\n"
        f"# TYPE {name} gauge\n"
        f"{name} {value}\n"
    )
