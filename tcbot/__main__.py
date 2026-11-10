# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bot entry point: lifecycle, errors, and main startup."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
import traceback
import warnings
from typing import TYPE_CHECKING

import telegram.error as te
from pymongo.errors import ConnectionFailure
from telegram import Bot, LinkPreviewOptions, Update
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    ContextTypes,
    Defaults,
    TypeHandler,
)

from tcbot import cfg, error_reporter
from tcbot import database as db
from tcbot.alive import register_webhook, start_keepalive
from tcbot.database import mtproto as mtproto_mod
from tcbot.database import redis_client
from tcbot.database import scheduler as sched_mod
from tcbot.database.cache import drain_redis_mutations
from tcbot.database.mongos import close as close_mongo
from tcbot.database.mongos import connect, ensure_indexes
from tcbot.modules import get_handlers
from tcbot.modules.helper.decorators import global_rate_limit_handler
from tcbot.modules.helper.pipelines.connected_flow import drain_harvest_tasks
from tcbot.modules.sync import run_ban_sync
from tcbot.utils import logger as logger_mod
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.dispatch import drain_tasks, throw_if_cancelled
from tcbot.utils.i18n import _ensure_loaded
from tcbot.utils.logger import get_logger
from tcbot.utils.logger import setup as setup_logging
from tcbot.utils.transport import (
    API_POOL_SIZE,
    HTTP_CONNECT_TIMEOUT,
    HTTP_POOL_TIMEOUT,
    HTTP_READ_TIMEOUT,
    HTTP_WRITE_TIMEOUT,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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

# ─────────────────────────────── Constants ───────────────────────────────── #

_UPDATES_POOL_SIZE: int = 4
_LINK_PREVIEW_DISABLED: LinkPreviewOptions = LinkPreviewOptions(is_disabled=True)
_HANDLER_GROUP_RATE_LIMITER: int = -1
_HANDLER_GROUP_CACHE: int = 10
_WEBHOOK_PATH: str = "/webhook"
_FATAL_BORDER_WIDTH: int = 70
_FATAL_RED: str = "\033[38;5;203m"
_FATAL_RESET: str = "\033[0m"
_ERROR_CONTEXT_TEXT_LEN: int = 120
_member_cache_tasks: set[asyncio.Task[None]] = set()
_startup_tasks: set[asyncio.Task[None]] = set()
_asyncio_report_tasks: set[asyncio.Task[None]] = set()
_MEMBER_CACHE_MAX_CONCURRENT: int = 20

warnings.filterwarnings(
    "ignore",
    message=r"If 'per_message=False', 'CallbackQueryHandler'.*",
    category=UserWarning,
)


# ───────────────────────────── Member cache ────────────────────────────── #


async def _update_member_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cache the effective_user of every update; skip bots and empty names."""
    user = update.effective_user
    if not user or user.is_bot or not user.first_name:
        return
    uid, uname, fname, lname = user.id, user.username, user.first_name, user.last_name

    async def _do_cache() -> None:
        try:
            await db.users_cache.harvest_user_identity(uid, uname, fname, lname)
        except Exception as exc:
            log.debug("Member cache update failed for %d: %s", uid, exc)

    if len(_member_cache_tasks) >= _MEMBER_CACHE_MAX_CONCURRENT:
        return
    try:
        task = asyncio.get_running_loop().create_task(_do_cache())
        _member_cache_tasks.add(task)
        task.add_done_callback(_member_cache_tasks.discard)
    except RuntimeError:
        log.debug("Member cache warmup skipped: no running event loop.")


# ──────────────────────────── Error layers ─────────────────────────────── #


async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Report unhandled PTB handler exceptions to LOG_ERRORS."""
    exc = ctx.error
    if exc is None:
        return
    if isinstance(exc, (ConnectionFailure, CircuitOpenError)):
        log.warning("Handler aborted: %s", exc)
        return
    if isinstance(exc, (te.NetworkError, te.TimedOut, te.RetryAfter)):
        log.warning("Transient Telegram error (not reported): %s", exc)
        return
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        log.warning("Transient network error (not reported): %s", exc)
        return
    try:
        if error_reporter._benign(exc):
            return
    except Exception as check_exc:
        log.debug("benign check failed, treating as reportable: %s", check_exc)
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
    context_str = (
        error_reporter.scrub_text(" | ".join(context_parts)) if context_parts else None
    )
    update_id = update.update_id if isinstance(update, Update) else "?"
    log.error(
        "Unhandled exception for update %s%s",
        update_id,
        f" | {context_str}" if context_str else "",
        exc_info=exc,
    )
    await error_reporter.report_exc(exc, context=context_str)


def _make_asyncio_exc_handler(
    loop: asyncio.AbstractEventLoop,
) -> Callable[[asyncio.AbstractEventLoop, dict], None]:
    """Return an asyncio exception handler mirroring errors to the reporter."""

    def handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
        """Forward asyncio exceptions to the error reporter."""
        exc = context.get("exception")
        msg = context.get("message", "Unhandled asyncio exception")
        future = context.get("future") or context.get("task")
        if exc is None and future is not None:
            try:
                done = future.done()
            except Exception:
                done = False
            if done:
                try:
                    cancelled = future.cancelled()
                except Exception:
                    cancelled = False
                if cancelled:
                    log.debug("[asyncio] benign (not reported): cancelled task")
                    return
                extracted: BaseException | None = None
                try:
                    with contextlib.suppress(
                        asyncio.CancelledError, asyncio.InvalidStateError
                    ):
                        extracted = future.exception()
                except Exception:
                    extracted = None
                if extracted is not None:
                    exc = extracted
                    log.debug("[asyncio] recovered task exception: %s", exc)
        detail = (
            f"{msg} | Exception: {exc!r} | Task: {future!r}"
            if exc is not None and future is not None
            else (f"{msg} | Task: {future!r}" if future else msg)
        )
        if isinstance(exc, (te.NetworkError, te.TimedOut, te.RetryAfter)):
            log.debug("[asyncio] transient (not reported): %s", exc)
            return
        if isinstance(exc, (ConnectionFailure, CircuitOpenError)):
            log.debug("[asyncio] transient (not reported): %s", exc)
            return
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            log.debug("[asyncio] transient (not reported): %s", exc)
            return
        if exc is not None and error_reporter._benign(exc):
            log.debug("[asyncio] benign (not reported): %s", exc)
            return
        log.error("[asyncio] %s%s", detail, f" - {exc}" if exc else "")
        if exc is not None and (
            mtproto_mod.is_auth_key_duplicated(exc)
            or mtproto_mod.is_auth_key_not_found(exc)
        ):
            if mtproto_mod.is_auth_dead():
                log.debug("[asyncio] dead MTProto auth key suppressed.")
                return
            try:
                park = lp.create_task(mtproto_mod.handle_auth_failure())
                _asyncio_report_tasks.add(park)
                park.add_done_callback(_asyncio_report_tasks.discard)
            except Exception as err:
                log.debug("Failed to schedule MTProto park task: %s", err)
        try:
            task = lp.create_task(
                error_reporter.report_exc(exc or RuntimeError(detail), context=detail)
            )
            _asyncio_report_tasks.add(task)
            task.add_done_callback(_asyncio_report_tasks.discard)
        except Exception as err:
            log.debug("Failed to schedule async error report: %s", err)

    return handler


# ─────────────────────────────── Lifecycle ─────────────────────────────── #


async def _warm_hot_caches() -> None:
    """Pre-warm owner ID, active groups, and owner role caches."""
    try:
        owner_id_r, groups_r = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.groups_db.active_groups(),
            return_exceptions=True,
        )
        throw_if_cancelled((owner_id_r, groups_r))
        if isinstance(groups_r, BaseException):
            log.debug("Cache warm-up: active_groups failed (non-fatal): %s", groups_r)
        if isinstance(owner_id_r, int):
            await db.users_roles.get_effective_role(owner_id_r)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Cache warm-up failed (non-fatal): %s", exc)


