# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bot entry point: Kurigram polling lifecycle, errors, and startup."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import traceback
from typing import TYPE_CHECKING

from pyrogram import idle
from pyrogram.handlers import (
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberUpdatedHandler,
    ErrorHandler,
    MessageHandler,
)
from pyrogram.types import CallbackQuery, ChatJoinRequest, ChatMemberUpdated, Message

from tcbot import cfg, error_reporter
from tcbot import database as db
from tcbot.alive import start_keepalive
from tcbot.database import engine as db_engine
from tcbot.database import mtproto as mtproto_mod
from tcbot.database import pg_cron, redis_client
from tcbot.database import scheduler as sched_mod
from tcbot.database.cache import drain_redis_mutations
from tcbot.database.engine import close as close_database
from tcbot.database.engine import connect
from tcbot.enforcement_worker import configure as configure_enforcement_worker
from tcbot.enforcement_worker import run as run_enforcement_worker
from tcbot.modules import get_handlers, handler_group
from tcbot.modules.helper.context import bot_identity
from tcbot.modules.helper.extraction import refresh as identity_refresh
from tcbot.modules.helper.handlers import current_ctx, shutdown_dispatcher
from tcbot.modules.helper.pipelines import connect_common
from tcbot.modules.helper.pipelines.ban_actions import drain_proof_sessions
from tcbot.notification_worker import configure as configure_notification_worker
from tcbot.notification_worker import run as run_notification_worker
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import _ensure_loaded
from tcbot.utils.logger import ERROR_LEVEL, get_logger
from tcbot.utils.logger import setup as setup_logging
from tcbot.utils.tasks import TaskTracker

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram import Client

try:  # Optional performance extra: uvloop replaces the asyncio loop on Linux.
    import uvloop  # type: ignore[reportMissingImports]
except ImportError:
    uvloop = None  # type: ignore[assignment]

try:  # Optional observability extra: error monitoring.
    import sentry_sdk  # type: ignore[reportMissingImports]
    from sentry_sdk.integrations.loguru import LoguruIntegration  # type: ignore[reportMissingImports]
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]
    LoguruIntegration = None  # type: ignore[assignment, misc]

log = get_logger(__name__)

# ─────────────────────────────── Constants ─────────────────────────────── #

_HANDLER_GROUP_RATE_LIMITER: int = -1
_HANDLER_GROUP_CACHE: int = 10
# * Last responder: flows release callbacks they do not own with
# * ContinuePropagation. This group acknowledges a tap nobody claimed so no
# * client spinner is left hanging, and it never answers twice.
_HANDLER_GROUP_UNOWNED: int = 20
_FATAL_BORDER_WIDTH: int = 70
_FATAL_RED: str = "\033[38;5;203m"
_FATAL_RESET: str = "\033[0m"
_ERROR_CONTEXT_TEXT_LEN: int = 120
_MEMBER_CACHE_MAX_CONCURRENT: int = 20
_MEMBER_CACHE_DROP_REPORT_EVERY: int = 100

_member_cache_tasks = TaskTracker("member cache")
_startup_tasks = TaskTracker("startup warm-up")
_asyncio_report_tasks = TaskTracker("async error reports")
_member_cache_drops: int = 0


# ───────────────────────────── Member cache ────────────────────────────── #


async def _cache_identity(client: Client, user: object) -> None:
    """Cache the acting user of every update; skip bots and empty names."""
    global _member_cache_drops
    uid = getattr(user, "id", None)
    if not uid or getattr(user, "is_bot", False) or not getattr(user, "first_name", ""):
        return

    async def _do_cache() -> None:
        try:
            await db.users_cache.harvest_user_identity(
                uid,
                getattr(user, "username", None),
                str(getattr(user, "first_name", "") or ""),
                getattr(user, "last_name", None),
            )
        except Exception as exc:
            log.debug("Member cache update failed for %d: %s", uid, exc)

    if _member_cache_tasks.pending >= _MEMBER_CACHE_MAX_CONCURRENT:
        _member_cache_drops += 1
        if _member_cache_drops % _MEMBER_CACHE_DROP_REPORT_EVERY == 0:
            log.warning(
                "Member cache harvest saturated (%d in flight): %d identity "
                "updates dropped since startup.",
                _MEMBER_CACHE_MAX_CONCURRENT,
                _member_cache_drops,
            )
        return
    _member_cache_tasks.spawn(_do_cache())


async def _on_any_update(client: Client, update: object) -> None:
    """Cache identity from a typed Kurigram update that carries a user."""
    if isinstance(update, (Message, CallbackQuery, ChatMemberUpdated, ChatJoinRequest)):
        user = update.from_user
        if user is not None:
            await _cache_identity(client, user)


