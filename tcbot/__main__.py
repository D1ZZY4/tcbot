# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Bot entry point: initialises the PTB application and starts long-polling."""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
import warnings
from typing import TYPE_CHECKING

from telegram import LinkPreviewOptions, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    Defaults,
    TypeHandler,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.alive import start_keepalive
from tcbot.database.mongos import connect, ensure_indexes
from tcbot.modules import get_handlers
from tcbot.modules.helper.decorators import global_rate_limit_handler
from tcbot.utils import error_reporter
from tcbot.utils.logger import setup as setup_logging

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

# ─────────────────────── Application constants ──────────────────── #

# * HTTP timeout values for the PTB ApplicationBuilder (seconds).
_HTTP_READ_TIMEOUT: int = 15
_HTTP_WRITE_TIMEOUT: int = 15
_HTTP_CONNECT_TIMEOUT: int = 10
_HTTP_POOL_TIMEOUT: int = 5

# * Connection pool sizes for the underlying httpx client.
_API_POOL_SIZE: int = 8
_UPDATES_POOL_SIZE: int = 4

# * Maximum number of characters captured from a message in error-handler context.
_ERROR_CONTEXT_TEXT_LEN: int = 120

# * Applied globally via Defaults so every bot message suppresses link preview cards.
_LINK_PREVIEW_DISABLED: LinkPreviewOptions = LinkPreviewOptions(is_disabled=True)

# * Width of the fatal-error border printed to stderr.
_FATAL_BORDER_WIDTH: int = 70

# * PTB emits a UserWarning about per_message=False + CallbackQueryHandler when
# * ConversationHandlers are built. Our flows deliberately use per_message=False
# * because approval callbacks must be matchable across multiple messages. The
# * warning is accurate but the behaviour is intentional, so we suppress it here
# * rather than at every call site.
warnings.filterwarnings(
    "ignore",
    message=r"If 'per_message=False', 'CallbackQueryHandler'.*",
    category=UserWarning,
)


# ────────────────── Member Cache Update (layer 1) ───────────────── #
# * Caches the effective_user from every update so log messages and mention
# * links resolve to real names instead of falling back to numeric IDs.


async def _update_member_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cache the effective_user from any update; bot-issued events are skipped."""
    user = update.effective_user
    if not user or user.is_bot:
        return
    if not user.first_name:
        return
    try:
        await db.users_cache.upsert_user(
            user.id, user.username, user.first_name, user.last_name
        )
    except Exception as exc:
        log.debug("Member cache update failed for %d: %s", user.id, exc)


# ─────────────────── PTB Error Handler (Layer 2) ────────────────── #
# * Catches all unhandled exceptions from Telegram Bot API handlers
# * Layer 2 of 3 error handling system - reports to logs_errors channel


async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch all unhandled PTB handler exceptions and report them to the logs-errors channel."""
    exc = ctx.error
    if exc is None:
        return

    # * Build context string from the update for extra detail
    context_parts: list[str] = []
    if isinstance(update, Update):
        if update.effective_user:
            u = update.effective_user
            context_parts.append(f"User: {u.first_name} ({u.id})")
        if update.effective_chat:
            c = update.effective_chat
            context_parts.append(f"Chat: {c.title or 'DM'} ({c.id})")
        if update.effective_message and update.effective_message.text:
            context_parts.append(
                f"Text: {update.effective_message.text[:_ERROR_CONTEXT_TEXT_LEN]}"
            )
        elif update.callback_query:
            context_parts.append(f"CBQ data: {update.callback_query.data}")

    context_str = " | ".join(context_parts) if context_parts else None

    # * Log to console as well (existing behaviour)
    log.error(
        "Unhandled exception for update %s",
        update,
        exc_info=exc,
    )

    # * Ship to LOG_ERRORS (non-blocking)
    await error_reporter.report_exc(exc, context=context_str)


# ─────────────── Asyncio Exception Handler (Layer3) ─────────────── #
# * Catches unhandled asyncio exceptions from background tasks
# * Layer 3 of 3 error handling system - last line of defense for errors

# * Strong references to in-flight async error-report tasks. Without this, the
# * fire-and-forget task scheduled in the handler below can be garbage collected
# * before it runs, silently dropping the report (mirrors logger._tg_tasks).
_asyncio_report_tasks: set[asyncio.Task[None]] = set()


