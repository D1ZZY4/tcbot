# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The batch cache read must reach L2, not only the in-memory layer.

The batch readers serve a whole list of user ids in one call. Reading
the in-memory layer only would send every batch back to the database
after a restart, while the single-key reader still found the value in
Redis. One Redis round trip for the whole batch keeps the two paths on
the same cache.
"""

from __future__ import annotations

import asyncio
from typing import Any

import msgspec
import pytest

import tcbot.database.cache as cache_mod
from tcbot.database import users_cache
from tcbot.database.cache import redis_io
from tcbot.database.cache.codec import _msgspec_enc_hook, _tag_scalars
from tcbot.database.cache.memory import CACHE_MISS


class _FakeRedis:
    """A Redis double that stores the values it is handed."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.mget_calls = 0

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def mget(self, *keys: str) -> list[str | None]:
        self.mget_calls += 1
        return [self.store.get(key) for key in keys]

    async def set(self, key: str, value: str) -> bool:
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.store.pop(key, None)
        return 1


def _cache() -> cache_mod.TwoLevelCache[list[str | None]]:
    return cache_mod.TwoLevelCache(
        memory_ttl=60.0,
        redis_ttl=90.0,
        redis_prefix="test-batch-peek",
    )


def _encode(value: Any) -> str:
    """Encode one value the way the cache stores it."""
    return msgspec.json.encode(_tag_scalars(value), enc_hook=_msgspec_enc_hook).decode(
        "utf-8"
    )


def test_a_batch_read_reaches_the_second_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value that only exists in Redis must come back from a batch read."""
    redis = _FakeRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: redis)

    cache = _cache()
    redis.store["tcbot:test-batch-peek:v2:7"] = _encode(["Ann", "ann", None])

    found = asyncio.run(cache.peek_many([7, 8]))

    assert found == {7: ["Ann", "ann", None]}
    assert redis.mget_calls == 1


def test_a_batch_read_fills_the_in_memory_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value read from Redis must be cached for the next read."""
    redis = _FakeRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: redis)

    cache = _cache()
    redis.store["tcbot:test-batch-peek:v2:7"] = _encode(["Ann", "ann", None])

    asyncio.run(cache.peek_many([7]))
    redis.mget_calls = 0
    found = asyncio.run(cache.peek_many([7]))

    assert found == {7: ["Ann", "ann", None]}
    assert redis.mget_calls == 0


def test_a_batch_read_serves_the_in_memory_layer_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value the in-memory layer already holds costs no round trip."""
    redis = _FakeRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: redis)

    cache = _cache()
    cache.put(7, ["Ann", "ann", None])

    found = asyncio.run(cache.peek_many([7]))

    assert found == {7: ["Ann", "ann", None]}
    assert redis.mget_calls == 0


def test_peek_does_not_promote_stale_l2_after_a_local_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queued local write must not be undone by an older Redis value."""
    redis = _FakeRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: redis)
    cache = _cache()
    redis.store["tcbot:test-batch-peek:v2:7"] = _encode(["Old", "old", None])
    # * put() marks the key until the queued write lands; simulate that window.
    cache._pending_writes.add(7)

    found = asyncio.run(cache.peek(7))

    assert found == ["Old", "old", None]
    assert cache.get(7) is CACHE_MISS


def test_a_queued_write_is_skipped_when_a_tombstone_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another process's revocation must not be overwritten by a stale fill."""

    class _RevokedRedis(_FakeRedis):
        async def exists(self, key: str) -> int:
            return 1

    redis = _RevokedRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: redis)

    asyncio.run(_cache()._redis_set_guarded("value-key", "payload", "tomb-key"))

    assert "value-key" not in redis.store


def test_a_batch_read_treats_a_redis_outage_as_a_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable Redis must not raise; the keys stay absent."""

    class _DeadRedis:
        async def mget(self, *keys: str) -> list[str | None]:
            raise OSError("redis is down")

    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: _DeadRedis())

    found = asyncio.run(_cache().peek_many([7, 8]))

    assert found == {}


def test_the_batch_mention_reader_reaches_the_second_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The batch reader must find a value that only lives in Redis.

    The single-user reader consults both cache layers, so the batch
    reader has to as well. A warm Redis that the batch reader ignores
    sends every list view back to the database.
    """
    redis = _FakeRedis()
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: redis)

    async def _no_database(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the batch reader reached the database")

    monkeypatch.setattr(users_cache, "fetch_all", _no_database)

    triple = ["Ann", "ann", None]
    # * The key comes from the cache itself: the workers of a parallel
    # * run use their own Redis namespace for the shared caches.
    redis.store[users_cache.user_mention_cache._rkey(7)] = _encode(triple)
    users_cache.user_mention_cache.clear()

    names = asyncio.run(users_cache.get_first_names_batch([7]))

    assert names == {7: "Ann"}