async def _answer_unowned_callback(_client: Client, query: CallbackQuery) -> None:
    """Acknowledge a callback that no flow claimed, without touching state."""
    try:
        await query.answer()
    except Exception as exc:
        log.debug("Unowned callback answer failed: %s", exc)


# ─────────────────────────────── Error layers ───────────────────────────── #


async def _error_handler(
    client: object,
    exc: BaseException,
    handler: object,
    update: object,
    users: object,
    chats: object,
) -> None:
    """Report unhandled Kurigram handler exceptions to LOG_ERRORS."""
    if db_engine.is_connection_error(exc) or isinstance(exc, CircuitOpenError):
        log.warning("Handler aborted: %s", exc)
        return
    if db_engine.is_pool_timeout(exc):
        log.warning("Database pool saturated (not reported): %s", exc)
        return
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        log.warning("Transient network error (not reported): %s", exc)
        return
    if isinstance(exc, error_reporter.PollingConflictError):
        # * Another instance is polling this bot. It is an operator situation,
        # * not a defect: keep the traceback out of the log and route one
        # * actionable report to the owner.
        log.warning(
            "Telegram refused the poll: another instance is polling this "
            "bot. Stop the other instance or give each one its own token."
        )
        await error_reporter.report_exc(exc)
        return
    if error_reporter._is_benign(exc):
        return
    context_parts: list[str] = []
    ctx = current_ctx()
    user = ctx.effective_user if ctx is not None else None
    chat = ctx.effective_chat if ctx is not None else None
    msg = ctx.effective_message if ctx is not None else None
    query = ctx.callback_query if ctx is not None else None
    is_private = getattr(getattr(chat, "type", None), "value", "") in ("private", "bot")
    if user is not None:
        context_parts.append(
            f"User: {user.first_name}"
            if is_private
            else f"User: {user.first_name} ({user.id})"
        )
    if chat is not None:
        context_parts.append(
            "Chat: DM"
            if is_private
            else f"Chat: {getattr(chat, 'title', None) or 'group'} ({chat.id})"
        )
    if msg is not None and getattr(msg, "text", None) and not is_private:
        context_parts.append(f"Text: {msg.text[:_ERROR_CONTEXT_TEXT_LEN]}")
    if query is not None and query.data:
        context_parts.append(f"CBQ data: {query.data}")
    context_str = (
        error_reporter.scrub_text(" | ".join(context_parts)) if context_parts else None
    )
    await error_reporter.report_exc(exc, context=context_str)
    log.error(
        "Unhandled exception for update %s%s",
        getattr(update, "id", "?"),
        f" | {context_str}" if context_str else "",
        exc_info=exc,
    )


def _make_asyncio_exc_handler() -> Callable[[asyncio.AbstractEventLoop, dict], None]:
    """Return an asyncio exception handler mirroring errors to the reporter."""

    def handler(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        """Forward asyncio exceptions to the error reporter."""
        exc = context.get("exception")
        msg = context.get("message", "Unhandled asyncio exception")
        future = context.get("future") or context.get("task")
        if exc is None and future is not None:
            try:
                if future.done() and not future.cancelled():
                    with contextlib.suppress(
                        asyncio.CancelledError, asyncio.InvalidStateError
                    ):
                        exc = future.exception()
            except Exception:
                exc = None
        detail = (
            f"{msg} | Exception: {exc!r} | Task: {future!r}"
            if exc is not None and future is not None
            else (f"{msg} | Task: {future!r}" if future else msg)
        )
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            log.debug("[asyncio] transient (not reported): %s", exc)
            return
        if exc is not None and (
            db_engine.is_connection_error(exc) or isinstance(exc, CircuitOpenError)
        ):
            log.debug("[asyncio] transient (not reported): %s", exc)
            return
        if exc is not None and db_engine.is_pool_timeout(exc):
            log.debug("[asyncio] pool saturated (not reported): %s", exc)
            return
        if error_reporter._is_benign(exc):
            log.debug("[asyncio] benign (not reported): %s", exc)
            return
        log.error(
            "[asyncio] %s%s",
            detail,
            f" - {exc}" if exc else "",
            exc_info=exc,
        )
        if exc is not None and (
            mtproto_mod.is_auth_key_duplicated(exc)
            or mtproto_mod.is_auth_key_not_found(exc)
            or mtproto_mod.is_session_revoked(exc)
        ):
            if mtproto_mod.is_auth_dead():
                return
            _asyncio_report_tasks.spawn(mtproto_mod.handle_auth_failure())
        if exc is not None:
            _asyncio_report_tasks.spawn(error_reporter.report_exc(exc, context=detail))

    return handler


# ─────────────────────────────── Lifecycle ─────────────────────────────── #


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """Return the uvloop loop factory, or None when the package is absent."""
    return None if uvloop is None else uvloop.new_event_loop


async def _warm_hot_caches() -> None:
    """Pre-warm the caches the first command and callback taps always read.

    A cold locale cache makes the first `/start` pay the Redis and database
    miss chain inside the handler. Warming it at boot moves that latency out
    of the user-visible path.
    """
    try:
        owner_id_r, groups_r, community_r = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.groups_db.active_groups(),
            db.settings_db.get_community_locale(),
            return_exceptions=True,
        )
        throw_if_cancelled((owner_id_r, groups_r, community_r))
        if isinstance(groups_r, BaseException):
            log.debug("Cache warm-up: active_groups failed (non-fatal): %s", groups_r)
        if isinstance(community_r, BaseException):
            log.debug(
                "Cache warm-up: community locale failed (non-fatal): %s", community_r
            )
        if isinstance(owner_id_r, int):
            role_r, locale_r = await asyncio.gather(
                db.users_roles.get_effective_role(owner_id_r),
                db.settings_db.get_user_locale(owner_id_r),
                return_exceptions=True,
            )
            throw_if_cancelled((role_r, locale_r))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Cache warm-up failed (non-fatal): %s", exc)


