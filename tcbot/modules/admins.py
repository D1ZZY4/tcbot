# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Admin management handlers: promote, demote, transfer ownership, and manage requests."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import (
    decorators,
    extraction,
    identity,
    keyboards,
    parse_logmsg,
    replies,
)
from tcbot.modules.helper.formatter import code, mention
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.promote_flow import ROLE_ALIASES, Promote
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_ERR_NO_ASSIGN_PERMS = "You don't have permission to assign any roles."
_MSG_PROMOTE_CANCELLED = "Promotion cancelled. No changes were made."
_ERR_NO_REMOVABLE_ROLE = "That user doesn't hold a role that can be removed."
_ERR_FOUNDER_DEMOTE_ONLY = "Only the Founder can demote an Admin."
_ERR_NO_LONGER_REMOVABLE = "That user no longer holds a removable role."
_ERR_ROLE_CLEAR_FAILED = "Couldn't remove the role - it may have already been cleared."
_MSG_CANCELLED = "Cancelled. No changes were made."
_MSG_NO_PENDING = "No pending promotion requests."
_ERR_REQUEST_NOT_FOUND = "Request not found or already resolved."

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_PERIOD_LONG_S: int = 60
_RL_PERIOD_BULK_S: int = 300
_RL_CMD_LIMIT: int = 10
_RL_QUERY_LIMIT: int = 5
_RL_BULK_LIMIT: int = 3


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Admins"
__help_text__ = (
    "Promote and demote staff, transfer ownership, and manage promotion requests "
    "across the federation."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/tcpromote</code> (alias: <code>/tcp</code>)\n"
        "<code>/tcdemote</code> (alias: <code>/tcd</code>)\n"
        "<code>/transferowner</code> (alias: <code>/tfowner</code>)\n"
        "<code>/tcpromoterequests</code> (alias: <code>/tcreqs</code>)\n"
        "<code>/tcpromotelist</code> (alias: <code>/tcplist</code>)",
    ),
    (
        replies.SEC_WHO,
        "<b>/tcpromote</b>, <b>/tcdemote</b>, <b>/tcpromotelist</b>: Founder and Admin.\n"
        f"<b>/transferowner</b>: {replies.PERM_FOUNDER_ONLY}\n"
        "<b>/tcpromoterequests</b>: anyone (creates a self-request to the Founder).",
    ),
    (
        replies.SEC_WHERE,
        replies.CONTEXT_BOT_OR_GROUP,
    ),
    (
        "Role Hierarchy",
        "Founder (rank 4) › Admin (rank 3) › Developer (rank 2) › Tester (rank 1)\n\n"
        "You cannot promote a user to a rank equal to or above your own. "
        "Admins promoting someone to Admin queues a request for the Founder.",
    ),
    (
        replies.SEC_TARGET,
        replies.TARGET_SYNTAX,
    ),
    (
        "/tcpromote",
        "Assigns a role to a user. Omit the role argument to get an inline button menu.\n\n"
        "<b>Usage:</b> <code>/tcpromote &lt;target&gt; [admin|developer|tester]</code>\n"
        "- Founder can promote to any role directly.\n"
        "- Admin can promote to Developer or Tester directly; promoting to Admin "
        "sends a pending request to the Founder for approval.",
    ),
    (
        "/tcdemote",
        "Removes a user's role. A confirmation button is shown before the action executes.\n\n"
        "<b>Usage:</b> <code>/tcdemote &lt;target&gt;</code>\n"
        "- Founder can demote any role.\n"
        "- Admin can demote Developer or Tester only.\n"
        "- When a user with a role is banned or kicked, their role is automatically removed "
        "and they are notified by DM.",
    ),
    (
        "/transferowner",
        "Transfers federation ownership to another user. The current Founder steps down "
        "to Admin. Founder only.\n\n"
        "<b>Usage:</b> <code>/transferowner &lt;target&gt;</code>",
    ),
    (
        replies.SEC_EXAMPLES,
        "<code>/tcpromote @username developer</code>\n"
        "<code>/tcpromote 123456789</code> - shows role selection menu\n"
        "<code>/tcdemote @username</code>\n"
        "<code>/transferowner @newowner</code>\n"
        "<code>/tcpromoterequests</code> - request promotion to Admin\n"
        "<code>/tcplist</code> - list pending promotion requests",
    ),
]


# ────────────────── Command Promote </tcpromote> ────────────────── #