def _make_asyncio_exc_handler(
    loop: asyncio.AbstractEventLoop,
) -> Callable[[asyncio.AbstractEventLoop, dict], None]:
    """Return a synchronous asyncio exception handler that mirrors errors to the error reporter."""

    def handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
        """Forward asyncio exceptions to the error reporter and module logger."""
        exc = context.get("exception")
        msg = context.get("message", "Unhandled asyncio exception")
        future = context.get("future") or context.get("task")
        detail = f"{msg} | Task: {future!r}" if future else msg

        # * Mirror to module logger so nothing is silently swallowed.
        log.error("[asyncio] %s%s", detail, f" - {exc}" if exc else "")

        # * Schedule async report on the running loop, keeping a strong reference
        # * until the task completes so it cannot be garbage collected mid-flight.
        try:
            task = lp.create_task(
                error_reporter.report_exc(exc or RuntimeError(detail), context=detail)
            )
            _asyncio_report_tasks.add(task)
            task.add_done_callback(_asyncio_report_tasks.discard)
        except Exception as err:
            log.debug("Failed to schedule async error report: %s", err)

    return handler


# ───────────────────────── Post-Init Setup ──────────────────────── #
# * Runs after PTB Application is built but before polling starts
# * Initializes database connections and all core bot systems


async def _post_init(app: Application) -> None:
    """Connect to MongoDB, ensure indexes, seed owner, and attach the error reporter."""
    log.info("post_init: connecting to MongoDB...")
    await connect()
    log.info("post_init: ensuring indexes...")
    await ensure_indexes()
    log.info("post_init: ensuring initial owner...")
    await db.users_roles.ensure_initial_owner(cfg.initial_owner_id)

    # * Attach live bot to the error reporter (enables Layers 1 + 3)
    lec, let = cfg.logs_errors
    error_reporter.attach(app.bot, lec, let)

    # * Register asyncio-level exception handler (Layer 3)
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_make_asyncio_exc_handler(loop))

    log.info("Bot initialised.")
    # * Internal IDs go to DEBUG so they do not appear in default INFO logs.
    log.debug("Owner: %d | LOG_ERRORS: %d", cfg.initial_owner_id, lec)


# ──────────────────────── Main Entry Point ──────────────────────── #
# * The main function that starts the entire bot application
# * Configures PTB Application and registers all handlers


def _print_fatal(stage: str, exc: BaseException) -> None:
    """Print a fatal startup error with stage label and full traceback to stderr."""
    border = "═" * _FATAL_BORDER_WIDTH
    print(f"\n{border}", file=sys.stderr)
    print(f" FATAL STARTUP ERROR in stage: {stage}", file=sys.stderr)
    print(f" {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"{border}", file=sys.stderr)
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    print(border, file=sys.stderr)


def main() -> None:
    """Configure and start the PTB application with long-polling."""
    # * Each stage is wrapped so any failure prints a clear stage + traceback before exit.
    stage = "logging setup"
    try:
        setup_logging(level=cfg.log_level)
        log.info("Starting %s bot...", cfg.community_name)

        stage = "keepalive server"
        start_keepalive()

        stage = "PTB application build"
        app: Application = (
            ApplicationBuilder()
            .token(cfg.bot_token)
            .post_init(_post_init)
            # * Disable link preview on all bot messages globally.
            .defaults(Defaults(link_preview_options=_LINK_PREVIEW_DISABLED))
            # * Process independent updates in parallel (big latency win)
            .concurrent_updates(True)  # noqa: FBT003
            # * Connection pools - API calls and dedicated getUpdates polling lane
            .connection_pool_size(_API_POOL_SIZE)
            .get_updates_connection_pool_size(_UPDATES_POOL_SIZE)
            # * HTTP timeouts - generous but bounded so hangs never block the loop
            .read_timeout(_HTTP_READ_TIMEOUT)
            .write_timeout(_HTTP_WRITE_TIMEOUT)
            .connect_timeout(_HTTP_CONNECT_TIMEOUT)
            .pool_timeout(_HTTP_POOL_TIMEOUT)
            .build()
        )

        # * Layer 1: Global per-user rate limiter - runs before every handler (group -1)
        stage = "handler registration"
        app.add_handler(TypeHandler(Update, global_rate_limit_handler), group=-1)

        # * Register all module handlers via tcbot.modules
        for handler in get_handlers():
            app.add_handler(handler)

        # * Low-priority handler: cache every effective_user we observe.
        # * Runs on every update (messages, callback queries, my_chat_member)
        # * so future log messages and mention links resolve to real names.
        app.add_handler(TypeHandler(Update, _update_member_cache), group=10)

        # * Layer 2: PTB global error handler - catches all unhandled handler exceptions
        app.add_error_handler(_error_handler)

        log.info("Handlers registered. Starting polling...")
        stage = "polling"
        app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    except SystemExit:
        # * Module discovery uses SystemExit on failure; logging already reported the cause.
        raise
    except KeyboardInterrupt:
        log.info("Shutdown requested (KeyboardInterrupt).")
    except BaseException as exc:
        _print_fatal(stage, exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
