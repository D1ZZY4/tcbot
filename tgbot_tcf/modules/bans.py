# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Ban / unban business logic.

The Telegram handler in :mod:`tgbot_tcf.handlers.ban` owns the proof-collection
session lifecycle (timers, album debouncing, ``InputMediaPhoto`` packing).
Everything else — building captions and log text, posting proof to the proof
topic, persisting to the ``bans`` collection, and enforcing across federated
groups — is delegated to the helpers in this module so the handler stays
easy to read and the business rules stay in one place.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from telegram import InputMediaPhoto, InputMediaVideo
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import MAIN_GROUP, PROOF_TOPIC
from ..database import bans_repo
from ..utils.format import topic_link, utcnow
from . import log_templates

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- DB lookups

async def find_active_for_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Convenience re-export so handlers do not import the repo directly."""
    return await bans_repo.find_active_for_user(user_id)


async def find_by_ban_id(ban_id: str) -> Optional[Dict[str, Any]]:
    return await bans_repo.find_by_ban_id(ban_id)


# --------------------------------------------------------------- proof I/O

async def post_proof_to_topic(
    context: ContextTypes.DEFAULT_TYPE,
    media: List[Dict[str, Any]],
    caption: str,
) -> Optional[int]:
    """Upload one or more media items to the proof topic.

    Returns the message ID of the first media (used for ``proof_link``)
    or ``None`` if the upload failed entirely.
    """
    try:
        if len(media) == 1:
            item = media[0]
            if item["kind"] == "photo":
                m = await context.bot.send_photo(
                    chat_id=MAIN_GROUP,
                    message_thread_id=PROOF_TOPIC,
                    photo=item["file_id"],
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
            else:
                m = await context.bot.send_video(
                    chat_id=MAIN_GROUP,
                    message_thread_id=PROOF_TOPIC,
                    video=item["file_id"],
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
            return m.message_id

        items: list[Any] = []
        for idx, it in enumerate(media):
            cap = caption if idx == 0 else None
            if it["kind"] == "photo":
                items.append(
                    InputMediaPhoto(
                        media=it["file_id"], caption=cap, parse_mode=ParseMode.HTML
                    )
                )
            else:
                items.append(
                    InputMediaVideo(
                        media=it["file_id"], caption=cap, parse_mode=ParseMode.HTML
                    )
                )
        msgs = await context.bot.send_media_group(
            chat_id=MAIN_GROUP,
            message_thread_id=PROOF_TOPIC,
            media=items,
        )
        return msgs[0].message_id if msgs else None
    except TelegramError as exc:
        logger.exception("Failed to post proof: %s", exc)
        return None


def proof_link_for(message_id: int) -> str:
    """Return the public proof-topic link for ``message_id``."""
    return topic_link(MAIN_GROUP, message_id, PROOF_TOPIC)


def caption_for_new_ban(
    *, target_id: int, admin_id: int, admin_name: str, when: datetime
) -> str:
    return log_templates.proof_caption_new(
        target_id=target_id,
        admin_id=admin_id,
        admin_name=admin_name,
        timestamp=when,
    )


def caption_for_updated_ban(
    *,
    target_id: int,
    admin_id: int,
    admin_name: str,
    previous_proof_link: str,
    original_when: datetime,
    update_when: datetime,
) -> str:
    return log_templates.proof_caption_update(
        target_id=target_id,
        admin_id=admin_id,
        admin_name=admin_name,
        previous_proof_link=previous_proof_link,
        original_timestamp=original_when,
        update_timestamp=update_when,
    )


# ----------------------------------------------------------- DB persistence

async def persist_new_ban(
    *,
    target_id: int,
    admin_id: int,
    reason: str,
    proof_message_id: int,
    log_message_id: Optional[int],
    when: datetime,
) -> str:
    """Insert a new ban document and return its generated ``ban_id``."""
    ban_id = f"{target_id}_{int(when.timestamp())}"
    await bans_repo.insert_new(
        ban_id=ban_id,
        banned_user_id=target_id,
        reason=reason,
        admin_user_id=admin_id,
        proof_message_id=proof_message_id,
        log_message_id=log_message_id,
        timestamp=when,
    )
    return ban_id


async def persist_ban_update(
    *,
    existing: Dict[str, Any],
    proof_message_id: int,
    log_message_id: Optional[int],
    admin_id: int,
    reason: str,
    update_when: datetime,
) -> None:
    await bans_repo.update_existing(
        ban_id=existing["ban_id"],
        previous_proof_message_id=existing.get("proof_message_id"),
        previous_log_message_id=existing.get("log_message_id"),
        proof_message_id=proof_message_id,
        log_message_id=log_message_id,
        admin_user_id=admin_id,
        reason=reason,
        update_timestamp=update_when,
    )


async def deactivate_ban(ban_id: str) -> None:
    await bans_repo.deactivate(ban_id)


def now() -> datetime:
    """Forwarder so handlers can import a single time-source."""
    return utcnow()
