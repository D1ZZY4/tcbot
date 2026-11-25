# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Peer lookups for rich edits stay off the remote session database."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot.database import mtproto_store


@pytest.fixture
def _store_and_queries(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict[str, int]]:
    store = mtproto_store.PostgresStorage("cache-test")
    calls = {"db": 0, "writes": 0}
    row = {"access_hash": 123, "type": "user"}

    async def _db_call(op: Any, **_kwargs: Any) -> Any:
        calls["db"] += 1
        return await op()

    async def _fetch_one(_stmt: Any) -> dict[str, Any]:
        return dict(row)

    async def _no_write(*_args: Any, **_kwargs: Any) -> None:
        calls["writes"] += 1

    monkeypatch.setattr(mtproto_store, "db_call", _db_call)
    monkeypatch.setattr(mtproto_store, "fetch_one", _fetch_one)
    monkeypatch.setattr(mtproto_store, "_retry_write", _no_write)
    monkeypatch.setattr(
        mtproto_store,
        "get_input_peer",
        lambda peer_id, access_hash, peer_type: (peer_id, access_hash, peer_type),
    )
    return store, calls


@pytest.mark.asyncio
async def test_a_repeated_peer_lookup_does_not_hit_the_database(
    _store_and_queries: tuple[Any, dict[str, int]],
) -> None:
    store, calls = _store_and_queries

    first = await store.get_peer_by_id(42)
    second = await store.get_peer_by_id(42)

    assert first == second == (42, 123, "user")
    assert calls["db"] == 1


@pytest.mark.asyncio
async def test_telegram_peer_updates_refresh_the_cache(
    _store_and_queries: tuple[Any, dict[str, int]],
) -> None:
    store, calls = _store_and_queries
    await store.get_peer_by_id(42)

    await store.update_peers([(42, 999, "user", None)])

    assert await store.get_peer_by_id(42) == (42, 999, "user")
    assert calls["db"] == 1
    assert calls["writes"] == 1


@pytest.mark.asyncio
async def test_deleting_the_session_invalidates_the_cache(
    _store_and_queries: tuple[Any, dict[str, int]],
) -> None:
    store, calls = _store_and_queries
    await store.get_peer_by_id(42)

    await store.delete()

    assert store._peer_cache == {}
    await store.get_peer_by_id(42)
    assert calls["db"] == 2


@pytest.mark.asyncio
async def test_a_failed_relogin_invalidates_the_cache(
    _store_and_queries: tuple[Any, dict[str, int]],
) -> None:
    store, calls = _store_and_queries
    await store.get_peer_by_id(42)

    await store.clear_session_for_relogin()

    assert store._peer_cache == {}
    await store.get_peer_by_id(42)
    assert calls["db"] == 2
