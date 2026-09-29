# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Persistent moderation scheduler backed by APScheduler 3.x + MongoDB."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .jobs import (
    _EXPIRE_OP_TIMEOUT_S,
    _SYNC_RUN_TIMEOUT_S,
    _cleanup_old_records,
    _run_scheduled_sync,
    expire_old_warns,
)
from .lifecycle import is_ready, start, stop
from .schedules import (
    _CLEANUP_SCHEDULE_ID,
    _SYNC_SCHEDULE_ID,
    _WARN_EXPIRY_SCHEDULE_ID,
    _register_periodic_schedules,
    _scheduler_background,
)

if TYPE_CHECKING:
    import asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from telegram import Bot

# ──────────── Shared mutable state (single owner: this package) ───── #
# * Tests patch these attributes on the package (monkeypatch.setattr on
# * tcbot.database.scheduler), so they live here and every submodule reads
# * them via the package namespace at call time, exactly like
# * tcbot.database.cache.twolevel resolves its patchable names.
# * The dotted import paths APScheduler persisted in MongoDB
# * (tcbot.database.scheduler.expire_old_warns and friends) keep resolving
# * because this package re-exports those exact names below.

_scheduler: AsyncIOScheduler | None = None
_sched_task: asyncio.Task[None] | None = None
_sched_ready: asyncio.Event | None = None
_sched_stop: asyncio.Event | None = None
_sched_error: BaseException | None = None
_sync_bot: Bot | None = None

# * Maximum seconds to wait for the scheduler background task to exit cleanly
# * before declaring it stuck.  10 s matches the PTB shutdown grace window.
_STOP_TIMEOUT_S: float = 10.0

__all__ = [
    "_CLEANUP_SCHEDULE_ID",
    "_EXPIRE_OP_TIMEOUT_S",
    "_STOP_TIMEOUT_S",
    "_SYNC_RUN_TIMEOUT_S",
    "_SYNC_SCHEDULE_ID",
    "_WARN_EXPIRY_SCHEDULE_ID",
    "_cleanup_old_records",
    "_register_periodic_schedules",
    "_run_scheduled_sync",
    "_sched_error",
    "_sched_ready",
    "_sched_stop",
    "_sched_task",
    "_scheduler",
    "_scheduler_background",
    "_sync_bot",
    "expire_old_warns",
    "is_ready",
    "start",
    "stop",
]
