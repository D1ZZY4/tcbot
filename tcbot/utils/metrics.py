# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Low-cost cache counters with an optional Prometheus surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tcbot.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class _CacheStats:
    """Process-local counters used by tests and when Prometheus is absent."""

    hits: dict[str, int] = field(default_factory=dict)
    misses: int = 0
    invalidations: int = 0
    drops: int = 0
    evictions: int = 0
    queue_depth: dict[str, int] = field(default_factory=dict)
    redis_available: bool | None = None


_STATS = _CacheStats()

# * prometheus-client is optional. The metrics exist either way; the
# * registry only gets the series when the observability extra is installed.
try:
    from prometheus_client import Counter, Gauge  # type: ignore[reportMissingImports]

    _HITS = Counter(
        "tcbot_cache_hits_total",
        "Cache reads served by a cache layer.",
        ["layer"],
    )
    _MISSES = Counter(
        "tcbot_cache_misses_total",
        "Cache reads that had to reach the source.",
    )
    _INVALIDATIONS = Counter(
        "tcbot_cache_invalidations_total",
        "Cache invalidations requested.",
    )
    _DROPS = Counter(
        "tcbot_cache_invalidation_drops_total",
        "Cache mutations dropped by the bounded queue.",
        ["prefix"],
    )
    _EVICTIONS = Counter(
        "tcbot_cache_queue_evictions_total",
        "Droppable cache mutations evicted to queue a revocation.",
        ["prefix"],
    )
    _QUEUE_DEPTH = Gauge(
        "tcbot_cache_queue_depth",
        "Queued Redis mutations per cache prefix.",
        ["prefix"],
    )
    _REDIS_AVAILABLE = Gauge(
        "tcbot_redis_available",
        "Whether the Redis client is usable (1) or not (0).",
    )
except Exception:  # pragma: no cover - exercised only without the extra
    _HITS = _MISSES = _INVALIDATIONS = _DROPS = _EVICTIONS = None
    _QUEUE_DEPTH = _REDIS_AVAILABLE = None


def record_hit(layer: str) -> None:
    """Count one cache hit from ``l1`` or ``l2``."""
    _STATS.hits[layer] = _STATS.hits.get(layer, 0) + 1
    if _HITS is not None:
        _HITS.labels(layer).inc()


def record_miss() -> None:
    """Count one cache read that had to reach the source."""
    _STATS.misses += 1
    if _MISSES is not None:
        _MISSES.inc()


def record_invalidation() -> None:
    """Count one cache invalidation request."""
    _STATS.invalidations += 1
    if _INVALIDATIONS is not None:
        _INVALIDATIONS.inc()


def record_drop(prefix: str) -> None:
    """Count one mutation the bounded Redis queue had to drop."""
    _STATS.drops += 1
    if _DROPS is not None:
        _DROPS.labels(prefix).inc()


def record_eviction(prefix: str) -> None:
    """Count one droppable mutation evicted to make room for a revocation."""
    _STATS.evictions += 1
    if _EVICTIONS is not None:
        _EVICTIONS.labels(prefix).inc()


def set_queue_depth(prefix: str, depth: int) -> None:
    """Publish the queued mutation depth of one cache prefix."""
    _STATS.queue_depth[prefix] = depth
    if _QUEUE_DEPTH is not None:
        _QUEUE_DEPTH.labels(prefix).set(depth)


def set_redis_available(*, available: bool) -> None:
    """Publish whether the Redis client can serve the current loop."""
    _STATS.redis_available = available
    if _REDIS_AVAILABLE is not None:
        _REDIS_AVAILABLE.set(1 if available else 0)


def snapshot() -> dict[str, Any]:
    """Return the process-local counters for tests and diagnostics."""
    return {
        "hits": dict(_STATS.hits),
        "misses": _STATS.misses,
        "invalidations": _STATS.invalidations,
        "drops": _STATS.drops,
        "evictions": _STATS.evictions,
        "queue_depth": dict(_STATS.queue_depth),
        "redis_available": _STATS.redis_available,
    }


def reset() -> None:
    """Clear the process-local counters (tests only)."""
    global _STATS
    _STATS = _CacheStats()