async def init_shared_subsystems(bot: Bot, *, start_mtproto: bool) -> None:
    """Connect MongoDB/Redis and attach the error reporter (both transports)."""
    _ensure_loaded()
    log.info("Connecting to MongoDB...")
    await connect()
    log.info("Running parallel setup (indexes, owner seed, Redis)...")
    if start_mtproto:
        indexes_r, owner_r, _, _mtproto_r = await asyncio.gather(
            ensure_indexes(),
            db.users_roles.ensure_initial_owner(cfg.initial_owner_id),
            redis_client.connect_if_configured(),
            mtproto_mod.start(),
            return_exceptions=True,
        )
    else:
        indexes_r, owner_r, _ = await asyncio.gather(
            ensure_indexes(),
            db.users_roles.ensure_initial_owner(cfg.initial_owner_id),
            redis_client.connect_if_configured(),
            return_exceptions=True,
        )
        _mtproto_r = True
    throw_if_cancelled((indexes_r, owner_r, _mtproto_r))
    if isinstance(indexes_r, BaseException):
        raise indexes_r
    if isinstance(owner_r, BaseException):
        log.warning("ensure_initial_owner failed (non-fatal): %s", owner_r)
    if start_mtproto:
        if isinstance(_mtproto_r, BaseException):
            raise _mtproto_r
        if _mtproto_r is False:
            log.warning(
                "MTProto degraded: another live instance owns the shared "
                "session. Identity lookups run Bot-API-only."
            )
    lec, let = cfg.logs_errors
    error_reporter.attach(bot, lec, let, owner_id=cfg.initial_owner_id)