@decorators.ratelimiter(limit=_RL_QUERY_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_promote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Assign a federation role to a user (admin / developer / tester).

    Fetches the executor role and resolves the target in parallel. Then fetches
    identity classification and the target's current role in a second parallel
    gather, since both are independent reads. When a role name is given inline,
    executes the promotion immediately via ``Promote.execute``. When no role is
    given, shows a role-selection keyboard. Identity and rank checks prevent
    self-promotion or promoting above one's own rank.
    """
    admin = update.effective_user
    msg = update.effective_message
    args = parse_cmd_args(msg.text)

    has_explicit_target = bool(args) and (
        args[0].lstrip("-").isdigit() or args[0].startswith("@")
    )
    # * Executor role (founder/admin guaranteed by @staff_only) + target run in parallel
    executor_role, (target_id, target_fname) = await asyncio.gather(
        db.users_roles.get_effective_role(admin.id),
        extraction.extract_target(update, args, ctx.bot),
    )
    remaining_args = args[1:] if has_explicit_target else args
    role_arg = remaining_args[0].lower() if remaining_args else ""

    if not target_id:
        await msg.reply_text(
            "Specify a target - reply to a message, or provide a user ID / @username."
        )
        return

    # * identity classify and current-role fetch are independent reads; run in parallel.
    ident, current_role = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_fname),
        db.users_roles.get_effective_role(target_id),
    )
    refusal = identity.refuse_message("promote", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return

    role = ROLE_ALIASES.get(role_arg)

    if role:
        ok, text = await Promote.execute(
            ctx.bot,
            admin.id,
            admin.first_name,
            executor_role,
            target_id,
            target_fname or str(target_id),
            current_role,
            role,
        )
        await msg.reply_text(text, parse_mode="HTML")
        return

    # * No role arg - show selection buttons
    available = Promote.available_roles_for(executor_role)
    if not available:
        await msg.reply_text(_ERR_NO_ASSIGN_PERMS)
        return
    await msg.reply_text(
        f"Choose a role to assign to {mention(target_id, target_fname or str(target_id), ident.username)}:",
        parse_mode="HTML",
        reply_markup=keyboards.promote_role_kb(target_id, available),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promote_role_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the role-selection inline button from /tcpromote.

    Verifies the executor still holds staff rank; rejects with alert if expired.
    Fetches the target's name and current role in parallel, then delegates to
    ``Promote.execute`` and edits the prompt to the result.
    """
    q = update.callback_query
    admin = update.effective_user
    executor_role = await db.users_roles.get_effective_role(admin.id)

    if executor_role not in ("founder", "admin"):
        await q.answer(replies.ERR_PERM_EXPIRED, show_alert=True)
        try:
            await q.edit_message_reply_markup(None)
        except Exception as exc:
            log.debug("Failed to clear promote reply markup: %s", exc)
        return

    parts = q.data.split(":", 2)
    if len(parts) != 3:
        return
    _, role, target_id_str = parts
    target_id = int(target_id_str)

    if role not in ("admin", "developer", "tester"):
        await q.edit_message_text(replies.ERR_UNKNOWN_ROLE, reply_markup=None)
        return

    # * answer + fetch name + current role in parallel
    _, target_fname, current_role = await asyncio.gather(
        q.answer(),
        db.users_cache.get_first_name(target_id, str(target_id)),
        db.users_roles.get_effective_role(target_id),
    )

    ok, text = await Promote.execute(
        ctx.bot,
        admin.id,
        admin.first_name,
        executor_role,
        target_id,
        target_fname,
        current_role,
        role,
    )
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=None)


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promote_role_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Acknowledge the cancel button and replace the role-selection prompt with a cancellation notice."""
    q = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(_MSG_PROMOTE_CANCELLED, reply_markup=None),
    )


# ─────────────────── Command Demote </tcdemote> ─────────────────── #


@decorators.ratelimiter(limit=_RL_QUERY_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_demote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a user's federation role.

    Fetches the executor role and resolves the target in parallel. Then fetches
    identity classification and the target's current role in a second parallel
    gather, since both are independent reads. Shows a confirmation keyboard for
    the target's current role. Identity guards prevent demoting the Founder or
    self without the correct flow.
    """
    admin = update.effective_user
    msg = update.effective_message
    args = parse_cmd_args(msg.text)

    # * Executor role (founder/admin guaranteed by @staff_only) + target run in parallel
    executor_role, (target_id, target_fname) = await asyncio.gather(
        db.users_roles.get_effective_role(admin.id),
        extraction.extract_target(update, args, ctx.bot),
    )

    if not target_id:
        await msg.reply_text(
            "Specify a target - reply to a message, or provide a user ID / @username."
        )
        return

    # * identity classify and target-role fetch are independent reads; run in parallel.
    ident, target_role = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_fname),
        db.users_roles.get_effective_role(target_id),
    )
    refusal = identity.refuse_message("demote", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return

    if not target_role:
        await msg.reply_text(_ERR_NO_REMOVABLE_ROLE)
        return

    if target_role == "admin" and executor_role != "founder":
        await msg.reply_text(_ERR_FOUNDER_DEMOTE_ONLY)
        return

    role_label = db.users_roles.ROLE_LABEL.get(target_role, target_role)
    await msg.reply_text(
        f"{mention(target_id, target_fname or str(target_id), ident.username)} is currently a "
        f"<b>{role_label}</b>.\nConfirm to remove their role.",
        parse_mode="HTML",
        reply_markup=keyboards.demote_confirm_kb(target_id),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_demote_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm the demote action from the inline keyboard.

    Re-validates the executor's rank; rejects with alert if insufficient.
    Answers the query, fetches the target's current role and mention data in
    parallel, then executes ``Demote.execute`` and edits the prompt to the result.
    """
    q = update.callback_query
    admin = update.effective_user
    target_id = int(q.data.split(":", 1)[1])
    executor_role = await db.users_roles.get_effective_role(admin.id)

    if executor_role not in ("founder", "admin"):
        await q.answer(replies.ERR_PERM_EXPIRED, show_alert=True)
        try:
            await q.edit_message_reply_markup(None)
        except Exception as exc:
            log.debug("Failed to clear demote reply markup: %s", exc)
        return

    # * answer + fetch target role + mention data in parallel
    _, target_role, (target_fname, target_uname) = await asyncio.gather(
        q.answer(),
        db.users_roles.get_effective_role(target_id),
        db.users_cache.get_user_mention_data(target_id),
    )

    if not target_role or target_role == "founder":
        await q.edit_message_text(_ERR_NO_LONGER_REMOVABLE, reply_markup=None)
        return

    if target_role == "admin" and executor_role != "founder":
        await q.edit_message_text(_ERR_FOUNDER_DEMOTE_ONLY, reply_markup=None)
        return

    removed = await Demote.execute(
        ctx.bot,
        target_id,
        target_fname,
        target_role,
        admin.id,
        admin.first_name,
        trigger=None,
    )
    if not removed:
        await q.edit_message_text(_ERR_ROLE_CLEAR_FAILED, reply_markup=None)
        return

    role_label = db.users_roles.ROLE_LABEL.get(target_role, target_role)
    await q.edit_message_text(
        f"Done. {mention(target_id, target_fname, target_uname)} - {code(str(target_id))} "
        f"has been removed from {role_label}.",
        parse_mode="HTML",
        reply_markup=None,
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_demote_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge the cancel button and collapse the demotion confirmation prompt."""
    q = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(_MSG_CANCELLED, reply_markup=None),
    )


# ───────────── Command Transfer Owner </transferowner> ──────────── #


@decorators.ratelimiter(limit=_RL_BULK_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Transfer federation ownership to another user.

    Resolves the new owner target, runs identity checks, then sequentially
    demotes the current owner to Admin (``add_admin``) and promotes the target
    to Founder (``set_owner``). The two DB writes are intentionally sequential
    because ``set_owner`` does a ``delete_many`` that must see the owner record
    before it is replaced. Logs and confirmation reply run in parallel afterward.
    """
    current_owner = update.effective_user
    msg = update.effective_message
    if current_owner is None or msg is None:
        return

    args = parse_cmd_args(msg.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text(
            "Specify the new owner - reply to a message, or provide a user ID / @username."
        )
        return

    ident = await identity.classify(ctx.bot, current_owner.id, target_id, target_fname)
    refusal = identity.refuse_message("transfer", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return

    target_uname = ident.username

    # * add_admin must complete before set_owner (set_owner does delete_many + insert)
    await db.users_roles.add_admin(current_owner.id, current_owner.id)
    await db.users_roles.set_owner(target_id)
    lc, lt = cfg.logs
    log_text = parse_logmsg.ownership_transferred(
        target_id,
        target_fname,
        current_owner.id,
        current_owner.first_name,
    )
    # * log and reply in parallel
    await asyncio.gather(
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        msg.reply_text(
            f"Done. Ownership has been transferred to "
            f"{mention(target_id, target_fname, target_uname)} - {code(str(target_id))}.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )


# ───────── Command Promotion Requests </tcpromoterequests> ──────── #


@decorators.ratelimiter(limit=_RL_BULK_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.log_execution
async def cmd_promote_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit a promotion request to the Founder.

    Checks identity and any existing pending request in parallel. Rejects if the
    user is banned or already has an open request, then calls
    ``Promote.request_admin`` to create a new queue entry and notify the Founder.
    """
    user = update.effective_user
    msg = update.effective_message
    if user is None or msg is None:
        return

    ident, existing = await asyncio.gather(
        identity.classify(ctx.bot, user.id, user.id, user.first_name),
        db.queues_db.get_request(user.id),
    )
    refusal = identity.refuse_message("promote", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return

    if existing:
        await msg.reply_text(
            f"You already have a pending request (ID: <code>{existing['request_id']}</code>).",
            parse_mode="HTML",
        )
        return
    ok, reply = await Promote.request_admin(
        ctx.bot, user.id, user.id, user.first_name, user.username
    )
    await msg.reply_text(reply, parse_mode="HTML")


# ──────── Command Promotion Requests List </tcpromotelist> ──────── #


@decorators.ratelimiter(limit=_RL_QUERY_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_promote_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a formatted list of all pending promotion requests."""
    pending = await db.queues_db.all_pending()
    if not pending:
        await update.effective_message.reply_text(_MSG_NO_PENDING)
        return
    lines = [f"<b>Pending Promotion Requests ({len(pending)})</b>\n"]
    for req in pending:
        uname = f"@{req['username']}" if req.get("username") else "no username"
        lines.append(
            f"- {mention(req['target_id'], req['first_name'], req.get('username'))} "
            f"{code(str(req['target_id']))} | {uname} | ID: <code>{req['request_id']}</code>"
        )
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promo_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approve / reject decisions on promotion request cards.

    Owner-only callback. Answers the query and fetches the request record in
    parallel. On approve, executes ``Promote.execute`` and updates the card. On
    reject, marks the request resolved and edits the card to show the rejection.
    """
    q = update.callback_query
    admin = update.effective_user
    is_owner = await db.users_roles.is_owner(admin.id)
    if not is_owner:
        await q.answer(replies.PERM_FOUNDER_ONLY, show_alert=True)
        return
    action, request_id = q.data.split(":", 1)
    # * answer + fetch request in parallel
    _, req = await asyncio.gather(
        q.answer(),
        db.queues_db.get_request_by_id(request_id),
    )
    if not req:
        await q.edit_message_text(_ERR_REQUEST_NOT_FOUND)
        return
    target_id = req["target_id"]
    target_fname = req.get("first_name", str(target_id))
    lc, lt = cfg.logs

    if action == "promo_approve":
        # * DB writes in parallel
        await asyncio.gather(
            db.users_roles.add_admin(target_id, admin.id),
            db.queues_db.resolve(request_id, "approved", admin.id),
        )
        log_text = parse_logmsg.promote_approved_log(
            target_id,
            target_fname,
            admin.id,
            admin.first_name,
            request_id,
        )
        # * notify target, send log, and edit review message all in parallel
        await asyncio.gather(
            ctx.bot.send_message(
                target_id,
                f"Your promotion request has been approved - welcome to the {cfg.community_name} staff team, Admin.",
            ),
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            q.edit_message_text(
                (q.message.text or "") + f"\n\n- Approved by {admin.first_name}",
                reply_markup=None,
            ),
            return_exceptions=True,
        )

    elif action == "promo_reject":
        log_text = parse_logmsg.promote_rejected_log(
            target_id,
            target_fname,
            admin.id,
            admin.first_name,
            request_id,
        )
        # * resolve DB + notify + send log + edit review message all in parallel
        await asyncio.gather(
            db.queues_db.resolve(request_id, "rejected", admin.id),
            ctx.bot.send_message(
                target_id,
                "Your request was reviewed but wasn't approved this time. You're free to apply again later.",
            ),
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            q.edit_message_text(
                (q.message.text or "") + f"\n\n- Rejected by {admin.first_name}",
                reply_markup=None,
            ),
            return_exceptions=True,
        )


# ──────────────────────────── Handlers ──────────────────────────── #

_PMT_CMDS = build_prefixed_filters("tcpromote") | build_prefixed_filters("tcp")
_DMT_CMDS = build_prefixed_filters("tcdemote") | build_prefixed_filters("tcd")
_TF_CMDS = build_prefixed_filters("transferowner") | build_prefixed_filters("tfowner")
_PMTREQ_CMDS = build_prefixed_filters("tcpromoterequests") | build_prefixed_filters(
    "tcreqs"
)
_PMTLIST_CMDS = build_prefixed_filters("tcpromotelist") | build_prefixed_filters(
    "tcplist"
)

__handlers__ = [
    MessageHandler(_PMT_CMDS, cmd_promote),
    MessageHandler(_DMT_CMDS, cmd_demote),
    MessageHandler(_TF_CMDS, cmd_transfer),
    MessageHandler(_PMTREQ_CMDS, cmd_promote_request),
    MessageHandler(_PMTLIST_CMDS, cmd_promote_list),
    CallbackQueryHandler(on_promo_decision, pattern=r"^(promo_approve|promo_reject):"),
    CallbackQueryHandler(on_promote_role_btn, pattern=r"^promo_role:[a-z]+:\d+$"),
    CallbackQueryHandler(on_promote_role_cancel, pattern=r"^promo_role_cancel:\d+$"),
    CallbackQueryHandler(on_demote_confirm, pattern=r"^demote_confirm:\d+$"),
    CallbackQueryHandler(on_demote_cancel, pattern=r"^demote_cancel:\d+$"),
]
