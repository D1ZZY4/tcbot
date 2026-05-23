# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role
from tcbot.modules.helper import decorators, extraction, keyboards, parse_logmsg
from tcbot.modules.helper.formatter import code, mention
from tcbot.modules.helper.workflows.promote_flow import (
    _ROLE_ALIASES,
    _available_roles_for,
    _execute_promote,
)
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Admins"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcpromote</code> (alias: <code>/tcp</code>)\n"
    "<code>/tcdemote</code> (alias: <code>/tcd</code>)\n"
    "<code>/transferowner</code> (alias: <code>/tfowner</code>)\n"
    "<code>/tcpromoterequests</code> (alias: <code>/tcreqs</code>)\n"
    "<code>/tcpromotelist</code> (alias: <code>/tcplist</code>\n\n"
    "<b>Role Hierarchy</b>\n"
    "Founder (rank 4) › Admin (rank 3) › Developer (rank 2) › Tester (rank 1)\n\n"
    "<b>/tcpromote</b>\n"
    "Assigns a role to a user. Omit the role argument to get an inline button menu.\n"
    "Usage: <code>/tcpromote @user [admin|developer|tester]</code>\n"
    "- Founder can promote to any role directly.\n"
    "- Admin can promote to Developer or Tester directly; promoting someone to Admin "
    "sends a pending request to the Founder for approval.\n"
    "- You cannot promote a user to a rank equal to or above your own.\n\n"
    "<b>/tcdemote</b>\n"
    "Removes a user's role. A confirmation button is shown before the action executes.\n"
    "Usage: <code>/tcdemote @user</code>\n"
    "- Founder can demote any role.\n"
    "- Admin can demote Developer or Tester only.\n"
    "- When a user with a role is banned or kicked, their role is automatically removed "
    "and they are notified by DM.\n\n"
    "<b>/transferowner</b>\n"
    "Transfers federation ownership to another user. The current Founder steps down to Admin. "
    "Founder only.\n"
    "Usage: <code>/transferowner @user</code>\n\n"
    "<b>/tcpromoterequests</b>\n"
    "Submits a request to the Founder to be promoted to Admin. The Founder receives a "
    "notification with Approve / Reject buttons.\n\n"
    "<b>/tcpromotelist</b>\n"
    "Lists all pending Admin promotion requests. Admin and above only.\n\n"
    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username after the command.\n\n"
    "<b>Examples</b>\n"
    "<code>/tcpromote @username developer</code>\n"
    "<code>/tcpromote 123456789</code> - shows role selection menu\n"
    "<code>/tcdemote @username</code>\n"
    "<code>/transferowner @newowner</code>"
)


# ────────────────── Command Promote </tcpromote> ────────────────── #


@decorators.ratelimiter(limit=5, period=60)
@decorators.log_execution
async def cmd_promote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    admin = update.effective_user
    msg = update.effective_message
    args = parse_cmd_args(msg.text)

    has_explicit_target = bool(args) and (
        args[0].lstrip("-").isdigit() or args[0].startswith("@")
    )
    # * Role check and target resolution run in parallel
    executor_role, (target_id, target_fname) = await asyncio.gather(
        get_effective_role(admin.id),
        extraction.extract_target(update, args, ctx.bot),
    )
    remaining_args = args[1:] if has_explicit_target else args
    role_arg = remaining_args[0].lower() if remaining_args else ""

    if executor_role not in ("founder", "admin"):
        await msg.reply_text(
            "Only Founder and Admin can promote users - not your call. 🚫"
        )
        return

    if not target_id:
        await msg.reply_text(
            "Specify a target - reply to a message, or provide a user ID / @username."
        )
        return

    if target_id == admin.id:
        await msg.reply_text(
            "Can't promote yourself - the hierarchy doesn't work that way. 🙃"
        )
        return

    if target_id == ctx.bot.id:
        await msg.reply_text("That's me - promoting a bot doesn't quite work. 😄")
        return

    role = _ROLE_ALIASES.get(role_arg)
    current_role = await get_effective_role(target_id)

    if role:
        ok, text = await _execute_promote(
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
    available = _available_roles_for(executor_role)
    if not available:
        await msg.reply_text("You don't have permission to assign any roles.")
        return
    await msg.reply_text(
        f"Choose a role to assign to {mention(target_id, target_fname or str(target_id))}:",
        parse_mode="HTML",
        reply_markup=keyboards.promote_role_kb(target_id, available),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=10, period=30)
@decorators.log_execution
async def on_promote_role_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    admin = update.effective_user
    executor_role = await get_effective_role(admin.id)

    if executor_role not in ("founder", "admin"):
        await q.answer("You no longer have permission to do this.", show_alert=True)
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        return

    parts = q.data.split(":", 2)
    if len(parts) != 3:
        return
    _, role, target_id_str = parts
    target_id = int(target_id_str)

    if role not in ("admin", "developer", "tester"):
        await q.edit_message_text("Unknown role.", reply_markup=None)
        return

    # * answer + fetch name + current role in parallel
    _, target_fname, current_role = await asyncio.gather(
        q.answer(),
        db.users_db.get_first_name(target_id, str(target_id)),
        get_effective_role(target_id),
    )

    ok, text = await _execute_promote(
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


@decorators.ratelimiter(limit=10, period=30)
@decorators.log_execution
async def on_promote_role_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            "Promotion cancelled. No changes were made.", reply_markup=None
        ),
    )


