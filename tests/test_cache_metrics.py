# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Cache metrics stay available without the optional Prometheus package."""

from __future__ import annotations

from tcbot.utils import metrics


def test_cache_counters_and_queue_depth() -> None:
    metrics.reset()

    metrics.record_hit("l1")
    metrics.record_hit("l1")
    metrics.record_hit("l2")
    metrics.record_miss()
    metrics.record_invalidation()
    metrics.record_drop("role")
    metrics.set_queue_depth("role", 3)
    metrics.set_redis_available(available=True)

    snapshot = metrics.snapshot()
    assert snapshot["hits"] == {"l1": 2, "l2": 1}
    assert snapshot["misses"] == 1
    assert snapshot["invalidations"] == 1
    assert snapshot["drops"] == 1
    assert snapshot["queue_depth"] == {"role": 3}
    assert snapshot["redis_available"] is True

    metrics.reset()
    assert metrics.snapshot()["misses"] == 0
