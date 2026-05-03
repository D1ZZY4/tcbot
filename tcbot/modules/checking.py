# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Ban status check commands."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg, database as db
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role
from tcbot.modules.helper import extraction, keyboards
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.formatter import code, esc, mention
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.timedate_format import fmt_dt

__module_name__ = "Checking"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/checkme</code> (alias: <code>/cme</code>)\n"
    "<code>/checkban</code> (alias: <code>/cban</code>)\n\n"
    "<b>Who can use it</b>\n"
    "Anyone, no special permissions needed.\n\n"
    "<b>Where to use it</b>\n"
    "Bot PM, exec group, or any connected group.\n\n"
    "<b>What it does</b>\n"
    "<code>/checkme</code>: checks your own federation ban status. "
    "If you're banned, the bot will show the reason, who banned you, and give you a button "
    "to submit an appeal.\n\n"
    "<code>/checkban</code>: looks up the ban status of any user. "
    "Shows full details including the reason, ban date, and who issued it. "
    "If proof exists, you'll get a button to view it.\n\n"
    "<b>How to specify the target (checkban)</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"
    "<b>Examples</b>\n"
    "<code>/checkme</code>\n"
    "<code>/checkban @username</code>\n"
    "<code>/cban 123456789</code>"
)


## ---------------------------------------------------------------------------
## Helpers
## ---------------------------------------------------------------------------

async def _ban_summary(ban: dict, user_id: int, user_fname: str) -> tuple[str, str | None]:
    """Build the /checkme summary text and proof link."""
    aid         = ban.get("admin_user_id", 0)
    admin_fname = await db.users_db.get_first_name(aid, "Admin")

    proof_chat, proof_thread = cfg.proofs
    proof_link = (
        message_link(proof_chat, ban["proof_message_id"], proof_thread)
        if ban.get("proof_message_id") else None
    )

    ts       = ban.get("timestamp")
    date_str = fmt_dt(ts) if ts else "Unknown"

    text = (
        f"You are currently banned from {cfg.community_name}.\n\n"
        f"User: {mention(user_id, user_fname)}\n"
        f"User ID: {code(str(user_id))}\n"
        f"Reason: {esc(ban.get('reason', 'No reason provided'))}\n\n"
        f"Banned by: {mention(aid, admin_fname)}\n\n"
        f"Commit Date: {date_str}\n"
        "Tap a button below for more details."
    )
    return text, proof_link


## ---------------------------------------------------------------------------
## /checkme
## ---------------------------------------------------------------------------

async def cmd_checkme(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user  = update.effective_user
    msg   = update.effective_message
    fname = user.first_name or str(user.id)

    owner_id = await db.admins_db.get_owner_id()
    if user.id == owner_id:
        await msg.reply_text(
            f"Bro, {mention(user.id, fname)}... seriously? 😭\n\n"
            "You're the Founder. You literally built this place from scratch. "
            "There is no ban for you, you ARE the federation.\n"
            "Go touch grass, you're perfectly fine. 😊",
            parse_mode="HTML",
        )
        return

    user_role = await get_effective_role(user.id)
    if user_role == "admin":
        await msg.reply_text(
            f"Hey {mention(user.id, fname)}, checking yourself? 😄\n\n"
            "You're part of the staff team, the ones who handle bans, not receive them. "
            "No active ban on your end. You're good, now go back to work! 😊",
            parse_mode="HTML",
        )
        return
    if user_role in ("developer", "tester"):
        role_label = ROLE_LABEL.get(user_role, user_role)
        await msg.reply_text(
            f"Hey {mention(user.id, fname)}, all good! 😄\n\n"
            f"You're a {cfg.community_name} {role_label} — you're on the team, not on the ban list. "
            "Nothing to worry about here. 😊",
            parse_mode="HTML",
        )
        return

    ban = await db.bans_db.get_active_ban(user.id)
    if not ban:
        await msg.reply_text(f"You are not banned in {cfg.community_name}.")
        return

    bot_info       = await ctx.bot.get_me()
    ban_id         = ban["ban_id"]
    text, proof_link = await _ban_summary(ban, user.id, fname)

    await msg.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboards.checkme_ban_kb(bot_info.username, ban_id, proof_link),
    )