# ─────────────────── Command Demote </tcdemote> ─────────────────── #


@decorators.ratelimiter(limit=5, period=60)
@decorators.log_execution
async def cmd_demote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    admin = update.effective_user
    msg = update.effective_message
    args = parse_cmd_args(msg.text)

    # * Role check and target resolution run in parallel
    executor_role, (target_id, target_fname) = await asyncio.gather(
        get_effective_role(admin.id),
        extraction.extract_target(update, args, ctx.bot),
    )
    if executor_role not in ("founder", "admin"):
        await msg.reply_text(
            "Only Founder and Admin can demote users - not your call. 🚫"
        )
        return

    if not target_id:
        await msg.reply_text(
            "Specify a target - reply to a message, or provide a user ID / @username."
        )
        return

    if target_id == admin.id:
        await msg.reply_text("Can't demote yourself - ask a higher-up if needed. 🙃")
        return

    target_role = await get_effective_role(target_id)

    if not target_role or target_role == "founder":
        await msg.reply_text("That user doesn't hold a role that can be removed.")
        return

    if target_role == "admin" and executor_role != "founder":
        await msg.reply_text("Only the Founder can demote an Admin.")
        return

    role_label = ROLE_LABEL.get(target_role, target_role)
    await msg.reply_text(
        f"{mention(target_id, target_fname or str(target_id))} is currently a "
        f"<b>{role_label}</b>.\nConfirm to remove their role.",
        parse_mode="HTML",
        reply_markup=keyboards.demote_confirm_kb(target_id),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=10, period=30)
@decorators.log_execution
async def on_demote_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    admin = update.effective_user
    target_id = int(q.data.split(":", 1)[1])
    executor_role = await get_effective_role(admin.id)

    if executor_role not in ("founder", "admin"):
        await q.answer("You no longer have permission to do this.", show_alert=True)
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        return

    # * answer + fetch target role + name in parallel
    _, target_role, target_fname = await asyncio.gather(
        q.answer(),
        get_effective_role(target_id),
        db.users_db.get_first_name(target_id, str(target_id)),
    )
    if not target_role or target_role == "founder":
        await q.edit_message_text(
            "That user no longer holds a removable role.", reply_markup=None
        )
        return

    if target_role == "admin" and executor_role != "founder":
        await q.edit_message_text(
            "Only the Founder can demote an Admin.", reply_markup=None
        )
        return

    if target_role == "admin":
        removed = await db.admins_db.remove_admin(target_id)
    else:
        removed = await db.roles_db.remove_role(target_id)

    if not removed:
        await q.edit_message_text(
            "Couldn't remove the role - it may have already been cleared.",
            reply_markup=None,
        )
        return

    lc, lt = cfg.logs
    role_label = ROLE_LABEL.get(target_role, target_role)
    log_text = parse_logmsg.role_removed(
        target_id,
        target_fname,
        target_role,
        admin.id,
        admin.first_name,
    )
    # * log, notify, and edit review message all in parallel
    await asyncio.gather(
        ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        ctx.bot.send_message(
            target_id,
            f"Your {role_label} role in {cfg.community_name} has been removed by "
            f"{admin.first_name}.",
        ),
        q.edit_message_text(
            f"Done. {mention(target_id, target_fname)} has been removed from {role_label}.",
            parse_mode="HTML",
            reply_markup=None,
        ),
        return_exceptions=True,
    )


@decorators.ratelimiter(limit=10, period=30)
@decorators.log_execution
async def on_demote_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await asyncio.gather(
        q.answer(),
        q.edit_message_text("Cancelled. No changes were made.", reply_markup=None),
    )


