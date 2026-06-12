# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""checkme and check handlers: self ban status and comprehensive user-profile view."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, extraction, keyboards, replies
from tcbot.modules.helper.formatter import code, esc, mention
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.workflows.check_flow import Check
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.timedate_format import fmt_dt

if TYPE_CHECKING:
    from telegram import CallbackQuery, InlineKeyboardMarkup, Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 8
_RL_CHECKME_CB_LIMIT: int = 15
_RL_CHECK_CB_LIMIT: int = 20

# ──────────────── User-facing reply constants ──────────────────── #

_ERR_BAN_INACTIVE = "This ban is no longer active."
_ERR_BAN_NOT_FOUND = "Ban record not found."

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Checking"
__help_text__ = (
    "Look up your own ban status with <code>/checkme</code>, or pull a full "
    "federation activity profile for any user with <code>/check</code>."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/checkme</code> (alias: <code>/cme</code>)\n"
        "<code>/check</code> (alias: <code>/c</code>)",
    ),
    (
        replies.SEC_WHO,
        replies.CONTEXT_ANYONE,
    ),
    (
        replies.SEC_WHERE,
        replies.CONTEXT_BOT_OR_GROUP,
    ),
    (
        "/checkme",
        "Checks your own federation ban status.\n\n"
        "- If you are <b>not banned</b>: the bot confirms your account is in good standing.\n"
        "- If you are <b>banned</b>: the bot shows the reason, the admin who issued the ban, "
        "the ban date, and gives you a <b>Submit Appeal</b> button to start the appeal "
        "process.",
    ),
    (
        "/check",
        "Pulls a full federation profile for any user: identity, role, active ban, "
        "ban history, warnings (by group), kicks, mutes, and appeals.\n\n"
        "Each section opens a drill-down inline keyboard so you can inspect every "
        "record individually.",
    ),
    (
        replies.SEC_TARGET,
        replies.TARGET_SYNTAX,
    ),
    (
        replies.SEC_EXAMPLES,
        "<code>/checkme</code>\n"
        "<code>/check @username</code>\n"
        "<code>/c 123456789</code>\n"
        "Or reply to a message and run <code>/c</code>.",
    ),
]


# ───────────────────────────── Helpers ──────────────────────────── #


async def _ban_summary(
    ban: dict,
    user_id: int,
    user_fname: str,
    admin_fname: str | None = None,
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
        admin_fname = admin_fname_cached

    proof_chat, proof_thread = cfg.proofs
    proof_link = (
        message_link(proof_chat, ban["proof_message_id"], proof_thread)
        if ban.get("proof_message_id")
        else None
    )

    ts = ban.get("timestamp")
    date_str = fmt_dt(ts) if ts else "Unknown"

    text = (
        f"You are currently banned from {esc(cfg.community_name)}.\n\n"
        f"User: {mention(user_id, user_fname, user_uname)}\n"
        f"User ID: {code(str(user_id))}\n"
        f"Reason: {esc(ban.get('reason', replies.NO_REASON))}\n\n"
        f"Banned by: {mention(aid, admin_fname, admin_uname)}\n\n"
        f"Commit Date: {date_str}\n"
        "Tap a button below for more details."
    )
    return text, proof_link


async def _safe_edit(
    q: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None
) -> None:
    """Edit message text; ignore 'message is not modified' errors."""
    try:
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


# ─────────── Command Check Ban for User Self </checkme> ─────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_checkme(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the caller's federation status (ban / staff role / clean record).

    Fetches the owner ID, caller role, and active ban in parallel. Returns
    identity-aware replies for the Founder, staff members, and regular users.
    Provides an appeal deep-link when the caller is actively banned.
    """
    user = update.effective_user
    msg = update.effective_message
    fname = user.first_name or str(user.id)

    # * Fetch owner ID, user role, and active ban all in parallel
    owner_id, user_role, ban = await asyncio.gather(
        db.users_roles.get_owner_id(),
        db.users_roles.get_effective_role(user.id),
        db.bans_db.get_active_ban(user.id),
        return_exceptions=True,
    )
    if isinstance(owner_id, BaseException):
        owner_id = None
    if isinstance(user_role, BaseException):
        user_role = None
    if isinstance(ban, BaseException):
        ban = None

    if user.id == owner_id:
        await msg.reply_text(
            f"Bro, {mention(user.id, fname, user.username)}... seriously?\n\n"
            "You're the Founder - you built this whole place. "
            "The ban list doesn't apply to you, you run it. "
            "Go touch grass, you're fine.",
            parse_mode="HTML",
        )
        return

    if user_role == "admin":
        await msg.reply_text(
            f"Hey {mention(user.id, fname, user.username)}, checking yourself?\n\n"
            "You're on the staff team - you handle bans, not receive them. "
            "No active ban on your end. You're good.",
            parse_mode="HTML",
        )
        return
    if user_role in ("developer", "tester"):
        role_label = db.users_roles.ROLE_LABEL.get(user_role, user_role)
        await msg.reply_text(
            f"Hey {mention(user.id, fname, user.username)}, all good.\n\n"
            f"You're a {esc(cfg.community_name)} {esc(role_label)} - on the team, not on the ban list. "
            "Nothing to worry about.",
            parse_mode="HTML",
        )
        return

    if not ban:
        await msg.reply_text(f"You're clean - no active ban in {cfg.community_name}.")
        return

    ban_id = ban["ban_id"]

    text, proof_link = await _ban_summary(ban, user.id, fname)

    await msg.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboards.checkme_ban_kb(ctx.bot.username, ban_id, proof_link),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CHECKME_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_checkme_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed ban information from the /checkme ban card.

    Fetches the ban record, answers the query and builds the detail view in
    parallel, then edits the message to the full detail card with a back button.
    """
    q = update.callback_query
    ban_id = q.data.split(":")[1]

    _, ban = await asyncio.gather(
        q.answer(), db.bans_db.get_ban(ban_id), return_exceptions=True
    )
    if isinstance(ban, BaseException):
        ban = None
    if not ban or not ban.get("is_active"):
        try:
            await q.edit_message_text(_ERR_BAN_INACTIVE, reply_markup=None)
        except Exception as exc:
            log.debug("checkme_detail error edit failed: %s", exc)
        return

    from tcbot.modules.helper.ban_info import (  # noqa: PLC0415
        build_ban_detail,
    )

    text, proof_link = await build_ban_detail(ban)
    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboards.checkme_detail_back_kb(ban_id, proof_link),
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
    ban_id = q.data.split(":")[1]

    _, ban = await asyncio.gather(
        q.answer(), db.bans_db.get_ban(ban_id), return_exceptions=True
    )
    if isinstance(ban, BaseException):
        ban = None
    if not ban:
        try:
            await q.edit_message_text(_ERR_BAN_NOT_FOUND, reply_markup=None)
        except Exception as exc:
            log.debug("checkme_back error edit failed: %s", exc)
        return

    uid = ban["banned_user_id"]
    aid = ban.get("admin_user_id", 0)
    fname, admin_fname = await asyncio.gather(
        db.users_cache.get_first_name(uid, str(uid)),
        db.users_cache.get_first_name(aid, "Admin"),
    )
    text, proof_link = await _ban_summary(ban, uid, fname, admin_fname)

    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboards.checkme_ban_kb(ctx.bot.username, ban_id, proof_link),
    )