## ---------------------------------------------------------------------------
## /checkme inline callbacks
## ---------------------------------------------------------------------------

async def on_checkme_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q      = update.callback_query
    ban_id = q.data.split(":")[1]

    ban = await db.bans_db.get_ban(ban_id)
    if not ban or not ban.get("is_active"):
        await q.answer("This ban is no longer active.", show_alert=True)
        return

    await q.answer()
    text, proof_link = await build_ban_detail(ban)
    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboards.checkme_detail_back_kb(ban_id, proof_link),
    )


async def on_checkme_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q      = update.callback_query
    ban_id = q.data.split(":")[1]

    ban = await db.bans_db.get_ban(ban_id)
    if not ban:
        await q.answer("Ban record not found.", show_alert=True)
        return

    await q.answer()
    uid   = ban["banned_user_id"]
    fname = await db.users_db.get_first_name(uid, str(uid))
    bot_info = await ctx.bot.get_me()
    text, proof_link = await _ban_summary(ban, uid, fname)

    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboards.checkme_ban_kb(bot_info.username, ban_id, proof_link),
    )


## ---------------------------------------------------------------------------
## /checkban
## ---------------------------------------------------------------------------

async def cmd_baninfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text("Cannot resolve user.")
        return

    msg   = update.effective_message
    fname = target_fname or str(target_id)

    if target_id == ctx.bot.id:
        bot_info = await ctx.bot.get_me()
        await msg.reply_text(
            f"Hey, that's {mention(ctx.bot.id, bot_info.first_name or 'me')} — that's me. 😄\n\n"
            "I run things around here, so I'm definitely not on the receiving end of a ban. "
            "All clear.",
            parse_mode="HTML",
        )
        return

    owner_id = await db.admins_db.get_owner_id()
    if target_id == owner_id:
        owner_fname = await db.users_db.get_first_name(owner_id, "the Founder")
        await msg.reply_text(
            f"Bro... that's {mention(owner_id, owner_fname)}, our Founder 😭\n\n"
            "They built this whole federation, banning them would be like locking "
            "the landlord out of their own building. Not happening.\n"
            "Definitely clean, obviously. Anything else?",
            parse_mode="HTML",
        )
        return

    target_role = await get_effective_role(target_id)
    if target_role == "admin":
        await msg.reply_text(
            f"Hold up — {mention(target_id, fname)} is part of our staff team! 😄\n\n"
            "They're more likely to be the ones issuing bans, not receiving them. "
            "No active ban on record, they're all good.",
            parse_mode="HTML",
        )
        return
    if target_role in ("developer", "tester"):
        role_label = ROLE_LABEL.get(target_role, target_role)
        await msg.reply_text(
            f"Chill — {mention(target_id, fname)} is our {cfg.community_name} {role_label}! 😄\n\n"
            f"They're part of the team behind the scenes. No active ban on record, all good.",
            parse_mode="HTML",
        )
        return

    ban = await db.bans_db.get_active_ban(target_id)
    if not ban:
        await msg.reply_text(
            f"All clear! {mention(target_id, fname)} has no active ban in {cfg.community_name}. "
            "They're free to go, clean as a whistle. 😊",
            parse_mode="HTML",
        )
        return

    text, proof_link = await build_ban_detail(ban, target_fname)
    kb = keyboards.baninfo_proof_kb(proof_link) if proof_link else None
    await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)


## ---------------------------------------------------------------------------
## Handler registration
## ---------------------------------------------------------------------------

_CHECKME_FILTER = build_prefixed_filters("checkme") | build_prefixed_filters("cme")
_BANINFO_FILTER = build_prefixed_filters("checkban") | build_prefixed_filters("cban")

__handlers__ = [
    MessageHandler(_CHECKME_FILTER, cmd_checkme),
    MessageHandler(_BANINFO_FILTER, cmd_baninfo),
    CallbackQueryHandler(on_checkme_detail, pattern=r"^checkme_detail:"),
    CallbackQueryHandler(on_checkme_back,   pattern=r"^checkme_back:"),
]