# ───────────── Command Transfer Owner </transferowner> ──────────── #


@decorators.ratelimiter(limit=3, period=300)
@decorators.owner_only
@decorators.log_execution
async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    current_owner = update.effective_user
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify the new owner - reply to a message, or provide a user ID / @username."
        )
        return
    if target_id == current_owner.id:
        await update.effective_message.reply_text(
            "You're already the Founder - can't transfer ownership to yourself. 😅"
        )
        return
    # * add_admin must complete before set_owner (set_owner does delete_many + insert)
    await db.admins_db.add_admin(current_owner.id, current_owner.id)
    await db.admins_db.set_owner(target_id)
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
        update.effective_message.reply_text(
            f"Done. Ownership has been transferred to {mention(target_id, target_fname)}.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )


# ───────── Command Promotion Requests </tcpromoterequests> ──────── #


@decorators.ratelimiter(limit=3, period=300)
@decorators.log_execution
async def cmd_promote_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    existing = await db.queues_db.get_request(user.id)
    if existing:
        await update.effective_message.reply_text(
            f"You already have a pending request (ID: <code>{existing['request_id']}</code>).",
            parse_mode="HTML",
        )
        return
    # * enqueue + get_owner_id in parallel
    request_id, owner_id = await asyncio.gather(
        db.queues_db.enqueue(user.id, user.username, user.first_name, user.id),
        db.admins_db.get_owner_id(),
    )
    req_text = parse_logmsg.promo_request_log(
        user.id, user.first_name, user.username, request_id
    )
    lc, lt = cfg.logs
    notified = False
    if owner_id:
        try:
            await ctx.bot.send_message(
                owner_id,
                req_text,
                parse_mode="HTML",
                reply_markup=keyboards.promo_decision_kb(request_id),
            )
            notified = True
        except Exception as exc:
            log.warning("Owner DM failed, falling back to log channel: %s", exc)
    if not notified:
        try:
            await ctx.bot.send_message(
                lc,
                req_text,
                parse_mode="HTML",
                message_thread_id=lt,
                reply_markup=keyboards.promo_decision_kb(request_id),
            )
        except Exception as exc:
            log.error("Promo request notify failed: %s", exc)
    await update.effective_message.reply_text(
        f"Your promotion request has been submitted. Request ID: <code>{request_id}</code>",
        parse_mode="HTML",
    )


# ──────── Command Promotion Requests List </tcpromotelist> ──────── #


@decorators.ratelimiter(limit=5, period=60)
@decorators.staff_only
@decorators.log_execution
async def cmd_promote_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    pending = await db.queues_db.all_pending()
    if not pending:
        await update.effective_message.reply_text("No pending promotion requests.")
        return
    lines = [f"<b>Pending Promotion Requests ({len(pending)})</b>\n"]
    for req in pending:
        uname = f"@{req['username']}" if req.get("username") else "no username"
        lines.append(
            f"- {mention(req['target_id'], req['first_name'])} "
            f"{code(str(req['target_id']))} | {uname} | ID: <code>{req['request_id']}</code>"
        )
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=10, period=30)
@decorators.log_execution
async def on_promo_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    admin = update.effective_user
    is_owner = await db.admins_db.is_owner(admin.id)
    if not is_owner:
        await q.answer("Founder only.", show_alert=True)
        return
    action, request_id = q.data.split(":", 1)
    # * answer + fetch request in parallel
    _, req = await asyncio.gather(
        q.answer(),
        db.queues_db.get_request_by_id(request_id),
    )
    if not req:
        await q.edit_message_text("Request not found or already resolved.")
        return
    target_id = req["target_id"]
    target_fname = req.get("first_name", str(target_id))
    lc, lt = cfg.logs

    if action == "promo_approve":
        # * DB writes in parallel
        await asyncio.gather(
            db.admins_db.add_admin(target_id, admin.id),
            db.queues_db.resolve(request_id, "approved", admin.id),
        )
        log_text = parse_logmsg.promo_approved_log(
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
                f"Your promotion request has been approved - welcome to the {cfg.community_name} staff team, Admin! 🎉",
            ),
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            q.edit_message_text(
                (q.message.text or "") + f"\n\n- Approved by {admin.first_name}",
                reply_markup=None,
            ),
            return_exceptions=True,
        )

    elif action == "promo_reject":
        log_text = parse_logmsg.promo_rejected_log(
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
