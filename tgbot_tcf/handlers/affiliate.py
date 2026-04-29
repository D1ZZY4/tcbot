"""Group affiliation, disaffiliation, joinfed, my_chat_member events."""
import logging

from telegram import (
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import BRANDING, INITIAL_OWNER_ID
from ..db import fed_owners, federated_groups
from ..utils.auth import is_authorized
from ..utils.format import fmt_now, safe_first_name, user_link, utcnow
from ..utils.logger import log_to_channel

logger = logging.getLogger(__name__)


REQUIRED_PERMS = ("can_delete_messages", "can_restrict_members", "can_invite_users")
PERM_HINT = (
    "Please make the bot an admin with the necessary permissions "
    "(delete messages, ban users, invite users) and try again."
)


async def _bot_has_required_perms(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
    except TelegramError as exc:
        logger.warning("perm check failed in %s: %s", chat_id, exc)
        return False
    if me.status not in ("administrator", "creator"):
        return False
    for perm in REQUIRED_PERMS:
        if not getattr(me, perm, False):
            return False
    return True


async def _ensure_first_owner() -> None:
    existing = await fed_owners.find_one({})
    if existing is None:
        await fed_owners.insert_one({"user_id": INITIAL_OWNER_ID})


async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    bot_id = context.bot.id
    if not msg.new_chat_members:
        return
    if not any(m.id == bot_id for m in msg.new_chat_members):
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Join Federation", callback_data="fed_join"),
                InlineKeyboardButton("Cancel", callback_data="fed_cancel"),
            ]
        ]
    )
    try:
        await msg.reply_text(
            "Do you want this community to join the Transsion Core Federation?",
            reply_markup=keyboard,
        )
    except TelegramError as exc:
        logger.warning("Could not send affiliation prompt: %s", exc)


async def on_affiliation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    if cq is None or cq.message is None:
        return
    chat = cq.message.chat
    user = cq.from_user
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
    except TelegramError as exc:
        logger.warning("get_chat_member failed: %s", exc)
        await cq.answer("Cannot verify your role.", show_alert=True)
        return

    if member.status != ChatMember.OWNER:
        await cq.answer("Only the group owner can decide.", show_alert=True)
        return

    if cq.data == "fed_join":
        await cq.answer()
        if not await _bot_has_required_perms(context, chat.id):
            try:
                await cq.edit_message_text(PERM_HINT)
            except TelegramError:
                pass
            return

        existing = await federated_groups.find_one({"chat_id": chat.id})
        if existing and existing.get("is_active"):
            try:
                await cq.edit_message_text("Already affiliated.")
            except TelegramError:
                pass
            return

        await federated_groups.update_one(
            {"chat_id": chat.id},
            {
                "$set": {
                    "chat_id": chat.id,
                    "title": chat.title or "",
                    "added_by": user.id,
                    "added_date": utcnow(),
                    "is_active": True,
                }
            },
            upsert=True,
        )
        await _ensure_first_owner()

        try:
            await cq.edit_message_text(
                "This community is now affiliated with TCF. "
                "Federation commands can now be used here by authorized federation admins."
            )
        except TelegramError:
            pass

        await log_to_channel(
            context,
            "<b>New Affiliated Group</b>\n"
            f"{BRANDING}\n"
            f'Group: <a href="tg://user?id={chat.id}">{(chat.title or str(chat.id))}</a> '
            f"(ID: {chat.id})\n"
            f"Added by Owner: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
            f"Date: {fmt_now()}",
        )
        return

    if cq.data == "fed_cancel":
        await cq.answer()
        try:
            await cq.edit_message_text("Affiliation cancelled. Leaving the group.")
        except TelegramError:
            pass
        await log_to_channel(
            context,
            "<b>Affiliation Rejected &amp; Left</b>\n"
            f"{BRANDING}\n"
            f"Group: {chat.title or str(chat.id)} (ID: {chat.id})\n"
            f"Rejected by Owner: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
            f"Date: {fmt_now()}",
        )
        try:
            await context.bot.leave_chat(chat.id)
        except TelegramError:
            pass


