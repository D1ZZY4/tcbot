# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The two-level cache against a real Redis server.

The unit tests cover the cache with doubles, so they cannot prove that
the real client speaks the wire format the cache expects. This module
runs the same paths against a Redis server and skips when none is
configured.

Every test owns its own keys. The workers of a parallel run share one
Redis server, so a test that flushed the database would erase the keys
another worker had just written.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from tcbot import cfg
from tcbot.database import redis_client as redis_client_mod
from tcbot.database import users_cache
from tcbot.database.cache import drain_redis_mutations, twolevel
from tcbot.database.cache.memory import CACHE_MISS
from tcbot.database.cache.singletons import user_mention_cache

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# * The integration tests read the server URL from the environment and
# * skip when it is unset, so the committed suite never needs a server.
REDIS_URL_ENV: str = "REDIS_URL"

pytestmark = [pytest.mark.redis]

# * Keys per worker. The workers of a parallel run share one Redis
# * server, so each worker owns a disjoint key range.
_KEYS_PER_WORKER: int = 10_000


def _uid(base: int) -> int:
    """Return a key id that belongs to this worker alone."""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if not worker:
        return base
    index = 0
    for char in worker:
        if char.isdigit():
            index = index * 10 + int(char)
    return base + (index + 1) * _KEYS_PER_WORKER


@pytest.fixture(autouse=True)
def _redis_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the Redis configuration the session switched off.

    The shared caches stay on their in-memory layer for the rest of the
    suite, because the Redis half of a cache is eventually consistent.
    This module is the one that checks the Redis half.
    """
    monkeypatch.setattr(twolevel, "cfg", cfg)
    monkeypatch.setattr(redis_client_mod, "cfg", cfg)


@pytest.fixture
async def redis_server() -> AsyncIterator[str]:
    """Yield the Redis URL, with the cache's memory layer emptied."""
    url = os.environ.get(REDIS_URL_ENV, "").strip()
    if not url:
        pytest.skip(f"{REDIS_URL_ENV} is not set; skipping the Redis integration test.")
    await redis_client_mod.connect(url)
    assert redis_client_mod.client() is not None
    user_mention_cache.clear()
    try:
        yield url
    finally:
        user_mention_cache.clear()
        await redis_client_mod.close()


def _key(uid: int) -> str:
    """Return the Redis key the mention cache uses for a user id."""
    return user_mention_cache._rkey(uid)


async def _drop(client: object, *uids: int) -> None:
    """Remove the keys of the given user ids from Redis."""
    keys = [_key(uid) for uid in uids]
    await client.delete(*keys)  # type: ignore[attr-defined]


async def test_a_write_reaches_the_second_layer(redis_server: str) -> None:
    """A value stored in memory lands in Redis as well."""
    client = redis_client_mod.client()
    assert client is not None
    uid = _uid(7)
    await _drop(client, uid)

    user_mention_cache.put(uid, ["Ann", "ann", None])
    await drain_redis_mutations()

    stored = await client.get(_key(uid))
    assert stored is not None


async def test_a_batch_read_finds_a_value_only_in_redis(redis_server: str) -> None:
    """A value that only lives in Redis is found by the batch read."""
    client = redis_client_mod.client()
    assert client is not None
    uid = _uid(8)
    await client.set(_key(uid), '["Ann","ann",null]')

    user_mention_cache.clear()
    found = await user_mention_cache.peek_many([uid])

    assert found == {uid: ["Ann", "ann", None]}


async def test_the_batch_mention_reader_reaches_redis(redis_server: str) -> None:
    """The batch reader finds a name that only lives in Redis."""
    client = redis_client_mod.client()
    assert client is not None
    uid = _uid(9)
    await client.set(_key(uid), '["Ann","ann",null]')
    user_mention_cache.clear()

    names = await users_cache.get_first_names_batch([uid])

    assert names == {uid: "Ann"}


async def test_a_missing_key_is_a_miss(redis_server: str) -> None:
    """A key that Redis does not hold is absent from the result."""
    uid = _uid(10)
    client = redis_client_mod.client()
    assert client is not None
    await _drop(client, uid)

    found = await user_mention_cache.peek_many([uid])

    assert found == {}


async def test_a_large_batch_is_read_in_chunks(redis_server: str) -> None:
    """A batch larger than one chunk still resolves completely."""
    client = redis_client_mod.client()
    assert client is not None
    ids = [_uid(1000 + i) for i in range(200)]
    for uid in ids:
        await client.set(_key(uid), f'["User{uid}",null,null]')
    user_mention_cache.clear()

    found = await user_mention_cache.peek_many(ids)

    assert len(found) == len(ids)


async def test_an_invalidation_clears_both_layers(redis_server: str) -> None:
    """An invalidation removes the value from memory and from Redis."""
    client = redis_client_mod.client()
    assert client is not None
    uid = _uid(11)
    await _drop(client, uid)

    user_mention_cache.put(uid, ["Ann", "ann", None])
    await drain_redis_mutations()
    user_mention_cache.invalidate(uid)
    await drain_redis_mutations()

    assert await client.get(_key(uid)) is None
    assert user_mention_cache.get(uid) is CACHE_MISS
