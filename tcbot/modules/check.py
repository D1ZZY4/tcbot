# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""checkme and check handlers: self ban status and comprehensive user-profile view."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, extraction, keyboards
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    ack_and_render,
    callback_args,
    callback_numbers,
    cb_error_edit,
    message_link,
    replies,
    safe_edit_cb,
    safe_reply,
)
from tcbot.modules.helper.pipelines.check_flow import Check
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.time_and_date import fmt_dt

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Check"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("checking.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("checking.help.commands.body", locale),
        ),
        replies.who_section(replies.context_anyone(locale), locale),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            "/checkme",
            t("checking.help.checkme.body", locale),
        ),
        (
            "/check",
            t("checking.help.check.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("checking.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()


# ───────────────────────── Self-check (/checkme) ─────────────────────── #


async def _ban_id_from_query(q: CallbackQuery) -> str | None:
    """Parse the ban id from checkme callback data, answering on malformed taps."""
    args = callback_args(q, 2)
    if args is None:
        await q.answer()
        return None
    return args[0]


async def _load_ban_for_callback(
    q: CallbackQuery, ban_id: str, locale: str | None, *, log_label: str
) -> BanDoc | None:
    """Answer the query and fetch its ban record in parallel.

    Returns the record, or ``None`` after answering with the retry alert
    when the read failed (the live card stays untouched so the appeal
    button remains actionable). Cancellation always propagates.
    """
    _, ban = await asyncio.gather(
        q.answer(), db.bans_db.get_ban(ban_id), return_exceptions=True
    )
    throw_if_cancelled((_, ban))
    if isinstance(ban, BaseException):
        log.warning("%s ban lookup failed for %s: %s", log_label, ban_id, ban)
        try:
            await q.answer(
                t("checking.error.status_retry", locale, plain=True),
                show_alert=True,
            )
        except Exception as exc:
            log.debug("%s retry answer failed: %s", log_label, exc)
        return None
    return ban


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


@decorators.ratelimiter(decorators.THROTTLE_READ)
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
    throw_if_cancelled((user_role, ban))
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
        role_label = db.users_roles.role_label(user_role)
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


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_checkme_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed ban information from the /checkme ban card.

    Fetches the ban record, answers the query and builds the detail view in
    parallel, then edits the message to the full detail card with a back button.
    """
    q = update.callback_query
    if q is None:
        return
    ban_id = await _ban_id_from_query(q)
    if ban_id is None:
        return
    locale = await locale_for_update(update)

    ban = await _load_ban_for_callback(q, ban_id, locale, log_label="checkme_detail")
    if ban is None:
        return
    # * Crafted taps on another user's card must not render it.
    if ban.get("banned_user_id", 0) != q.from_user.id:
        log.debug("checkme_detail ownership mismatch ban=%s", ban_id)
        return
    if not ban or not ban.get("is_active"):
        await cb_error_edit(
            q,
            t("checking.error.ban_inactive", locale, plain=True),
            log_label="checkme_detail error",
            parse_mode=None,
        )
        return

    text, proof_link = await build_ban_detail(ban, locale=locale)
    # * The detail card is a normal navigation, not a refusal: it keeps the
    # * back keyboard and renders as MarkdownV2 like every other card.
    await safe_edit_cb(
        q,
        text,
        reply_markup=keyboards.checkme_detail_back_kb(ban_id, proof_link, locale),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
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
    ban_id = await _ban_id_from_query(q)
    if ban_id is None:
        return
    locale = await locale_for_update(update)

    ban = await _load_ban_for_callback(q, ban_id, locale, log_label="checkme_back")
    if ban is None:
        return
    if ban.get("banned_user_id", 0) != q.from_user.id:
        log.debug("checkme_back ownership mismatch ban=%s", ban_id)
        return
    if not ban:
        await cb_error_edit(
            q,
            t("checking.error.ban_not_found", locale, plain=True),
            log_label="checkme_back error",
            parse_mode=None,
        )
        return

    uid = ban.get("banned_user_id", 0)
    aid = ban.get("admin_user_id", 0)
    admin_fallback = t("checking.profile.admin_fallback", locale, plain=True)
    fname, admin_fname = await asyncio.gather(
        db.users_cache.get_first_name(uid, str(uid)),
        db.users_cache.get_first_name(aid, admin_fallback),
        return_exceptions=True,
    )
    throw_if_cancelled((fname, admin_fname))
    if isinstance(fname, BaseException):
        fname = str(uid)
    if isinstance(admin_fname, BaseException):
        admin_fname = admin_fallback
    text, proof_link = await _ban_summary(ban, uid, fname, admin_fname, locale)
    await safe_edit_cb(
        q,
        text,
        reply_markup=keyboards.checkme_ban_kb(
            ctx.bot.username or "", ban_id, proof_link, locale
        ),
    )


# ───────────────────────── Profile (/check) ────────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.log_execution
async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a comprehensive profile (identity + bans + warns + kicks + mutes + appeals)."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    user = update.effective_user
    args = parse_cmd_args(msg.text)
    # * Read-only view: a typed target always beats the quoted message,
    # * so /check shows who was asked about, never who was quoted. When
    # * the arg resolves to nobody, the reply target still stands.
    target_id, target_fname = await extraction.extract_target(
        update, args, ctx.bot, prefer_explicit=True
    )
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="check resolve-fail",
            parse_mode=None,
        )
        return

    # * Refresh cache with whatever we just resolved so future renders
    # * have a real name. Skip when the resolved name is a bare numeric ID
    # * (extract_target fell back to str(target_id) because bot.get_chat
    # * returned nothing) -- in that case we let Check.profile do the
    # * heavy lifting via _resolve_user_info (which tries get_chat_member
    # * on each connected group) and we trust its lookup result.
    # * The refresh only writes when the name actually changed: an
    # * unconditional write cost a database round trip and evicted the
    # * mention cache on every /check.
    if target_fname and not db.users_cache.is_placeholder_name(target_fname):
        try:
            await db.users_cache.refresh_display_name(target_id, target_fname)
        except Exception as exc:
            log.debug("users_cache upsert failed for %d: %s", target_id, exc)

    text, kb = await Check.profile(
        ctx.bot,
        target_id,
        executor_id=user.id if user is not None else None,
        locale=locale,
    )
    await safe_reply(
        msg, text, log_label=f"check for target={target_id}", reply_markup=kb
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the top-level profile summary for the checked user."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 2)
    if numbers is None:
        await q.answer()
        return
    target_id = numbers[0]
    tapper = update.effective_user
    locale = await locale_for_update(update)
    await ack_and_render(
        q,
        Check.profile(
            ctx.bot,
            target_id,
            executor_id=tapper.id if tapper is not None else None,
            locale=locale,
        ),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of federation bans for the checked user."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 3)
    if numbers is None:
        await q.answer()
        return
    target_id, page = numbers
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.bans_list(target_id, page, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the full detail view for a single federation ban record."""
    q = update.callback_query
    if q is None:
        return
    args = callback_args(q, 3)
    if args is None:
        await q.answer()
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await q.answer()
        return
    ban_id = args[1]
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.ban_detail(target_id, ban_id, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_warns(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the per-group warning summary for the checked user."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 2)
    if numbers is None:
        await q.answer()
        return
    target_id = numbers[0]
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.warns_by_group(target_id, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_warn_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of warnings for the checked user in a specific group."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 4)
    if numbers is None:
        await q.answer()
        return
    target_id, chat_id, page = numbers
    locale = await locale_for_update(update)
    await ack_and_render(
        q,
        Check.warns_in_group(target_id, chat_id, page, locale),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_kicks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of kick records for the checked user."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 3)
    if numbers is None:
        await q.answer()
        return
    target_id, page = numbers
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.kicks_list(target_id, page, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_mutes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of mute records for the checked user."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 3)
    if numbers is None:
        await q.answer()
        return
    target_id, page = numbers
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.mutes_list(target_id, page, locale))


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK_DEEP)
@decorators.log_execution
async def on_check_appeals(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of appeal records for the checked user."""
    q = update.callback_query
    if q is None:
        return
    numbers = callback_numbers(q, 3)
    if numbers is None:
        await q.answer()
        return
    target_id, page = numbers
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.appeals_list(target_id, page, locale))


# ──────────────────────────── Handlers ──────────────────────────── #

_CHECKME_CMDS = build_prefixed_filters("checkme") | build_prefixed_filters("cme")
_CHECK_CMDS = build_prefixed_filters("check") | build_prefixed_filters("c")

__handlers__ = [
    MessageHandler(_CHECKME_CMDS, cmd_checkme),
    MessageHandler(_CHECK_CMDS, cmd_check),
    CallbackQueryHandler(on_checkme_detail, pattern=r"^checkme_detail:"),
    CallbackQueryHandler(on_checkme_back, pattern=r"^checkme_back:"),
    CallbackQueryHandler(on_check_main, pattern=r"^check_main:\d+$"),
    CallbackQueryHandler(on_check_bans, pattern=r"^check_bans:\d+:\d+$"),
    CallbackQueryHandler(on_check_ban_item, pattern=r"^check_ban_item:\d+:[a-z0-9]+$"),
    CallbackQueryHandler(on_check_warns, pattern=r"^check_warns:\d+$"),
    CallbackQueryHandler(
        on_check_warn_chat, pattern=r"^check_warn_chat:\d+:-?\d+:\d+$"
    ),
    CallbackQueryHandler(on_check_kicks, pattern=r"^check_kicks:\d+:\d+$"),
    CallbackQueryHandler(on_check_mutes, pattern=r"^check_mutes:\d+:\d+$"),
    CallbackQueryHandler(on_check_appeals, pattern=r"^check_appeals:\d+:\d+$"),
]
