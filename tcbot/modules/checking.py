# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Ban status check commands."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot import cfg
from tcbot.modules.helper import extraction, keyboards
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.formatter import esc, mention
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

__module_name__ = "Checking"
__help_text__ = (
    "<b>Help — Check Ban</b>\n\n"
    "<b>Commands & Aliases</b>\n"
    "<code>/checkme</code> — alias: <code>/cme</code>\n"
    "<code>/checkban</code> — alias: <code>/cban</code>\n\n"
    "<b>Who can use it</b>\n"
    "Anyone — no special permissions needed.\n\n"
    "<b>Where to use it</b>\n"
    "Anywhere — bot PM, exec group, or any connected group.\n\n"
    "<b>What it does</b>\n"
    "<code>/checkme</code> — checks your own federation ban status. "
    "If you're banned, the bot will show the reason, who banned you, and give you a button "
    "to submit an appeal.\n\n"
    "<code>/checkban</code> — looks up the ban status of any user. "
    "Shows full details including the reason, ban date, and who issued it. "
    "If proof exists, you'll get a button to view it.\n\n"
    "<b>How to specify the target (checkban)</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"
    "<b>Examples</b>\n"
    "<code>/checkme</code>\n"
    "<code>/checkban @username</code>\n"
    "<code>/cban 123456789</code>"
)


async def cmd_checkme(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    ban = await db.bans_db.get_active_ban(uid)

    if not ban:
        await update.effective_message.reply_text(
            "You are not banned in the Transsion Core."
        )
        return

    proof_chat, proof_thread = cfg.proofs
    proof_link = (
        message_link(proof_chat, ban["proof_message_id"], proof_thread)
        if ban.get("proof_message_id")
        else None
    )
    bot_info = await ctx.bot.get_me()
    ban_id = ban["ban_id"]
    admin_fname = await db.users_db.get_first_name(ban.get("admin_user_id", 0), "Admin")

    lines = [
        "You are currently banned from Transsion Core.",
        f"Reason: {esc(ban['reason'])}",
        f"Banned by: {admin_fname}",
    ]
    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboards.checkme_appeal_kb(bot_info.username, ban_id),
    )


async def cmd_baninfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = parse_cmd_args(update.effective_message.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await update.effective_message.reply_text("Cannot resolve user.")
        return

    msg = update.effective_message
    fname = target_fname or str(target_id)

    owner_id = await db.admins_db.get_owner_id()
    if target_id == owner_id:
        owner_fname = await db.users_db.get_first_name(owner_id, "the Founder")
        await msg.reply_text(
            f"Bro... that's {mention(owner_id, owner_fname)}, our Founder 😭\n\n"
            "They built this whole federation — banning them would be like locking "
            "the landlord out of their own building. Not happening.\n"
            "Definitely clean, obviously. Anything else?",
            parse_mode="HTML",
        )
        return

    if await db.admins_db.is_admin(target_id):
        await msg.reply_text(
            f"Hold up — {mention(target_id, fname)} is part of our staff team! 😄\n\n"
            "They're more likely to be the ones issuing bans, not receiving them. "
            "No active ban on record — they're all good.",
            parse_mode="HTML",
        )
        return

    ban = await db.bans_db.get_active_ban(target_id)
    if not ban:
        await msg.reply_text(
            f"All clear! {mention(target_id, fname)} has no active ban in TCF. "
            "They're free to go — clean as a whistle. ✅",
            parse_mode="HTML",
        )
        return

    text, proof_link = await build_ban_detail(ban, target_fname)
    kb = keyboards.baninfo_proof_kb(proof_link) if proof_link else None
    await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)


_CHECKME_FILTER = build_prefixed_filters("checkme") | build_prefixed_filters("cme")
_BANINFO_FILTER = build_prefixed_filters("checkban") | build_prefixed_filters("cban")

__handlers__ = [
    MessageHandler(_CHECKME_FILTER, cmd_checkme),
    MessageHandler(_BANINFO_FILTER, cmd_baninfo),
]
