# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Admin management – promote, demote, transfer ownership, and promotion requests."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import decorators, extraction, keyboards, parse_logmsg
from tcbot.modules.helper.formatter import code, mention
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)

__module_name__ = "Admins"
__help_text__ = (
    "<code>/tcpromote</code> <i>&lt;target&gt;</i> – promote a user to admin.\n"
    "Aliases: <code>/promote</code>, <code>/tcfpromote</code>\n\n"
    "<code>/tcdemote</code> <i>&lt;target&gt;</i> – remove admin status (owner only).\n"
    "Aliases: <code>/demote</code>, <code>/tcfdemote</code>\n\n"
    "<code>/tctransfer</code> <i>&lt;target&gt;</i> – transfer ownership (owner only).\n"
    "Aliases: <code>/transfer</code>, <code>/tcowner</code>\n\n"
    "<code>/tcpromoterequests</code> – submit a promotion request.\n"
    "Aliases: <code>/promoreqs</code>, <code>/tcreqs</code>\n\n"
    "<code>/tcpromotelist</code> – list pending requests (staff only)."
)


## ---------------------------------------------------------------------------
## Promote
## ---------------------------------------------------------------------------

async def cmd_promote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    admin = update.effective_user
    is_owner = await db.admins_db.is_owner(admin.id)
    is_staff = await db.admins_db.is_staff(admin.id)

    if not is_staff:
        await update.effective_message.reply_text("You are not authorized.")
        return

    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)

    if not target_id:
        await update.effective_message.reply_text(
            "Reply to a user, provide a user ID, or provide a username to promote."
        )
        return

    if target_id == admin.id:
        await update.effective_message.reply_text("You cannot promote yourself.")
        return

    if await db.admins_db.is_admin(target_id):
        await update.effective_message.reply_text("Already a Transsion Core Admin.")
        return

    lc, lt = cfg.logs

    if is_owner:
        ## Immediate promotion
        await db.admins_db.add_admin(target_id, admin.id)
        await db.users_db.upsert_user(target_id, None, target_fname)

        log_text = parse_logmsg.admin_promoted(target_id, target_fname, admin.id, admin.first_name)
        try:
            await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
        except Exception as exc:
            log.error("Promote log failed: %s", exc)

        await update.effective_message.reply_text(
            f"User {code(str(target_id))} is now a Transsion Core Admin.", parse_mode="HTML",
        )
    else:
        ## Admin path: create promotion request
        existing = await db.queues_db.get_request(target_id)
        if existing:
            await update.effective_message.reply_text(
                f"Promotion request for {code(str(target_id))} is already pending.",
                parse_mode="HTML",
            )
            return

        request_id = await db.queues_db.enqueue(target_id, None, target_fname, admin.id)

        req_text = parse_logmsg.promo_request_log(target_id, target_fname, None, request_id)
        owner_id = await db.admins_db.get_owner_id()

        ## Try to notify owner in PM first, fallback to LOG_CHANNEL
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
            f"Promotion request for {code(str(target_id))} has been sent to the Transsion Core Owner for approval.",
            parse_mode="HTML",
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
            "Reply to a user, provide a user ID, or provide a username to demote."
        )
        return

    if target_id == admin.id:
        await update.effective_message.reply_text(
            "I cannot demote myself. I hold a crucial position in this Transsion Core. "
            "Please ask the owner to do it."
        )
        return

    if await db.admins_db.is_owner(target_id):
        await update.effective_message.reply_text("Cannot demote the Transsion Core Owner.")
        return

    removed = await db.admins_db.remove_admin(target_id)
    if not removed:
        await update.effective_message.reply_text("Not a Transsion Core Admin.")
        return

    lc, lt = cfg.logs
    log_text = parse_logmsg.admin_demoted(target_id, target_fname, admin.id, admin.first_name)
    try:
        await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
    except Exception as exc:
        log.error("Demote log failed: %s", exc)

    await update.effective_message.reply_text("User demoted from Transsion Core Admin.")


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
            "Reply to a user, provide a user ID, or provide a username to transfer ownership to."
        )
        return

    if target_id == current_owner.id:
        await update.effective_message.reply_text("You are already the owner.")
        return

    ## Old owner becomes an admin
    await db.admins_db.add_admin(current_owner.id, current_owner.id)
    await db.admins_db.set_owner(target_id)

    lc, lt = cfg.logs
    old_fname = current_owner.first_name
    log_text = parse_logmsg.ownership_transferred(
        target_id, target_fname, current_owner.id, old_fname,
    )
    try:
        await ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt)
    except Exception as exc:
        log.error("Transfer log failed: %s", exc)

    await update.effective_message.reply_text(
        f"Ownership transferred to {code(str(target_id))}.", parse_mode="HTML",
    )


## ---------------------------------------------------------------------------
## Promotion request (any user)
## ---------------------------------------------------------------------------

async def cmd_promote_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    existing = await db.queues_db.get_request(user.id)
    if existing:
        await update.effective_message.reply_text(
            f"You already have a pending promotion request (ID: <code>{existing['request_id']}</code>).",
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
        f"Your promotion request has been submitted.\nRequest ID: <code>{request_id}</code>",
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
                target_id, "Your promotion request has been approved. You are now a Transsion Core Admin.",
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
                (q.message.text or "") + f"\n\nApproved by {admin.first_name}", reply_markup=None,
            )
        except Exception:
            pass

    elif action == "promo_reject":
        await db.queues_db.resolve(request_id, "rejected", admin.id)

        try:
            await ctx.bot.send_message(target_id, "Your promotion request has been rejected.")
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
                (q.message.text or "") + f"\n\nRejected by {admin.first_name}", reply_markup=None,
            )
        except Exception:
            pass


## ---------------------------------------------------------------------------
## Handler list
## ---------------------------------------------------------------------------

_PROMOTE_FILTER = (
    build_prefixed_filters("tcpromote")
    | build_prefixed_filters("promote")
    | build_prefixed_filters("tcfpromote")
)
_DEMOTE_FILTER = (
    build_prefixed_filters("tcdemote")
    | build_prefixed_filters("demote")
    | build_prefixed_filters("tcfdemote")
)
## Spec aliases: /tctransfer, /transfer, /tcowner
_TRANSFER_FILTER = (
    build_prefixed_filters("tctransfer")
    | build_prefixed_filters("transfer")
    | build_prefixed_filters("tcowner")
)
## Spec aliases: /tcpromoterequests, /promoreqs, /tcreqs
_PROMOREQ_FILTER = (
    build_prefixed_filters("tcpromoterequests")
    | build_prefixed_filters("promoreqs")
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