async def _post_init(app: Application) -> None:
    """Connect subsystems and start the scheduler."""
    if not cfg.mtproto_enabled:
        raise RuntimeError(
            "API_ID/API_HASH are required for MTProto identity resolution; refusing to boot degraded."
        )
    await init_shared_subsystems(app.bot, start_mtproto=True)
    await sched_mod.start(
        cfg.mongodb_uri,
        cfg.db_name,
        cfg.warn_expiry_days,
        bot=app.bot,
        sync_interval_hours=cfg.sync_interval_hours,
        sync_runner=run_ban_sync,
    )
    loop = asyncio.get_running_loop()
    _t = loop.create_task(_warm_hot_caches(), name="tcbot.cache_warmup")
    _startup_tasks.add(_t)
    _t.add_done_callback(_startup_tasks.discard)
    loop.set_exception_handler(_make_asyncio_exc_handler(loop))
    lec, _ = cfg.logs_errors
    log.info("Bot initialised.")
    log.debug("Owner: %d | LOG_ERRORS: %d", cfg.initial_owner_id, lec)


async def _post_shutdown(app: Application) -> None:
    """Drain tasks, stop the scheduler, and close clients."""
    await drain_tasks(_member_cache_tasks, label="member cache")
    await drain_tasks(_startup_tasks, label="startup warm-up")
    await drain_tasks(_asyncio_report_tasks, label="async error reports")
    await drain_harvest_tasks()
    await logger_mod.drain_pending()
    await drain_redis_mutations()
    shutdown_results = await asyncio.gather(
        sched_mod.stop(),
        redis_client.close(),
        mtproto_mod.stop(),
        return_exceptions=True,
    )
    for _result in shutdown_results:
        if isinstance(_result, BaseException) and not isinstance(
            _result, asyncio.CancelledError
        ):
            log.warning("Shutdown step failed (non-fatal): %s", _result)
    throw_if_cancelled(shutdown_results)
    close_mongo()


def base_builder() -> ApplicationBuilder:
    """Return the shared PTB ApplicationBuilder chain for every transport."""
    return (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .defaults(Defaults(link_preview_options=_LINK_PREVIEW_DISABLED))
        .concurrent_updates(True)  # noqa: FBT003
        .connection_pool_size(API_POOL_SIZE)
        .read_timeout(HTTP_READ_TIMEOUT)
        .write_timeout(HTTP_WRITE_TIMEOUT)
        .connect_timeout(HTTP_CONNECT_TIMEOUT)
        .pool_timeout(HTTP_POOL_TIMEOUT)
        .rate_limiter(AIORateLimiter())
    )


def build_application(*, polling: bool) -> Application:
    """Construct the PTB Application with transport-appropriate pools."""
    builder = base_builder().post_init(_post_init).post_shutdown(_post_shutdown)
    if polling:
        builder = builder.get_updates_connection_pool_size(_UPDATES_POOL_SIZE)
    return builder.build()


def register_handlers(app: Application) -> None:
    """Attach the rate limiter, module handlers, cache harvester, and error handler."""
    app.add_handler(
        TypeHandler(Update, global_rate_limit_handler),
        group=_HANDLER_GROUP_RATE_LIMITER,
    )
    for handler in get_handlers():
        app.add_handler(handler)
    app.add_handler(
        TypeHandler(Update, _update_member_cache), group=_HANDLER_GROUP_CACHE
    )
    app.add_error_handler(_error_handler)


# ─────────────────────────────── Entry point ───────────────────────────── #


