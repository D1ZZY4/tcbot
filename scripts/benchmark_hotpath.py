# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Hot-path micro-benchmark for the bot's bounded-concurrency primitives.

Measures the pieces every request pays for: the database call transport,
the two-level cache on hit and miss, and the bounded multi-group fan-out.
The benchmark runs entirely in-process, so it needs no MongoDB, Redis, or
Telegram connection and produces a comparable baseline on every machine.

Run it with:

    uv run python scripts/benchmark_hotpath.py

Use the numbers as a relative baseline, not as an absolute latency promise:
the absolute values depend on the host, its CPU count, and the load.
"""

from __future__ import annotations

import asyncio
import dataclasses
import statistics
import time

from tcbot import cfg
from tcbot.database import mongos
from tcbot.database import redis_client as redis_client_mod
from tcbot.database.cache import twolevel as cache_twolevel
from tcbot.database.cache.twolevel import TwoLevelCache
from tcbot.utils.dispatch import fan_out

# * Iterations per scenario. Small enough to run in a second, large enough
# * for the median to be stable.
_ITERATIONS: int = 2000
# * Groups used by the fan-out scenario.
_FANOUT_GROUPS: int = 100


def _disable_redis() -> None:
    """Keep the benchmark in-process: no Redis connection, no queued writes.

    The ambient configuration may point at a real Redis; the benchmark
    measures the local primitives, so the shared cache is turned off.
    """
    local = dataclasses.replace(cfg, redis_url=None)
    cache_twolevel.cfg = local
    mongos.cfg = local
    redis_client_mod.cfg = local


def _measure(label: str, samples: list[float]) -> None:
    """Print the median and p95 of a latency sample in milliseconds."""
    ordered = sorted(samples)
    median = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print(f"{label:<34} median={median * 1000:8.3f} ms   p95={p95 * 1000:8.3f} ms")


async def _bench_db_call() -> None:
    """Measure one database-call round trip through the worker pool."""
    samples: list[float] = []
    for _ in range(_ITERATIONS):
        start = time.perf_counter()
        await mongos.db_call(lambda: None)
        samples.append(time.perf_counter() - start)
    _measure("db_call (no-op worker)", samples)


async def _bench_cache_hit() -> None:
    """Measure an L1 cache hit."""
    cache: TwoLevelCache[str] = TwoLevelCache(
        memory_ttl=60.0, redis_ttl=90.0, redis_prefix="bench"
    )
    cache.put("k", "v")
    samples: list[float] = []
    for _ in range(_ITERATIONS):
        start = time.perf_counter()
        await cache.get_or_fetch("k", _never_called)
        samples.append(time.perf_counter() - start)
    _measure("cache L1 hit", samples)


async def _bench_cache_miss() -> None:
    """Measure an L1 miss that falls through to the fetch."""
    cache: TwoLevelCache[str] = TwoLevelCache(
        memory_ttl=0.001, redis_ttl=90.0, redis_prefix="bench"
    )
    samples: list[float] = []
    for index in range(_ITERATIONS):
        start = time.perf_counter()
        await cache.get_or_fetch(index, _fetch_value)
        samples.append(time.perf_counter() - start)
    _measure("cache L1 miss + fetch", samples)


async def _bench_fan_out() -> None:
    """Measure a bounded fan-out across the group set."""
    samples: list[float] = []
    for _ in range(max(1, _ITERATIONS // 10)):
        start = time.perf_counter()
        await fan_out([_no_op() for _ in range(_FANOUT_GROUPS)])
        samples.append(time.perf_counter() - start)
    _measure(f"fan_out ({_FANOUT_GROUPS} groups)", samples)


async def _bench_fan_out_bound() -> None:
    """Verify that the fan-out really keeps the concurrency bounded."""
    peak = 0
    live = 0

    async def _tracked() -> None:
        nonlocal peak, live
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.005)
        live -= 1

    await fan_out([_tracked() for _ in range(_FANOUT_GROUPS)])
    print(f"{'fan_out peak concurrency':<34} {peak:>8} (cap 10)")


async def _never_called() -> str:
    """Fetch callback that must never run on a cache hit."""
    raise AssertionError("the fetch must not run on a cache hit")


async def _fetch_value() -> str:
    """Fetch callback for the cache-miss scenario."""
    return "value"


async def _no_op() -> None:
    """Trivial awaited operation for the fan-out scenario."""
    await asyncio.sleep(0)


async def _main() -> None:
    """Run every scenario and print the report."""
    _disable_redis()
    print(f"Hot-path micro-benchmark ({_ITERATIONS} iterations per scenario)\n")
    await _bench_db_call()
    await _bench_cache_hit()
    await _bench_cache_miss()
    await _bench_fan_out()
    await _bench_fan_out_bound()


def main() -> None:
    """Entry point for the benchmark script."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
