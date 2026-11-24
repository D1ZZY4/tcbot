# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Edits that finalise an appeal post after its review cards are placed."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot.modules.helper.messages import safe_edit_message
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.types import Message

log = get_logger(__name__)


async def edit_instruction(
    bot: Client, chat_id: int, message_id: int, locale: str | None
) -> None:
    """Mark the instruction message as submitted, tolerating a dead message."""
    try:
        await safe_edit_message(
            bot,
            chat_id,
            message_id,
            t("appeals.submit.submitted", locale, plain=True),
            reply_markup=None,
            parse_mode=None,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Appeal submitted-edit failed for message %d: %s", message_id, exc)


async def report_delivery_failure(
    bot: Client,
    msg: Message,
    locale: str | None,
    *,
    instruction_message_id: int,
    instruction_chat_id: int,
    orphan_review_id: int | None,
    appeal_chat: int,
) -> None:
    """Remove an orphan card and tell the user the submission did not land."""
    if orphan_review_id:
        try:
            await bot.delete_messages(appeal_chat, orphan_review_id)
        except Exception as exc:
            log.debug("submit_appeal orphan APPEALS delete failed: %s", exc)
    if instruction_message_id and instruction_chat_id:
        try:
            await safe_edit_message(
                bot,
                instruction_chat_id,
                instruction_message_id,
                t("appeals.submit.delivery_failed", locale, plain=True),
                parse_mode=None,
            )
        except Exception as exc:
            log.debug("submit_appeal delivery-failed reply failed: %s", exc)
