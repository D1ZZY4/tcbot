# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Admin management – promote, demote, transfer ownership, and promotion requests."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import database as db
from tcbot import cfg
from tcbot.modules.helper import decorators, extraction, keyboards, parse_logmsg
from tcbot.modules.helper.formatter import code, mention
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

__module_name__ = "Admins"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcpromote</code> — alias: <code>/tcp</code>\n"
    "<code>/tcdemote</code> — alias: <code>/tcd</code>\n"
    "<code>/transferowner</code> — alias: <code>/tfowner</code>\n"
    "<code>/tcpromoterequests</code> — alias: <code>/tcreqs</code>\n"
    "<code>/tcpromotelist</code>\n\n"

    "<b>Who can use it</b>\n"
    "<code>/tcpromote</code> — TC Staff can submit a request; owner approves instantly.\n"
    "<code>/tcdemote</code>, <code>/transferowner</code> — Owner only.\n"
    "<code>/tcpromoterequests</code> — Anyone can submit a request.\n"
    "<code>/tcpromotelist</code> — TC Staff only.\n\n"

    "<b>Where to use it</b>\n"
    "Exec group or bot PM.\n\n"

    "<b>What it does</b>\n"
    "<code>/tcpromote</code> — promotes a user to TC Admin. If the owner runs it, "
    "promotion is immediate. If a staff member runs it, a request is sent to the owner for approval.\n\n"
    "<code>/tcdemote</code> — removes TC Admin status from a user (owner only).\n\n"
    "<code>/transferowner</code> — transfers federation ownership to another user. "
    "The current owner becomes a regular admin.\n\n"
    "<code>/tcpromoterequests</code> — lets any user submit a request to become a TC Admin. "
    "The owner will be notified and can approve or reject.\n\n"
    "<code>/tcpromotelist</code> — lists all pending promotion requests.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"

    "<b>Examples</b>\n"
    "<code>/tcpromote @username</code>\n"
    "<code>/tcdemote 123456789</code>\n"
    "<code>/transferowner @newowner</code>\n"
    "<code>/tcpromoterequests</code> — submits your own request"
)


## ---------------------------------------------------------------------------
## Promote
## ---------------------------------------------------------------------------

async def cmd_promote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    admin = update.effective_user
    is_owner = await db.admins_db.is_owner(admin.id)
    is_staff = await db.admins_db.is_staff(admin.id)

    if not is_staff:
        await update.effective_message.reply_text("Not authorized.")
        return

    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)

    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target — reply to a message, or provide a user ID or @username."
        )
        return

    if target_id == admin.id:
        await update.effective_message.reply_text("You cannot promote yourself.")
        return

    if await db.admins_db.is_admin(target_id):
        await update.effective_message.reply_text(f"That user is already a {cfg.community_name} Admin.")
        return

    lc, lt = cfg.logs

    if is_owner:
        await db.admins_db.add_admin(target_id, admin.id)
        await db.users_db.upsert_user(target_id, None, target_fname)
        log_text = parse_logmsg.admin_promoted(target_id, target_fname, admin.id, admin.first_name)
        try:
            await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
        except Exception as exc:
            log.error("Promote log failed: %s", exc)
        await update.effective_message.reply_text(
            f"Done. {mention(target_id, target_fname)} is now a {cfg.community_name} Admin.",
            parse_mode="HTML",
        )
    else:
        existing = await db.queues_db.get_request(target_id)
        if existing:
            await update.effective_message.reply_text(
                f"There is already a pending promotion request for {mention(target_id, target_fname)}.",
                parse_mode="HTML",
            )
            return
        request_id = await db.queues_db.enqueue(target_id, None, target_fname, admin.id)
        req_text = parse_logmsg.promo_request_log(target_id, target_fname, None, request_id)
        owner_id = await db.admins_db.get_owner_id()
        notified = False
        if owner_id:
            try:
                await ctx.bot.send_message(
                    owner_id, req_text, parse_mode="HTML",
                    reply_markup=keyboards.promo_decision_kb(request_id),
                )
                notified = True
            except Exception:
                pass
        if not notified:
            owner_mention = mention(owner_id, "Owner") if owner_id else "Owner"
            try:
                await ctx.bot.send_message(
                    lc,
                    req_text + f"\n\n{owner_mention} please review.",
                    parse_mode="HTML",
                    message_thread_id=lt,
                    reply_markup=keyboards.promo_decision_kb(request_id),
                )
            except Exception as exc:
                log.error("Promo request notify failed: %s", exc)
        await update.effective_message.reply_text(
            "Request submitted. The owner has been notified and will review it shortly.",
        )


## ---------------------------------------------------------------------------
## Demote
## ---------------------------------------------------------------------------

@decorators.owner_only
async def cmd_demote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    admin = update.effective_user
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify a target — reply to a message, or provide a user ID or @username."
        )
        return
    if target_id == admin.id:
        await update.effective_message.reply_text("You cannot demote yourself.")
        return
    if await db.admins_db.is_owner(target_id):
        await update.effective_message.reply_text(f"Cannot demote the {cfg.community_name} Owner.")
        return
    removed = await db.admins_db.remove_admin(target_id)
    if not removed:
        await update.effective_message.reply_text(f"That user is not a {cfg.community_name} Admin.")
        return
    lc, lt = cfg.logs
    log_text = parse_logmsg.admin_demoted(target_id, target_fname, admin.id, admin.first_name)
    try:
        await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
    except Exception as exc:
        log.error("Demote log failed: %s", exc)
    await update.effective_message.reply_text(
        f"Done. {mention(target_id, target_fname)} has been removed from the admin team.",
        parse_mode="HTML",
    )


