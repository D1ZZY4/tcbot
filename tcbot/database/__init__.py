# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Database package: the schema, the engine, and one module per domain.

The table helpers are imported on demand rather than eagerly. The
package holds the SQLAlchemy engine, the APScheduler job store, the
Redis client, and the MTProto session store, and importing all of them
made the schema tools (the Alembic environment, the migration
generator) load the whole application before they could read a table
definition.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    from . import (
        bans_db,
        base,
        documents,
        engine,
        groups_db,
        kicks_db,
        migrations,
        moderation_db,
        mtproto,
        mutes_db,
        queues_db,
        redis_client,
        scheduler,
        schema,
        settings_db,
        types,
        users_cache,
        users_roles,
        warns_db,
    )

# * Every module the package exposes. The list is the single source of
# * truth for the lazy import and for the package surface.
_SUBMODULES: frozenset[str] = frozenset(
    {
        "bans_db",
        "base",
        "documents",
        "engine",
        "groups_db",
        "kicks_db",
        "migrations",
        "moderation_db",
        "mtproto",
        "mutes_db",
        "queues_db",
        "redis_client",
        "scheduler",
        "schema",
        "settings_db",
        "types",
        "users_cache",
        "users_roles",
        "warns_db",
    }
)


def __getattr__(name: str) -> ModuleType:
    """Import one table helper on first access (PEP 562)."""
    if name not in _SUBMODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{name}", __name__)
    # * The import machinery already binds the submodule on the package,
    # * so later reads skip this hook.
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    """Return the package surface, including the lazy submodules."""
    return sorted(_SUBMODULES)


__all__ = [
    "bans_db",
    "base",
    "documents",
    "engine",
    "groups_db",
    "kicks_db",
    "migrations",
    "moderation_db",
    "mtproto",
    "mutes_db",
    "queues_db",
    "redis_client",
    "scheduler",
    "schema",
    "settings_db",
    "types",
    "users_cache",
    "users_roles",
    "warns_db",
]