async def cmd_joinfed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    if msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await msg.reply_text("This command must be used inside a group.")
        return
    user = update.effective_user
    if user is None:
        return

    try:
        member = await context.bot.get_chat_member(msg.chat.id, user.id)
    except TelegramError as exc:
        logger.warning("get_chat_member failed: %s", exc)
        await msg.reply_text("Cannot verify your role in this group.")
        return

    if member.status != ChatMember.OWNER and not await is_authorized(user.id):
        await msg.reply_text("Only the group owner can request affiliation.")
        return

    if not await _bot_has_required_perms(context, msg.chat.id):
        await msg.reply_text(PERM_HINT)
        return

    existing = await federated_groups.find_one({"chat_id": msg.chat.id})
    if existing and existing.get("is_active"):
        await msg.reply_text("Already affiliated.")
        return

    await federated_groups.update_one(
        {"chat_id": msg.chat.id},
        {
            "$set": {
                "chat_id": msg.chat.id,
                "title": msg.chat.title or "",
                "added_by": user.id,
                "added_date": utcnow(),
                "is_active": True,
            }
        },
        upsert=True,
    )
    await _ensure_first_owner()
    await msg.reply_text("This community is now affiliated with TCF.")
    await log_to_channel(
        context,
        "<b>New Affiliated Group</b>\n"
        f"{BRANDING}\n"
        f'Group: <a href="tg://user?id={msg.chat.id}">{(msg.chat.title or str(msg.chat.id))}</a> '
        f"(ID: {msg.chat.id})\n"
        f"Added by Owner: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Date: {fmt_now()}",
    )


async def cmd_defed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    if msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await msg.reply_text("This command must be used inside a federated group.")
        return
    user = update.effective_user
    if user is None:
        return

    try:
        member = await context.bot.get_chat_member(msg.chat.id, user.id)
        is_group_owner = member.status == ChatMember.OWNER
    except TelegramError:
        is_group_owner = False

    if not is_group_owner and not await is_authorized(user.id):
        await msg.reply_text("Only the group owner or federation admins can disaffiliate this group.")
        return

    record = await federated_groups.find_one({"chat_id": msg.chat.id, "is_active": True})
    if not record:
        await msg.reply_text("This group is not affiliated with TCF.")
        return

    await federated_groups.update_one({"chat_id": msg.chat.id}, {"$set": {"is_active": False}})
    await msg.reply_text("This group has been removed from the TCF federation.")
    await log_to_channel(
        context,
        "<b>Group Disaffiliated</b>\n"
        f"{BRANDING}\n"
        f"Group: {msg.chat.title or str(msg.chat.id)} (ID: {msg.chat.id})\n"
        f"Removed by: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Date: {fmt_now()}",
    )
    try:
        await context.bot.leave_chat(msg.chat.id)
    except TelegramError:
        pass


async def cmd_rmfed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await is_authorized(user.id):
        await msg.reply_text("You are not authorized.")
        return

    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await msg.reply_text("Usage: /rmfed <group_id>")
        return
    target_id = int(args[0])
    record = await federated_groups.find_one({"chat_id": target_id, "is_active": True})
    if not record:
        await msg.reply_text("Group not found or already removed.")
        return

    await federated_groups.update_one({"chat_id": target_id}, {"$set": {"is_active": False}})
    title = record.get("title") or str(target_id)
    try:
        await context.bot.leave_chat(target_id)
    except TelegramError:
        pass
    await msg.reply_text(f"Group {target_id} has been removed from the federation.")
    await log_to_channel(
        context,
        "<b>Group Disaffiliated</b>\n"
        f"{BRANDING}\n"
        f"Group: {title} (ID: {target_id})\n"
        f"Removed by: {user_link(user.id, safe_first_name(user))} (ID: {user.id})\n"
        f"Date: {fmt_now()}",
    )


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    upd = update.my_chat_member
    if upd is None:
        return
    new_status = upd.new_chat_member.status
    if new_status not in ("kicked", "left"):
        return
    chat = upd.chat
    record = await federated_groups.find_one({"chat_id": chat.id, "is_active": True})
    if not record:
        return
    await federated_groups.update_one({"chat_id": chat.id}, {"$set": {"is_active": False}})
    await log_to_channel(
        context,
        "<b>Group Removed Bot</b>\n"
        f"{BRANDING}\n"
        f"Group: {chat.title or str(chat.id)} (ID: {chat.id})\n"
        f"Date: {fmt_now()}",
    )
