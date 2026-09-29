# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Left-member announcements and chat migration tracking."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


@decorators.log_execution
async def on_left_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Announce when a non-bot member leaves the main or exec group."""
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return

    if not cfg.is_primary_group(chat.id):
        return

    member = msg.left_chat_member
    if member and not member.is_bot:
        await safe_reply(
            msg,
            t(
                "greeting.left.body",
                await locale_for_update(update),
                user=Safe(user_ref(member.id, member.first_name, member.username)),
            ),
            log_label="left-member",
        )


@decorators.log_execution
async def on_chat_migration(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Update group records when a basic group migrates to a supergroup.

    Telegram delivers two status updates on migration:
    - ``migrate_to_chat_id`` in the old basic group (bot may no longer have
      write access at that point, so we only log it).
    - ``migrate_from_chat_id`` in the new supergroup, which carries both IDs;
      this is where we perform the DB update.
    """
    msg = update.effective_message
    if not msg:
        return

    if msg.migrate_from_chat_id:
        old_id = msg.migrate_from_chat_id
        new_id = update.effective_chat.id if update.effective_chat else None
        if old_id and new_id and old_id != new_id:
            (
                migrated,
                _warns_migrated,
                _kicks_migrated,
                _mutes_migrated,
            ) = await asyncio.gather(
                db.groups_db.migrate_group(old_id, new_id),
                db.warns_db.migrate_records(old_id, new_id),
                db.kicks_db.migrate_records(old_id, new_id),
                db.mutes_db.migrate_records(old_id, new_id),
                return_exceptions=True,
            )
            throw_if_cancelled(
                (migrated, _warns_migrated, _kicks_migrated, _mutes_migrated)
            )
            if isinstance(migrated, BaseException):
                log.error(
                    "groups_db.migrate_group failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    migrated,
                )
                migrated = False
            if isinstance(_warns_migrated, BaseException):
                log.error(
                    "warns_db.migrate_records failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    _warns_migrated,
                )
            if isinstance(_kicks_migrated, BaseException):
                log.error(
                    "kicks_db.migrate_records failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    _kicks_migrated,
                )
            if isinstance(_mutes_migrated, BaseException):
                log.error(
                    "mutes_db.migrate_records failed for %d -> %d: %s",
                    old_id,
                    new_id,
                    _mutes_migrated,
                )
            if migrated:
                log.info(
                    "Federation group migrated: old_chat_id=%d new_chat_id=%d",
                    old_id,
                    new_id,
                )
            else:
                log.debug(
                    "Chat migration received but group was not in federation: "
                    "old_chat_id=%d new_chat_id=%d",
                    old_id,
                    new_id,
                )
        return

    if msg.migrate_to_chat_id:
        log.info(
            "Chat migrate_to received: chat_id=%d -> %d "
            "(will be recorded via migrate_from in the supergroup)",
            update.effective_chat.id if update.effective_chat else 0,
            msg.migrate_to_chat_id,
        )
