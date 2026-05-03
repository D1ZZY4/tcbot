# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Entry point – initialise DB, register all module handlers, start polling."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, filters

from tcbot import cfg
from tcbot import database as db
from tcbot.modules import get_handlers
from tcbot.utils.logger import setup as setup_logging

log = logging.getLogger(__name__)


async def _update_member_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cache sender's info on every message sent in any affiliated group."""
    chat = update.effective_chat
    user = update.effective_user

    if not user or user.is_bot:
        return
    if not chat or chat.type not in ("group", "supergroup"):
        return

    if not await db.groups_db.is_affiliated(chat.id):
        return

    try:
        await db.users_db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    except Exception as exc:
        log.debug("Member cache update failed for %d: %s", user.id, exc)


async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception for update %s: %s", update, ctx.error, exc_info=ctx.error)


async def _post_init(app: Application) -> None:
    from tcbot.database.mongos import connect
    from tcbot.database.admins_db import ensure_initial_owner

    await connect()
    await ensure_initial_owner(cfg.initial_owner_id)
    log.info("Bot initialised. Owner: %d", cfg.initial_owner_id)


def main() -> None:
    setup_logging()
    log.info("Starting %s bot...", cfg.community_name)

    from tcbot.alive import start_keepalive
    start_keepalive()

    app: Application = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .post_init(_post_init)
        .build()
    )

    ## Register all module handlers via tcbot.modules
    for handler in get_handlers():
        app.add_handler(handler)

    ## Low-priority handler: update member cache on every group message
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            _update_member_cache,
        ),
        group=10,
    )

    ## Global error handler
    app.add_error_handler(_error_handler)

    log.info("Handlers registered. Starting polling...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
