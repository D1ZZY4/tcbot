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
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    ContextTypes,
    Defaults,
    TypeHandler,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.alive import start_keepalive
from tcbot.database import redis_client
from tcbot.database import scheduler as sched_mod
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
# * Raised for Replit: first getMe() response can take >15s on this network.
_HTTP_READ_TIMEOUT: int = 60
_HTTP_WRITE_TIMEOUT: int = 30
_HTTP_CONNECT_TIMEOUT: int = 30
_HTTP_POOL_TIMEOUT: int = 15

# * Connection pool sizes for the underlying httpx client.
_API_POOL_SIZE: int = 8
_UPDATES_POOL_SIZE: int = 4

# * Maximum number of characters captured from a message in error-handler context.
_ERROR_CONTEXT_TEXT_LEN: int = 120

# * Applied globally via Defaults so every bot message suppresses link preview cards.
_LINK_PREVIEW_DISABLED: LinkPreviewOptions = LinkPreviewOptions(is_disabled=True)

# * Width of the fatal-error border printed to stderr.
_FATAL_BORDER_WIDTH: int = 70

# * PTB handler group IDs: lower number = higher priority.
_HANDLER_GROUP_RATE_LIMITER: int = -1
_HANDLER_GROUP_CACHE: int = 10

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
# * Only writes to MongoDB when identity data has changed (name/username differs
# * from the L1 cache), keeping the hot-path near-zero-cost on cache hits.

# * Strong references to in-flight member-cache background tasks; prevents GC.
_member_cache_tasks: set[asyncio.Task[None]] = set()

# * Strong reference to the one-shot startup cache warm-up task; prevents GC.
_startup_tasks: set[asyncio.Task[None]] = set()


async def _update_member_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cache the effective_user from any update; bot-issued events are skipped.

    Uses ``upsert_user_if_changed`` so the L1 mention cache is consulted first.
    When identity data matches the cached entry no DB write is issued, making
    the fast path sub-microsecond.  When a write is needed it is fire-and-forget
    so this handler never blocks the downstream handler chain.
    """
    user = update.effective_user
    if not user or user.is_bot:
        return
    if not user.first_name:
        return

    uid = user.id
    uname = user.username
    fname = user.first_name
    lname = user.last_name

    async def _do_cache() -> None:
        try:
            await db.users_cache.upsert_user_if_changed(uid, uname, fname, lname)
        except Exception as exc:
            log.debug("Member cache update failed for %d: %s", uid, exc)

    try:
        task = asyncio.get_running_loop().create_task(_do_cache())
        _member_cache_tasks.add(task)
        task.add_done_callback(_member_cache_tasks.discard)
    except RuntimeError:
        pass


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


async def _warm_hot_caches() -> None:
    """Pre-warm frequently-read L1+L2 caches immediately after startup.

    Step 1 (parallel): get_owner_id + active_groups — both are TwoLevelCache-backed
    so the first command handler gets an L1 hit instead of a cold MongoDB round-trip.

    Step 2 (sequential dep): get_effective_role(owner_id) — requires owner_id from
    step 1 and populates the effective_role_cache (L1+L2) for the owner so the first
    command from the owner resolves the role without any DB round-trip.
    """
    try:
        owner_id_r, _ = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.groups_db.active_groups(),
            return_exceptions=True,
        )
        log.debug("Cache warm-up: owner_id and active_groups pre-loaded into L1+L2.")
        if isinstance(owner_id_r, int):
            await db.users_roles.get_effective_role(owner_id_r)
            log.debug("Cache warm-up: owner effective_role pre-loaded into L1+L2.")
    except Exception as exc:
        log.debug("Cache warm-up failed (non-fatal): %s", exc)


async def _post_init(app: Application) -> None:
    """Connect to MongoDB, ensure indexes, seed owner, start scheduler, and attach error reporter."""
    log.info("post_init: connecting to MongoDB...")
    await connect()

    # * Run index creation, owner seeding, and Redis connect in parallel.
    # * All three are safe to run concurrently once the MongoDB client is live.
    log.info("post_init: parallel setup (indexes, owner seed, Redis)...")

    async def _try_redis() -> None:
        if cfg.redis_url:
            try:
                await redis_client.connect(cfg.redis_url)
            except Exception as exc:
                log.warning(
                    "Redis connection failed; running with in-memory cache only: %s",
                    exc,
                )
        else:
            log.info("REDIS_URL not set; in-memory cache only.")

    indexes_r, owner_r, _ = await asyncio.gather(
        ensure_indexes(),
        db.users_roles.ensure_initial_owner(cfg.initial_owner_id),
        _try_redis(),
        return_exceptions=True,
    )
    if isinstance(indexes_r, BaseException):
        raise indexes_r
    if isinstance(owner_r, BaseException):
        log.warning("ensure_initial_owner failed (non-fatal): %s", owner_r)

    # * APScheduler 4 with MongoDBDataStore - persistent scheduled moderation jobs.
    await sched_mod.start(cfg.mongodb_uri, cfg.db_name, cfg.warn_expiry_days)

    # * Pre-warm hot caches (owner ID + active groups) as a background task so
    # * the first real user command hits L1 instead of going all the way to MongoDB.
    # * Strong reference in _startup_tasks prevents GC before completion (RUF006).
    loop = asyncio.get_running_loop()
    _t = loop.create_task(_warm_hot_caches(), name="tcbot.cache_warmup")
    _startup_tasks.add(_t)
    _t.add_done_callback(_startup_tasks.discard)

    # * Attach live bot to the error reporter (enables Layers 1 + 3)
    # * Owner ID is passed so infra-level errors (Conflict, InvalidToken)
    # * go to the owner's DM instead of the shared logs_errors channel.
    lec, let = cfg.logs_errors
    error_reporter.attach(app.bot, lec, let, owner_id=cfg.initial_owner_id)

    # * Register asyncio-level exception handler (Layer 3)
    loop.set_exception_handler(_make_asyncio_exc_handler(loop))

    log.info("Bot initialised.")
    # * Internal IDs go to DEBUG so they do not appear in default INFO logs.
    log.debug("Owner: %d | LOG_ERRORS: %d", cfg.initial_owner_id, lec)


async def _post_shutdown(app: Application) -> None:
    """Stop APScheduler and close Redis after the application fully shuts down."""
    await asyncio.gather(sched_mod.stop(), redis_client.close(), return_exceptions=True)


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
            .post_shutdown(_post_shutdown)
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
            # * Global Telegram API pacing: ~30 req/s with automatic 429/RetryAfter
            # * backoff.  Works alongside fan_out's semaphore (max 10 concurrent) and
            # * the per-user decorator rate limiter (group -1).
            .rate_limiter(AIORateLimiter())
            .build()
        )

        # * Layer 1: Global per-user rate limiter - runs before every handler (group -1)
        stage = "handler registration"
        app.add_handler(
            TypeHandler(Update, global_rate_limit_handler),
            group=_HANDLER_GROUP_RATE_LIMITER,
        )

        # * Register all module handlers via tcbot.modules
        for handler in get_handlers():
            app.add_handler(handler)

        # * Low-priority handler: cache every effective_user we observe.
        # * Runs on every update (messages, callback queries, my_chat_member)
        # * so future log messages and mention links resolve to real names.
        app.add_handler(
            TypeHandler(Update, _update_member_cache), group=_HANDLER_GROUP_CACHE
        )

        # * Layer 2: PTB global error handler - catches all unhandled handler exceptions
        app.add_error_handler(_error_handler)

        log.info("Handlers registered. Starting polling...")
        stage = "polling"
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
            bootstrap_retries=-1,
        )
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
