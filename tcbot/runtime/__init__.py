# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Runtime package: member cache, error layers, lifecycle, and process entry."""

from __future__ import annotations

from .entry import (
    _FATAL_BORDER_WIDTH,
    _FATAL_RED,
    _FATAL_RESET,
    _print_fatal,
    _run_webhook_mode,
    main,
)
from .errors import (
    _ERROR_CONTEXT_TEXT_LEN,
    _asyncio_report_tasks,
    _error_handler,
    _make_asyncio_exc_handler,
)
from .lifecycle import (
    _HANDLER_GROUP_CACHE,
    _HANDLER_GROUP_RATE_LIMITER,
    _LINK_PREVIEW_DISABLED,
    _UPDATES_POOL_SIZE,
    _WEBHOOK_PATH,
    _build_application,
    _post_init,
    _post_shutdown,
    _register_handlers,
    _warm_hot_caches,
)
from .members import _member_cache_tasks, _startup_tasks, _update_member_cache

__all__ = [
    "_ERROR_CONTEXT_TEXT_LEN",
    "_FATAL_BORDER_WIDTH",
    "_FATAL_RED",
    "_FATAL_RESET",
    "_HANDLER_GROUP_CACHE",
    "_HANDLER_GROUP_RATE_LIMITER",
    "_LINK_PREVIEW_DISABLED",
    "_UPDATES_POOL_SIZE",
    "_WEBHOOK_PATH",
    "_asyncio_report_tasks",
    "_build_application",
    "_error_handler",
    "_make_asyncio_exc_handler",
    "_member_cache_tasks",
    "_post_init",
    "_post_shutdown",
    "_print_fatal",
    "_register_handlers",
    "_run_webhook_mode",
    "_startup_tasks",
    "_update_member_cache",
    "_warm_hot_caches",
    "main",
]
