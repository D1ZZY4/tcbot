# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Entry point – initialise DB, register all module handlers, start polling
from __future__ import annotations

import asyncio
import logging
import sys

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, TypeHandler, filters

from tcbot import cfg
from tcbot import database as db
from tcbot.alive import start_keepalive
from tcbot.database.admins_db import ensure_initial_owner
from tcbot.database.mongos import connect, ensure_indexes
from tcbot.modules import get_handlers
from tcbot.modules.helper.decorators import global_rate_limit_handler
from tcbot.utils import error_reporter
from tcbot.utils.prefixes import ANY_CMD_FILTER
from tcbot.utils.logger import setup as setup_logging

log = logging.getLogger(__name__)


## ── member cache ───────────────────────────────────────────────────────────

async def _update_member_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cache sender's info on every message sent in any connected group."""
    chat = update.effective_chat
    user = update.effective_user

    if not user or user.is_bot:
        return
    if not chat or chat.type not in ("group", "supergroup"):
        return

    if not await db.groups_db.is_connected(chat.id):
        return

    try:
        await db.users_db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    except Exception as exc:
        log.debug("Member cache update failed for %d: %s", user.id, exc)


## ── PTB error handler (Layer 2) ────────────────────────────────────────────

async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch every unhandled exception from any PTB handler and ship it to LOG_ERRORS."""
    exc = ctx.error
    if exc is None:
        return

    ## Build context string from the update for extra detail
    context_parts: list[str] = []
    if isinstance(update, Update):
        if update.effective_user:
            u = update.effective_user
            context_parts.append(f"User: {u.first_name} ({u.id})")
        if update.effective_chat:
            c = update.effective_chat
            context_parts.append(f"Chat: {c.title or 'DM'} ({c.id})")
        if update.effective_message and update.effective_message.text:
            context_parts.append(f"Text: {update.effective_message.text[:120]}")
        elif update.callback_query:
            context_parts.append(f"CBQ data: {update.callback_query.data}")

    context_str = " | ".join(context_parts) if context_parts else None

    ## Log to console as well (existing behaviour)
    log.error(
        "Unhandled exception for update %s",
        update,
        exc_info=exc,
    )

    ## Ship to LOG_ERRORS (non-blocking)
    await error_reporter.report_exc(exc, context=context_str)


## ── asyncio exception handler (Layer 3) ────────────────────────────────────

def _make_asyncio_exc_handler(loop: asyncio.AbstractEventLoop):
    """Return a synchronous asyncio exception handler that schedules a Telegram report."""
    def handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
        exc     = context.get("exception")
        msg     = context.get("message", "Unhandled asyncio exception")
        future  = context.get("future") or context.get("task")
        detail  = f"{msg} | Task: {future!r}" if future else msg

        ## Always mirror to stderr so nothing is silently swallowed
        print(f"[asyncio] {detail}" + (f" — {exc}" if exc else ""), file=sys.stderr)

        ## Schedule async report on the running loop
        try:
            lp.create_task(
                error_reporter.report_exc(exc or RuntimeError(detail), context=detail)
            )
        except Exception:
            pass

    return handler


## ── post-init ──────────────────────────────────────────────────────────────

async def _post_init(app: Application) -> None:
    await connect()
    await ensure_indexes()
    await ensure_initial_owner(cfg.initial_owner_id)

    ## Attach live bot to the error reporter (enables Layers 1 + 3)
    lec, let = cfg.logs_errors
    error_reporter.attach(app.bot, lec, let)

    ## Register asyncio-level exception handler (Layer 3)
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_make_asyncio_exc_handler(loop))

    log.info("Bot initialised. Owner: %d | LOG_ERRORS: %d", cfg.initial_owner_id, lec)


## ── entry point ────────────────────────────────────────────────────────────

def main() -> None:
    setup_logging(level=cfg.log_level)
    log.info("Starting %s bot...", cfg.community_name)

    start_keepalive()

    app: Application = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .post_init(_post_init)
        ## Process independent updates in parallel (big latency win)
        .concurrent_updates(True)
        ## Connection pools — 8 for API calls, 4 dedicated for getUpdates polling
        .connection_pool_size(8)
        .get_updates_connection_pool_size(4)
        ## HTTP timeouts — generous but bounded so hangs never block the loop
        .read_timeout(15)
        .write_timeout(15)
        .connect_timeout(10)
        .pool_timeout(5)
        .build()
    )

    ## Layer 1: Global per-user rate limiter — runs before every handler (group -1)
    app.add_handler(TypeHandler(Update, global_rate_limit_handler), group=-1)

    ## Register all module handlers via tcbot.modules
    for handler in get_handlers():
        app.add_handler(handler)

    ## Low-priority handler: update member cache on every group message.
    ## ~ANY_CMD_FILTER excludes custom-prefix commands (!, .) — /commands pass through.
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~ANY_CMD_FILTER,
            _update_member_cache,
        ),
        group=10,
    )

    ## Layer 2: PTB global error handler — catches all unhandled handler exceptions
    app.add_error_handler(_error_handler)

    log.info("Handlers registered. Starting polling...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