async def _run_webhook_mode(app: Application) -> None:
    """Run PTB in webhook mode wired to the Flask receiver."""
    full_url = f"{cfg.webhook_url}{_WEBHOOK_PATH}"
    secret = cfg.webhook_secret
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    with contextlib.suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
        loop.add_signal_handler(signal.SIGINT, shutdown_event.set)
    async with app:
        await _post_init(app)
        await app.start()
        try:
            log.info("Registering webhook at %s ...", full_url)
            await app.bot.set_webhook(
                url=full_url,
                secret_token=secret,
                allowed_updates=list(Update.ALL_TYPES),
                drop_pending_updates=True,
            )
            info = await app.bot.get_webhook_info()
            if info.url != full_url:
                raise RuntimeError(
                    f"Webhook URL mismatch after set_webhook: {info.url!r} != {full_url!r}"
                )
            log.info(
                "Webhook active. Pending updates: %d | Max connections: %s",
                info.pending_update_count,
                info.max_connections,
            )
            register_webhook(app.update_queue, loop, secret, app.bot)
            log.info("Bot running in webhook mode. Waiting for updates...")
            await shutdown_event.wait()
        except asyncio.CancelledError:
            log.info("Webhook mode cancelled.")
            raise
        finally:
            log.info("Webhook mode shutting down...")
            try:
                await app.bot.delete_webhook(drop_pending_updates=False)
            except Exception as exc:
                log.debug("delete_webhook failed during shutdown (non-fatal): %s", exc)
            await app.stop()
            await _post_shutdown(app)
    log.info("Bot shutdown complete.")


def _print_fatal(stage: str, exc: BaseException) -> None:
    """Print a fatal startup error with traceback to stderr."""
    border = "=" * _FATAL_BORDER_WIDTH
    print(f"\n{_FATAL_RED}{border}", file=sys.stderr)
    print(f" FATAL STARTUP ERROR in stage: {stage}", file=sys.stderr)
    print(f" {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"{border}", file=sys.stderr)
    tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(f"{_FATAL_RED}{tb_text}{_FATAL_RESET}", file=sys.stderr, end="")
    print(f"{border}{_FATAL_RESET}", file=sys.stderr)


def main() -> None:
    """Configure and start the PTB application in webhook or polling mode."""
    stage = "logging setup"
    try:
        if uvloop is not None:
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        setup_logging(level=cfg.log_level)
        _init_sentry()
        log.info("Starting %s bot...", cfg.community_name)
        stage = "keepalive server"
        start_keepalive()
        stage = "PTB application build"
        use_webhook = cfg.is_webhook_mode
        app: Application = build_application(polling=not use_webhook)
        stage = "handler registration"
        register_handlers(app)
        if use_webhook:
            log.info(
                "Webhook mode detected (URL: %s). Starting webhook transport...",
                cfg.webhook_url,
            )
            stage = "webhook"
            asyncio.run(_run_webhook_mode(app))
        else:
            log.warning(
                "No WEBHOOK_URL or REPLIT_DEV_DOMAIN found. "
                "Falling back to long-polling (local development only)."
            )
            log.info("Starting long-polling...")
            stage = "polling"
            app.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                bootstrap_retries=5,
            )
    except SystemExit:
        raise
    except KeyboardInterrupt:
        log.info("Shutdown requested (KeyboardInterrupt).")
    except BaseException as exc:
        _print_fatal(stage, exc)
        raise SystemExit(1) from exc


def _init_sentry() -> None:
    """Initialise Sentry when a DSN is configured and the extra is installed.

    Opt-in only: an empty ``SENTRY_DSN`` (or a missing observability extra)
    is a silent no-op. Failures to initialise degrade to no monitoring
    instead of blocking startup.
    """
    if not cfg.sentry_dsn or sentry_sdk is None or LoguruIntegration is None:
        return
    try:
        sentry_sdk.init(
            dsn=cfg.sentry_dsn,
            integrations=[LoguruIntegration(level_include="ERROR")],
            traces_sample_rate=0.0,
        )
    except Exception as exc:
        log.warning("Sentry initialisation failed (non-fatal): %s", exc)


__all__ = [
    "_ERROR_CONTEXT_TEXT_LEN",
    "_FATAL_BORDER_WIDTH",
    "_FATAL_RED",
    "_FATAL_RESET",
    "_HANDLER_GROUP_CACHE",
    "_HANDLER_GROUP_RATE_LIMITER",
    "_LINK_PREVIEW_DISABLED",
    "_MEMBER_CACHE_MAX_CONCURRENT",
    "_UPDATES_POOL_SIZE",
    "_WEBHOOK_PATH",
    "_asyncio_report_tasks",
    "_error_handler",
    "_init_sentry",
    "_make_asyncio_exc_handler",
    "_member_cache_tasks",
    "_post_init",
    "_post_shutdown",
    "_print_fatal",
    "_run_webhook_mode",
    "_startup_tasks",
    "_update_member_cache",
    "_warm_hot_caches",
    "base_builder",
    "build_application",
    "init_shared_subsystems",
    "log",
    "main",
    "register_handlers",
]

if __name__ == "__main__":
    main()