## ---------------------------------------------------------------------------
## Transfer ownership
## ---------------------------------------------------------------------------

@decorators.owner_only
async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    current_owner = update.effective_user
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text(
            "Specify the new owner — reply to a message, or provide a user ID or @username."
        )
        return
    if target_id == current_owner.id:
        await update.effective_message.reply_text("You are already the owner.")
        return
    await db.admins_db.add_admin(current_owner.id, current_owner.id)
    await db.admins_db.set_owner(target_id)
    lc, lt = cfg.logs
    log_text = parse_logmsg.ownership_transferred(
        target_id, target_fname, current_owner.id, current_owner.first_name,
    )
    try:
        await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
    except Exception as exc:
        log.error("Transfer log failed: %s", exc)
    await update.effective_message.reply_text(
        f"Done. Ownership has been transferred to {mention(target_id, target_fname)}.",
        parse_mode="HTML",
    )


## ---------------------------------------------------------------------------
## Promotion request (any user)
## ---------------------------------------------------------------------------

async def cmd_promote_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    existing = await db.queues_db.get_request(user.id)
    if existing:
        await update.effective_message.reply_text(
            f"You already have a pending request (ID: <code>{existing['request_id']}</code>).",
            parse_mode="HTML",
        )
        return
    request_id = await db.queues_db.enqueue(user.id, user.username, user.first_name, user.id)
    req_text = parse_logmsg.promo_request_log(user.id, user.first_name, user.username, request_id)
    owner_id = await db.admins_db.get_owner_id()
    lc, lt = cfg.logs
    notified = False
    if owner_id:
        try:
            await ctx.bot.send_message(
                owner_id, req_text, parse_mode="HTML",
                reply_markup=keyboards.promo_decision_kb(request_id),
            )
            notified = True
        except Exception:
            pass
    if not notified:
        try:
            await ctx.bot.send_message(
                lc, req_text, parse_mode="HTML",
                message_thread_id=lt,
                reply_markup=keyboards.promo_decision_kb(request_id),
            )
        except Exception as exc:
            log.error("Promo request notify failed: %s", exc)
    await update.effective_message.reply_text(
        f"Your promotion request has been submitted. Request ID: <code>{request_id}</code>",
        parse_mode="HTML",
    )


## ---------------------------------------------------------------------------
## Promotion list (staff only)
## ---------------------------------------------------------------------------

@decorators.staff_only
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


## ---------------------------------------------------------------------------
## Promotion decision callback (owner only)
## ---------------------------------------------------------------------------

async def on_promo_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    admin = update.effective_user
    if not await db.admins_db.is_owner(admin.id):
        await q.answer("Owner only.", show_alert=True)
        return
    action, request_id = q.data.split(":", 1)
    req = await db.queues_db.get_request_by_id(request_id)
    if not req:
        await q.edit_message_text("Request not found or already resolved.")
        return
    target_id = req["target_id"]
    target_fname = req.get("first_name", str(target_id))
    lc, lt = cfg.logs
    if action == "promo_approve":
        await db.admins_db.add_admin(target_id, admin.id)
        await db.queues_db.resolve(request_id, "approved", admin.id)
        try:
            await ctx.bot.send_message(
                target_id,
                f"Your promotion request has been approved — you are now a {cfg.community_name} Admin.",
            )
        except Exception:
            pass
        log_text = parse_logmsg.promo_approved_log(
            target_id, target_fname, admin.id, admin.first_name, request_id,
        )
        try:
            await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
        except Exception:
            pass
        try:
            await q.edit_message_text(
                (q.message.text or "") + f"\n\n— Approved by {admin.first_name}",
                reply_markup=None,
            )
        except Exception:
            pass
    elif action == "promo_reject":
        await db.queues_db.resolve(request_id, "rejected", admin.id)
        try:
            await ctx.bot.send_message(
                target_id,
                "Your promotion request has been reviewed and was not approved at this time.",
            )
        except Exception:
            pass
        log_text = parse_logmsg.promo_rejected_log(
            target_id, target_fname, admin.id, admin.first_name, request_id,
        )
        try:
            await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
        except Exception:
            pass
        try:
            await q.edit_message_text(
                (q.message.text or "") + f"\n\n— Rejected by {admin.first_name}",
                reply_markup=None,
            )
        except Exception:
            pass


## ---------------------------------------------------------------------------
## Handler list
## ---------------------------------------------------------------------------

_PROMOTE_FILTER = (
    build_prefixed_filters("tcpromote")
    | build_prefixed_filters("tcp")
)
_DEMOTE_FILTER = (
    build_prefixed_filters("tcdemote")
    | build_prefixed_filters("tcd")
)
_TRANSFER_FILTER = (
    build_prefixed_filters("transferowner")
    | build_prefixed_filters("tfowner")
)
_PROMOREQ_FILTER = (
    build_prefixed_filters("tcpromoterequests")
    | build_prefixed_filters("tcreqs")
)

__handlers__ = [
    MessageHandler(_PROMOTE_FILTER, cmd_promote),
    MessageHandler(_DEMOTE_FILTER, cmd_demote),
    MessageHandler(_TRANSFER_FILTER, cmd_transfer),
    MessageHandler(_PROMOREQ_FILTER, cmd_promote_request),
    MessageHandler(build_prefixed_filters("tcpromotelist"), cmd_promote_list),
    CallbackQueryHandler(on_promo_decision, pattern=r"^(promo_approve|promo_reject):"),
]
