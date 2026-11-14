# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared engine kwargs: valid for SQLAlchemy and never duplicated in connect()."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tcbot.database import engine as engine_module

# * The URL the fake engine is built with: the test never opens a socket.
_TEST_URL: str = "postgresql://tcbot:dummy@127.0.0.1:1/tcbot_placeholder"


class _FakeAsyncEngine:
    """Async engine double: records the disposal, opens no connection."""

    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.fixture(autouse=True)
def _restore_engine_state() -> Any:
    """Restore the published engine so connect() cannot leak into later tests."""
    previous_engine = engine_module._engine
    previous_factory = engine_module._session_factory
    try:
        yield
    finally:
        engine_module._engine = previous_engine
        engine_module._session_factory = previous_factory


@pytest.fixture
def captured_engine_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Return the kwargs connect() passes to create_async_engine()."""
    captured: dict[str, Any] = {}

    def _fake_create_async_engine(url: str, **kwargs: Any) -> _FakeAsyncEngine:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeAsyncEngine()

    def _noop_migrations(_url: str) -> None:
        return None

    def _noop_ensure_schema(_url: str, _schema: str) -> None:
        return None

    async def _noop_ping() -> None:
        return None

    monkeypatch.setattr(engine_module, "create_async_engine", _fake_create_async_engine)
    monkeypatch.setattr(
        engine_module.migrations, "upgrade_head", _noop_migrations, raising=True
    )
    monkeypatch.setattr(
        engine_module.migrations, "ensure_schema", _noop_ensure_schema, raising=True
    )
    monkeypatch.setattr(engine_module, "_ping", _noop_ping)
    monkeypatch.setattr(
        engine_module,
        "cfg",
        dataclasses.replace(engine_module.cfg, database_url=_TEST_URL),
    )
    return captured


def _connect() -> None:
    """Run the production connect() against the patched engine factory."""
    asyncio.run(engine_module.connect())


def test_shared_kwargs_cover_server_timeouts(
    captured_engine_kwargs: dict[str, Any],
) -> None:
    """The engine kwargs bound every server-side wait."""
    _connect()

    assert captured_engine_kwargs["pool_timeout"] == engine_module._POOL_TIMEOUT_S
    assert captured_engine_kwargs["pool_recycle"] == engine_module._POOL_RECYCLE_S
    connect_args = captured_engine_kwargs["connect_args"]
    assert connect_args["connect_timeout"] == engine_module._CONNECT_TIMEOUT_S
    # * The session runs in the configured schema and in UTC, exactly like
    # * the scheduler job store and the migration connection.
    assert f"search_path={engine_module.cfg.db_schema}" in connect_args["options"]
    assert "timezone=UTC" in connect_args["options"]


def test_shared_kwargs_size_the_connection_pool(
    captured_engine_kwargs: dict[str, Any],
) -> None:
    """The pool carries the configured capacity and pings stale connections."""
    _connect()

    assert captured_engine_kwargs["pool_size"] == engine_module.cfg.db_pool_size
    assert captured_engine_kwargs["max_overflow"] == engine_module.cfg.db_max_overflow
    assert captured_engine_kwargs["pool_pre_ping"] is True


def test_shared_kwargs_construct_an_async_engine(
    captured_engine_kwargs: dict[str, Any],
) -> None:
    """The captured kwargs are accepted by the SQLAlchemy engine factory."""
    _connect()

    kwargs = dict(captured_engine_kwargs)
    kwargs.pop("url", None)
    built = create_async_engine(
        "postgresql+psycopg://tcbot:dummy@127.0.0.1:1/tcbot_placeholder", **kwargs
    )
    assert isinstance(built, AsyncEngine)

    asyncio.run(built.dispose())


def test_connect_does_not_repeat_shared_kwargs(
    captured_engine_kwargs: dict[str, Any],
) -> None:
    """Guard the production startup crash: connect() must not repeat a kwarg.

    An explicit kwarg passed twice to create_async_engine() is a duplicate
    keyword argument and raises TypeError at boot.
    """
    _connect()

    source = inspect.getsource(engine_module.connect)
    for key in captured_engine_kwargs:
        if key == "url":
            continue
        assert source.count(f"{key}=") == 1, f"{key} is passed twice to the engine"


def test_the_database_url_gets_the_async_driver() -> None:
    """A plain postgresql URL is rewritten for the async psycopg driver."""
    original = engine_module.cfg
    try:
        engine_module.cfg = dataclasses.replace(
            original, database_url="postgresql://user:pw@host:5432/db"
        )
        assert (
            engine_module._database_url() == "postgresql+psycopg://user:pw@host:5432/db"
        )
    finally:
        engine_module.cfg = original


def test_an_async_database_url_is_left_alone() -> None:
    """An already converted URL is not rewritten twice."""
    original = engine_module.cfg
    try:
        engine_module.cfg = dataclasses.replace(
            original, database_url="postgresql+psycopg://user:pw@host:5432/db"
        )
        assert (
            engine_module._database_url() == "postgresql+psycopg://user:pw@host:5432/db"
        )
    finally:
        engine_module.cfg = original