async def init_shared_subsystems(client: Client) -> None:
    """Connect PostgreSQL/Redis, start MTProto, and attach the error reporter."""
    _ensure_loaded()
    log.info("Connecting to PostgreSQL...")
    await connect()
    log.info("Running parallel setup (owner seed, Redis, MTProto)...")
    destinations_r, owner_r, primary_r, redis_r, mtproto_r = await asyncio.gather(
        db.groups_db.ensure_destinations(
            (
                (cfg.proofs[0], cfg.proofs[1] is not None),
                (cfg.logs[0], cfg.logs[1] is not None),
                (cfg.appeals[0], cfg.appeals[1] is not None),
            )
        ),
        db.users_roles.ensure_initial_owner(cfg.initial_owner_id),
        db.groups_db.ensure_primary_group(cfg.main_group),
        redis_client.connect_if_configured(),
        mtproto_mod.start(),
        return_exceptions=True,
    )
    throw_if_cancelled((destinations_r, owner_r, primary_r, redis_r, mtproto_r))
    if isinstance(destinations_r, BaseException):
        log.warning("Destination registration failed (non-fatal): %s", destinations_r)
    if isinstance(owner_r, BaseException):
        log.warning("ensure_initial_owner failed (non-fatal): %s", owner_r)
    if isinstance(primary_r, BaseException):
        log.warning("Primary group registration failed (non-fatal): %s", primary_r)
    if isinstance(mtproto_r, BaseException):
        raise mtproto_r
    if mtproto_r is False:
        # * Kurigram is the only transport now: without its session this
        # * process cannot receive updates at all, so fail loudly instead of
        # * exiting 0 and looking healthy to a supervisor.
        raise RuntimeError(
            "MTProto session is unavailable (duplicate instance or dead session). "
            "Stop the other instance or repair the session before starting again."
        )
    lec, let = cfg.logs_errors
    error_reporter.attach(client, lec, let, owner_id=cfg.initial_owner_id)
    # * Cache the bot's own identity once, so display names, links, and
    # * self-target checks never pay for a lookup inside an update handler.
    await bot_identity(client)


def register_handlers(client: Client) -> None:
    """Attach the cache harvester, module handlers, and the error handler."""
    for factory in (
        MessageHandler,
        CallbackQueryHandler,
        ChatMemberUpdatedHandler,
        ChatJoinRequestHandler,
    ):
        client.add_handler(factory(_on_any_update), _HANDLER_GROUP_CACHE)
    for handler in get_handlers():
        client.add_handler(handler, handler_group(handler))
    client.add_handler(
        CallbackQueryHandler(_answer_unowned_callback), _HANDLER_GROUP_UNOWNED
    )
    client.add_handler(ErrorHandler(_error_handler))


