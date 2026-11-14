# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared ban-detail formatter: builds the rich ban information card from a ban document."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.messages import message_link
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import fmt_dt

log = get_logger(__name__)

if TYPE_CHECKING:
    from tcbot.database.documents import BanDoc

# ─────────────────────── Ban detail builder ─────────────────────── #


def ban_proof_link(ban: BanDoc) -> str | None:
    """Return the proof message link for a ban record, or ``None``.

    Single owner for the proof link: the proof channel and thread come
    from the configuration, so every ban surface links to the same post.
    A missing proof id renders no link.
    """
    proof_chat, proof_thread = cfg.proofs
    proof_msg_id = ban.get("proof_message_id")
    if not proof_msg_id:
        return None
    return message_link(proof_chat, proof_msg_id, proof_thread)


def ban_date_text(ban: BanDoc, locale: str | None = None) -> str:
    """Return the ban timestamp for display, or the unknown-date notice."""
    ts = ban.get("timestamp")
    return fmt_dt(ts) if ts else t("checking.ban_info.unknown_date", locale, plain=True)


async def build_ban_detail(
    ban: BanDoc, target_fname: str | None = None, locale: str | None = None
) -> tuple[str, str | None]:
    """Return (formatted text, proof_link or None) for a ban document."""
    # * BanDoc is total=False: every key access below uses .get() with a
    # * display-safe fallback so a sparse record renders instead of raising.
    uid = ban.get("target_user_id", 0)
    aid = ban.get("actor_user_id", 0)

    if target_fname is None:
        # Fetch mention data for both users in parallel
        r_target, r_admin = await asyncio.gather(
            db.users_cache.get_user_mention_data(uid),
            db.users_cache.get_user_mention_data(aid),
            return_exceptions=True,
        )
        throw_if_cancelled((r_target, r_admin))
        target_fname, target_uname = (
            r_target if not isinstance(r_target, BaseException) else (str(uid), None)
        )
        # * Outage fallback stays locale-neutral: the numeric ID renders
        # * the same in every language instead of a hardcoded word.
        admin_fname, admin_uname = (
            r_admin if not isinstance(r_admin, BaseException) else (str(aid), None)
        )
    else:
        try:
            r_admin = await db.users_cache.get_user_mention_data(aid)
            admin_fname, admin_uname = r_admin
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Admin mention data lookup failed for %d: %s", aid, exc)
            admin_fname, admin_uname = (str(aid), None)
        target_uname = None

    proof_link = ban_proof_link(ban)
    date_str = ban_date_text(ban, locale)

    text = (
        f"{t('checking.ban_info.title', locale)}\n\n"
        f"{t('checking.ban_info.user', locale, user=Safe(user_ref(uid, target_fname, target_uname)))}\n"
        f"{t('checking.ban_info.user_id', locale, id=Safe(code(str(uid))))}\n\n"
        f"{t('checking.ban_info.banned_by', locale, admin=Safe(user_ref(aid, admin_fname, admin_uname)))}\n"
        f"{t('checking.ban_info.admin_id', locale, id=Safe(code(str(aid))))}\n\n"
        # * Reason is moderator free text: pass raw so the engine escapes
        # * MarkdownV2 at render time (Safe would inject markup/parse errors).
        f"{t('checking.ban_info.reason', locale, reason=ban.get('reason', None) or t('checking.events.no_reason', locale, plain=True))}\n"
        f"{t('checking.ban_info.ban_id', locale, id=Safe(code(ban.get('ban_id', ''))))}\n"
        f"{t('checking.ban_info.date', locale, date=Safe(date_str))}"
    )
    return text, proof_link


async def build_ban_summary(
    ban: BanDoc,
    user_id: int,
    user_fname: str,
    admin_fname: str | None = None,
    locale: str | None = None,
) -> tuple[str, str | None]:
    """Return the compact ban summary card and its proof link.

    The /checkme card names the banned user, the reason, the moderator,
    and the date. The display names arrive resolved from the caller; only
    the usernames are read here, because a mention link is built from
    the numeric id and the names are only its label.
    """
    aid = ban.get("actor_user_id", 0)

    _user_r, _admin_r = await asyncio.gather(
        db.users_cache.get_user_mention_data(user_id),
        db.users_cache.get_user_mention_data(aid),
        return_exceptions=True,
    )
    # * Shutdown cancellation propagates; only real outages degrade below.
    throw_if_cancelled((_user_r, _admin_r))
    if isinstance(_user_r, BaseException):
        user_uname = None
    else:
        _, user_uname = _user_r
    if isinstance(_admin_r, BaseException):
        admin_fname_cached, admin_uname = None, None
    else:
        admin_fname_cached, admin_uname = _admin_r

    if admin_fname is None:
        admin_fname = admin_fname_cached or str(aid)

    proof_link = ban_proof_link(ban)
    date_str = ban_date_text(ban, locale)

    text = t(
        "checking.checkme.banned",
        locale,
        community=cfg.community_name,
        user=Safe(user_ref(user_id, user_fname, user_uname)),
        id=Safe(code(str(user_id))),
        reason=ban.get("reason", None)
        or t("checking.events.no_reason", locale, plain=True),
        admin=Safe(user_ref(aid, admin_fname, admin_uname)),
        date=Safe(date_str),
    )
    return text, proof_link
