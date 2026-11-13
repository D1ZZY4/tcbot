# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared pytest fixtures: mirror production logging startup for every test session."""

from __future__ import annotations

import dataclasses
import os
from typing import TYPE_CHECKING

# * Dummy import-time env: tcbot/__init__ loads Configs at import, so the
# * suite must not depend on CI-only env to collect. setdefault keeps real
# * CI/local values when already present.
os.environ.setdefault("BOT_TOKEN", "000000:dummy-token-for-lint000000000000000")
# * The dummy URL points at a port nothing listens on: the unit tests
# * never open a connection, so the placeholder must not be able to reach
# * a real server.
os.environ.setdefault(
    "DATABASE_URL", "postgresql://tcbot:dummy@127.0.0.1:1/tcbot_placeholder"
)
os.environ.setdefault("OWNER_ID", "1")

import pytest

from tcbot import cfg
from tcbot.database import redis_client as redis_client_mod
from tcbot.database.cache import singletons, twolevel
from tcbot.utils.logger import setup as setup_logging
from tests.postgres_support import (
    build_test_schema,
    drop_test_schema,
    require_test_database,
    reset_postgres_circuit,
    use_test_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


@pytest.fixture(scope="session", autouse=True)
def _production_logging() -> None:
    """Install the production logging setup once, like main() does at startup.

    Modules log through the loguru-backed shim (bridged to stdlib), which
    only reaches caplog and the Telegram error handler after configure()
    runs. Without this, records would fall back to loguru's default
    print-to-stdout facility and tests asserting on log output fail.
    """
    setup_logging()


@pytest.fixture(scope="session", autouse=True)
def _cache_key_namespace() -> None:
    """Move the shared caches into a test-only Redis namespace.

    The shared caches use fixed keys, and the owner cache uses one global
    key. Two workers would therefore read each other's entries when Redis
    is configured, and the tests that pin the cached and the fresh read
    would fail depending on the worker order.

    The namespace is applied in every run, not only under xdist. A serial
    run against a deployment Redis would otherwise write, read, and
    delete keys in the live namespace, where they collide with real cache
    entries of the running bot. The test-only suffix keeps every key the
    suite touches out of the deployment namespace.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    suffix = f"-test-{worker}" if worker else "-test"
    for cache in (
        singletons.effective_role_cache,
        singletons.connected_cache,
        singletons.active_groups_cache,
        singletons.owner_id_cache,
        singletons.user_mention_cache,
    ):
        cache._redis_prefix = f"{cache._redis_prefix}{suffix}"


@pytest.fixture(scope="session", autouse=True)
def _shared_caches_stay_in_memory() -> Iterator[None]:
    """Keep the shared caches on their in-memory layer for the whole suite.

    The Redis half of a cache is eventually consistent: an invalidation
    clears the in-memory entry at once and queues the Redis delete. The
    tests run each case on its own event loop, and a queued delete dies
    with the loop it was queued on, so the stale entry would stay in
    Redis and the next test would read it. The module that exercises
    Redis on purpose restores the configuration.
    """
    memory_only = dataclasses.replace(cfg, redis_url="")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(twolevel, "cfg", memory_only)
        patch.setattr(redis_client_mod, "cfg", memory_only)
        yield


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Return the test database URL and own the schema for the session.

    The test skips when no server is configured, so the committed suite
    never depends on a reachable database.
    """
    url = require_test_database()
    build_test_schema(url)
    try:
        yield url
    finally:
        drop_test_schema(url)


@pytest.fixture
async def postgres_db(postgres_url: str) -> AsyncIterator[str]:
    """Point the shared engine module at the test database."""
    reset_postgres_circuit()
    async with use_test_engine(postgres_url):
        yield postgres_url