async def _shutdown_subsystems() -> None:
    """Stop background work and close every external client."""
    await shutdown_dispatcher()
    await sched_mod.stop()
    await _asyncio_report_tasks.drain()
    await identity_refresh.identity_refresh_tasks.drain()
    await connect_common.harvest_tasks.drain()
    await drain_proof_sessions()
    await error_reporter.drain_pending()
    await _member_cache_tasks.drain()
    await _startup_tasks.drain()
    await drain_redis_mutations()
    shutdown_results = await asyncio.gather(
        redis_client.close(),
        mtproto_mod.stop(),
        return_exceptions=True,
    )
    for result in shutdown_results:
        if isinstance(result, BaseException) and not isinstance(
            result, asyncio.CancelledError
        ):
            log.warning("Shutdown step failed (non-fatal): %s", result)
    # ! CRITICAL: The database is the last client to close. A cancellation
    # ! returned by a step above must still reach it before propagating.
    try:
        throw_if_cancelled(shutdown_results)
    finally:
        await close_database()


async def _run_polling() -> None:
    """Run the single Kurigram client through start, idle and shutdown."""
    client = mtproto_mod.client()
    register_handlers(client)
    asyncio.get_running_loop().set_exception_handler(_make_asyncio_exc_handler())
    try:
        await init_shared_subsystems(client)
        configure_enforcement_worker(client)
        configure_notification_worker(client)
        pg_cron_active = await pg_cron.sync_schedules()
        await sched_mod.start(
            cfg.database_url,
            database_jobs_in_pg_cron=pg_cron_active,
            enforcement_job=run_enforcement_worker,
            notification_job=run_notification_worker,
        )
        _startup_tasks.spawn(_warm_hot_caches())
        # * A dropped connection after init would otherwise skip idle(),
        # * return normally and exit 0 while receiving no updates. A
        # * supervisor that restarts on failure would leave the bot down.
        if not client.is_connected:
            raise RuntimeError(
                "Kurigram client disconnected before the polling loop; "
                "refusing to exit successfully without receiving updates."
            )
        log.info("Bot initialised. Running Kurigram polling loop...")
        await idle()
    except asyncio.CancelledError:
        log.info("Polling cancelled.")
        raise
    finally:
        await _shutdown_subsystems()
        log.info("Bot shutdown complete.")


def _print_fatal(stage: str, exc: BaseException) -> None:
    """Print a fatal startup error with traceback to stderr."""
    border = "=" * _FATAL_BORDER_WIDTH
    detail = error_reporter.scrub_text(f"{type(exc).__name__}: {exc}")
    print(f"\n{_FATAL_RED}{border}", file=sys.stderr)
    print(f" FATAL STARTUP ERROR in stage: {stage}", file=sys.stderr)
    print(f" {detail}", file=sys.stderr)
    print(f"{border}", file=sys.stderr)
    tb_text = error_reporter.scrub_text(
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    )
    print(f"{_FATAL_RED}{tb_text}{_FATAL_RESET}", file=sys.stderr, end="")
    print(f"{border}{_FATAL_RESET}", file=sys.stderr)


def main() -> None:
    """Configure and run the Kurigram polling application."""
    stage = "logging setup"
    try:
        setup_logging(level=cfg.log_level)
        _init_sentry()
        log.info("Starting %s bot (Kurigram polling)...", cfg.community_name)
        if not cfg.mtproto_enabled:
            raise RuntimeError(
                "API_ID/API_HASH are required for the Kurigram client; refusing to boot."
            )
        stage = "keepalive server"
        start_keepalive()
        stage = "polling"
        # * asyncio.run ignores a loop installed with set_event_loop; the
        # * factory must be passed so uvloop actually owns the event loop.
        asyncio.run(_run_polling(), loop_factory=loop_factory())
    except KeyboardInterrupt:
        log.info("Shutdown requested (KeyboardInterrupt).")
    except BaseException as exc:
        _print_fatal(stage, exc)
        raise SystemExit(1) from exc


def _init_sentry() -> None:
    """Initialise Sentry when a DSN is configured and the extra is installed."""
    if not cfg.sentry_dsn or sentry_sdk is None or LoguruIntegration is None:
        return
    try:
        sentry_sdk.init(
            dsn=cfg.sentry_dsn,
            integrations=[LoguruIntegration(event_level=ERROR_LEVEL)],
            traces_sample_rate=0.0,
            send_default_pii=False,
            before_send=error_reporter.scrub_sentry_event,
        )
    except Exception as exc:
        log.warning("Sentry initialisation failed (non-fatal): %s", exc)


__all__ = [
    "_answer_unowned_callback",
    "_error_handler",
    "_init_sentry",
    "_make_asyncio_exc_handler",
    "_on_any_update",
    "_print_fatal",
    "_run_polling",
    "_shutdown_subsystems",
    "init_shared_subsystems",
    "log",
    "loop_factory",
    "main",
    "register_handlers",
]

if __name__ == "__main__":
    main()