# ───────────── Command Comprehensive Check </check> ────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a comprehensive profile (identity + bans + warns + kicks + mutes + appeals)."""
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Couldn't resolve that user. Reply to a message or provide a valid ID / @username."
        )
        return

    # * Refresh cache with whatever we just resolved so future renders have a real name.
    if target_fname and not target_fname.startswith("User "):
        try:
            await db.users_cache.upsert_user(target_id, None, target_fname)
        except Exception as exc:
            log.debug("users_cache upsert failed for %d: %s", target_id, exc)

    text, kb = await Check.profile(ctx.bot, target_id)
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)


# ─────────────── Callback Handlers for /check views ─────────────── #


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the top-level profile summary for the checked user."""
    q = update.callback_query
    target_id = int(q.data.split(":", 1)[1])
    _, result = await asyncio.gather(
        q.answer(), Check.profile(ctx.bot, target_id), return_exceptions=True
    )
    if isinstance(result, BaseException):
        log.debug("on_check_main failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of federation bans for the checked user."""
    q = update.callback_query
    _, target_id_str, page_str = q.data.split(":")
    target_id = int(target_id_str)
    page = int(page_str)
    _, result = await asyncio.gather(
        q.answer(), Check.bans_list(target_id, page), return_exceptions=True
    )
    if isinstance(result, BaseException):
        log.debug("on_check_bans failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the full detail view for a single federation ban record."""
    q = update.callback_query
    _, target_id_str, ban_id = q.data.split(":", 2)
    target_id = int(target_id_str)
    _, result = await asyncio.gather(
        q.answer(), Check.ban_detail(target_id, ban_id), return_exceptions=True
    )
    if isinstance(result, BaseException):
        log.debug("on_check_ban_item failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_warns(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the per-group warning summary for the checked user."""
    q = update.callback_query
    target_id = int(q.data.split(":", 1)[1])
    _, result = await asyncio.gather(
        q.answer(), Check.warns_by_group(target_id), return_exceptions=True
    )
    if isinstance(result, BaseException):
        log.debug("on_check_warns failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_warn_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of warnings for the checked user in a specific group."""
    q = update.callback_query
    _, target_id_str, chat_id_str, page_str = q.data.split(":")
    target_id = int(target_id_str)
    chat_id = int(chat_id_str)
    page = int(page_str)
    _, result = await asyncio.gather(
        q.answer(),
        Check.warns_in_group(target_id, chat_id, page),
        return_exceptions=True,
    )
    if isinstance(result, BaseException):
        log.debug("on_check_warn_chat failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_kicks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of kick records for the checked user."""
    q = update.callback_query
    _, target_id_str, page_str = q.data.split(":")
    target_id = int(target_id_str)
    page = int(page_str)
    _, result = await asyncio.gather(
        q.answer(), Check.kicks_list(target_id, page), return_exceptions=True
    )
    if isinstance(result, BaseException):
        log.debug("on_check_kicks failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_mutes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of mute records for the checked user."""
    q = update.callback_query
    _, target_id_str, page_str = q.data.split(":")
    target_id = int(target_id_str)
    page = int(page_str)
    _, result = await asyncio.gather(
        q.answer(), Check.mutes_list(target_id, page), return_exceptions=True
    )
    if isinstance(result, BaseException):
        log.debug("on_check_mutes failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_appeals(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of appeal records for the checked user."""
    q = update.callback_query
    _, target_id_str, page_str = q.data.split(":")
    target_id = int(target_id_str)
    page = int(page_str)
    _, result = await asyncio.gather(
        q.answer(), Check.appeals_list(target_id, page), return_exceptions=True
    )
    if isinstance(result, BaseException):
        log.debug("on_check_appeals failed: %s", result)
        return
    text, kb = result
    await _safe_edit(q, text, kb)


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
