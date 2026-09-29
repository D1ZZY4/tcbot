# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Self-serve federation status (/checkme) with ban summary and detail cards."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_edit_cb, safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import fmt_dt

if TYPE_CHECKING:
    from telegram import Update

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)

_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 8
_RL_CHECKME_CB_LIMIT: int = 15


async def _ban_summary(
    ban: BanDoc,
    user_id: int,
    user_fname: str,
    admin_fname: str | None = None,
    locale: str | None = None,
) -> tuple[str, str | None]:
    """Build the /checkme summary text and proof link."""
    aid = ban.get("admin_user_id", 0)

    # Fetch mention data for both users in parallel
    _user_r, _admin_r = await asyncio.gather(
        db.users_cache.get_user_mention_data(user_id),
        db.users_cache.get_user_mention_data(aid),
        return_exceptions=True,
    )
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

    proof_chat, proof_thread = cfg.proofs
    proof_msg_id = ban.get("proof_message_id")
    proof_link = (
        message_link(proof_chat, proof_msg_id, proof_thread)
        if proof_msg_id is not None
        else None
    )

    ts = ban.get("timestamp")
    date_str = (
        fmt_dt(ts) if ts else t("checking.ban_info.unknown_date", locale, plain=True)
    )

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


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_checkme(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the caller's federation status (ban / staff role / clean record).

    Fetches the caller role and active ban in parallel. Returns
    role-aware replies for staff members and regular users.
    Provides an appeal deep-link when the caller is actively banned.
    """
    user = update.effective_user
    msg = update.effective_message
    if user is None or msg is None:
        return
    locale = await locale_for_update(update)
    # * Bots and the anonymous-admin placeholder hold no federation records;
    # * without this guard an anonymous-admin /checkme would get a misleading
    # * "You're clean" verdict for an ID that can never be banned or staffed.
    if user.is_bot:
        await safe_reply(
            msg,
            t("checking.error.bot_sender", locale, plain=True),
            log_label="checkme bot-sender",
            parse_mode=None,
        )
        return
    fname = user.first_name or str(user.id)

    # * No identity.classify() call: executor == target always yields
    # * kind="self", so its founder/admin branches could never fire;
    # * user_role below covers staff. No owner-ID fetch either: nothing
    # * below uses it.
    user_role, ban = await asyncio.gather(
        db.users_roles.get_effective_role(user.id),
        db.bans_db.get_active_ban(user.id),
        return_exceptions=True,
    )
    if isinstance(user_role, BaseException):
        user_role = None
    # * Never render a clean bill of health from a failed read: during an
    # * outage a coerced None would tell a banned user "You're clean" (same
    # * defect class as the /check Unknown rendering). Fail closed with a
    # * retry notice instead; the staff branches below stay unreachable on
    # * this path because nothing about the caller could be verified.
    if isinstance(ban, BaseException):
        log.warning("checkme ban lookup failed for user=%d: %s", user.id, ban)
        await safe_reply(
            msg,
            t("checking.error.status_retry", locale, plain=True),
            log_label=f"checkme retry for user {user.id}",
            parse_mode=None,
        )
        return

    # * If the caller has an active ban, ALWAYS show the ban summary with
    # * the appeal button -- even for staff. A banned staff member still
    # * needs the appeal link, and the staff-flavoured early-returns below
    # * would otherwise tell them "you're fine" while they are banned.
    if ban is not None:
        text, proof_link = await _ban_summary(ban, user.id, fname, None, locale)
        await safe_reply(
            msg,
            text,
            log_label="checkme banned-staff",
            reply_markup=keyboards.checkme_ban_kb(
                ctx.bot.username or "", str(ban.get("ban_id", "")), proof_link, locale
            ),
        )
        return

    if user_role == "admin":
        await safe_reply(
            msg,
            t(
                "checking.checkme.staff_admin",
                locale,
                user=Safe(user_ref(user.id, fname, user.username)),
            ),
            log_label=f"checkme admin for user {user.id}",
        )
        return
    if user_role in ("developer", "tester"):
        role_label = db.users_roles.ROLE_LABEL.get(user_role, user_role)
        await safe_reply(
            msg,
            t(
                "checking.checkme.staff_role",
                locale,
                user=Safe(user_ref(user.id, fname, user.username)),
                community=cfg.community_name,
                role=role_label,
            ),
            log_label=f"checkme subrole for user {user.id}",
        )
        return

    # * ban is None on this path: the active-ban branch above always returns,
    # * so the second ban-detail block that used to follow was unreachable
    # * dead code (removed). The clean reply below is live for non-staff,
    # * non-banned callers.
    await safe_reply(
        msg,
        t("checking.checkme.clean", locale, community=cfg.community_name, plain=True),
        log_label=f"checkme clean for user {user.id}",
        parse_mode=None,
    )
    return


@decorators.ratelimiter(limit=_RL_CHECKME_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_checkme_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed ban information from the /checkme ban card.

    Fetches the ban record, answers the query and builds the detail view in
    parallel, then edits the message to the full detail card with a back button.
    """
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        ban_id = q.data.split(":")[1]
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)

    _, ban = await asyncio.gather(
        q.answer(), db.bans_db.get_ban(ban_id), return_exceptions=True
    )
    if isinstance(ban, BaseException):
        # * Never clobber the live ban card from a failed read: an outage
        # * is not proof the ban went inactive. Answer with a retry popup
        # * (mirroring the appeal-review outage path) and leave the card
        # * untouched so the appeal button stays available.
        log.warning("checkme_detail ban lookup failed for %s: %s", ban_id, ban)
        try:
            await q.answer(
                t("checking.error.status_retry", locale, plain=True),
                show_alert=True,
            )
        except Exception as exc:
            log.debug("checkme_detail retry answer failed: %s", exc)
        return
    if not ban or not ban.get("is_active"):
        try:
            await q.edit_message_text(
                t("checking.error.ban_inactive", locale, plain=True),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("checkme_detail error edit failed: %s", exc)
        return

    text, proof_link = await build_ban_detail(ban, locale=locale)
    await safe_edit_cb(
        q,
        text,
        reply_markup=keyboards.checkme_detail_back_kb(ban_id, proof_link, locale),
    )


@decorators.ratelimiter(limit=_RL_CHECKME_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_checkme_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to the ban summary card from the detail view.

    Fetches the ban record, answers the query and resolves display names in
    parallel, then edits the message back to the summary card with the appeal
    and detail keyboard.
    """
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        ban_id = q.data.split(":")[1]
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)

    _, ban = await asyncio.gather(
        q.answer(), db.bans_db.get_ban(ban_id), return_exceptions=True
    )
    if isinstance(ban, BaseException):
        # * Same card-preservation rationale as on_checkme_detail above: a
        # * failed re-read keeps the refusal-worthy unknown, not a "not
        # * found" verdict, and the summary card stays actionable.
        log.warning("checkme_back ban lookup failed for %s: %s", ban_id, ban)
        try:
            await q.answer(
                t("checking.error.status_retry", locale, plain=True),
                show_alert=True,
            )
        except Exception as exc:
            log.debug("checkme_back retry answer failed: %s", exc)
        return
    if not ban:
        try:
            await q.edit_message_text(
                t("checking.error.ban_not_found", locale, plain=True),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("checkme_back error edit failed: %s", exc)
        return

    uid = ban.get("banned_user_id", 0)
    aid = ban.get("admin_user_id", 0)
    fname, admin_fname = await asyncio.gather(
        db.users_cache.get_first_name(uid, str(uid)),
        db.users_cache.get_first_name(aid, "Admin"),
        return_exceptions=True,
    )
    if isinstance(fname, BaseException):
        fname = str(uid)
    if isinstance(admin_fname, BaseException):
        admin_fname = "Admin"
    text, proof_link = await _ban_summary(ban, uid, fname, admin_fname, locale)
    await safe_edit_cb(
        q,
        text,
        reply_markup=keyboards.checkme_ban_kb(
            ctx.bot.username or "", ban_id, proof_link, locale
        ),
    )
