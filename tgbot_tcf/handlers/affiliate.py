# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Group affiliation handlers (PROMPT Features 1, 2, 3, 4).

The handlers here only read updates and reply with the right copy. The DB
writes, permission checks, log entries and member-cache seeding all live in
:mod:`tgbot_tcf.modules.affiliations`.
"""
import logging

from telegram import ChatMember, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import groups_repo, joins_repo
from ..modules import affiliations, keyboards, log_templates
from ..modules.affiliations import REQUIRED_PERMS  # re-export for backward compat
from ..modules.messages import M
from ..utils.format import safe_first_name
from ..utils.logger import log_to_channel
from ..utils.users import resolve_identity
from .helper import auth, messaging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------- bot added to group

async def on_new_chat_members(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send the affiliation prompt the first time the bot is added."""
    msg = update.effective_message
    if msg is None or msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    members = msg.new_chat_members or []
    if not any(m.id == context.bot.id for m in members):
        return
    try:
        await msg.reply_text(
            M.AFFILIATION_PROMPT,
            reply_markup=keyboards.affiliation_prompt(),
        )
    except TelegramError as exc:
        logger.warning("Could not send affiliation prompt: %s", exc)


# ------------------------------------------------------- affiliation buttons

async def on_affiliation_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the ``Join Transsion Core`` / ``Cancel`` buttons."""
    cq = update.callback_query
    if cq is None or cq.message is None:
        return
    chat = cq.message.chat
    user = cq.from_user

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
    except TelegramError as exc:
        logger.warning("get_chat_member failed: %s", exc)
        await cq.answer(M.AFFILIATION_VERIFY_ROLE_FAIL, show_alert=True)
        return

    if member.status != ChatMember.OWNER:
        await cq.answer(M.AFFILIATION_OWNER_ONLY_ALERT, show_alert=True)
        return

    if cq.data == "tc_join":
        await cq.answer()
        if await affiliations.is_active(chat.id):
            await messaging.safe_edit_callback(cq, M.ALREADY_AFFILIATED, parse_mode=None)
            return

        if not await affiliations.bot_has_required_perms(context, chat.id):
            await messaging.safe_edit_callback(cq, M.PERMS_NEEDED, parse_mode=None)
            await affiliations.record_pending(
                chat_id=chat.id,
                title=chat.title or str(chat.id),
                requested_by=user.id,
                notice_message_id=cq.message.message_id,
            )
            return

        await affiliations.finalize_affiliation(
            context,
            chat_id=chat.id,
            title=chat.title or str(chat.id),
            added_by=user.id,
            added_by_name=safe_first_name(user),
        )
        await messaging.safe_edit_callback(
            cq, M.AFFILIATION_SUCCESS, parse_mode=None
        )
        return

    if cq.data == "tc_cancel":
        await cq.answer()
        await messaging.safe_edit_callback(
            cq, M.AFFILIATION_CANCELLED, parse_mode=None
        )
        await joins_repo.delete(chat.id)
        await log_to_channel(
            context,
            log_templates.affiliation_rejected(
                title=chat.title or str(chat.id),
                chat_id=chat.id,
                owner_id=user.id,
                owner_name=safe_first_name(user),
            ),
        )
        try:
            await context.bot.leave_chat(chat.id)
        except TelegramError:
            pass


# ---------------------------------------------------------- explicit /jointc

async def cmd_joinfed(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.effective_message
    if msg is None:
        return
    if msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await msg.reply_text(M.AFFILIATION_GROUPS_ONLY)
        return
    user = update.effective_user
    if user is None:
        return

    if not await auth.is_authorized(user.id):
        try:
            member = await context.bot.get_chat_member(msg.chat.id, user.id)
            is_group_owner = member.status == ChatMember.OWNER
        except TelegramError:
            is_group_owner = False
        if not is_group_owner:
            await msg.reply_text(M.AFFILIATION_GROUP_OWNER_ONLY)
            return

    if await affiliations.is_active(msg.chat.id):
        await msg.reply_text(M.ALREADY_AFFILIATED)
        return

    if not await affiliations.bot_has_required_perms(context, msg.chat.id):
        sent = await msg.reply_text(M.PERMS_NEEDED)
        await affiliations.record_pending(
            chat_id=msg.chat.id,
            title=msg.chat.title or str(msg.chat.id),
            requested_by=user.id,
            notice_message_id=sent.message_id,
        )
        return

    await affiliations.finalize_affiliation(
        context,
        chat_id=msg.chat.id,
        title=msg.chat.title or str(msg.chat.id),
        added_by=user.id,
        added_by_name=safe_first_name(user),
    )
    await msg.reply_text(M.AFFILIATION_SUCCESS_SHORT)


# ----------------------------------------------------------------- /detc

async def cmd_defed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    if msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await msg.reply_text(M.AFFILIATION_FED_GROUPS_ONLY)
        return
    user = update.effective_user
    if user is None:
        return

    if not await affiliations.is_active(msg.chat.id):
        await msg.reply_text(M.GROUP_NOT_AFFILIATED)
        return

    try:
        member = await context.bot.get_chat_member(msg.chat.id, user.id)
        is_group_owner = member.status == ChatMember.OWNER
    except TelegramError:
        is_group_owner = False

    if not is_group_owner and not await auth.is_authorized(user.id):
        await msg.reply_text(M.DEFED_NOT_ALLOWED)
        return

    title = msg.chat.title or str(msg.chat.id)
    await affiliations.deactivate_group(msg.chat.id)
    await msg.reply_text(M.GROUP_DISAFFILIATED)
    await log_to_channel(
        context,
        log_templates.group_disaffiliated(
            title=title,
            chat_id=msg.chat.id,
            by_user_id=user.id,
            by_user_name=safe_first_name(user),
        ),
    )
    try:
        await context.bot.leave_chat(msg.chat.id)
    except TelegramError:
        pass


# ----------------------------------------------------------------- /rmtc

async def cmd_rmfed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_authorized(msg, user.id):
        return

    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await msg.reply_text(M.REMOVE_USAGE)
        return

    target_id = int(args[0])
    record = await groups_repo.find_active(target_id)
    if record is None:
        await msg.reply_text(M.REMOVE_NOT_FOUND)
        return

    title = record.get("title") or str(target_id)
    await affiliations.deactivate_group(target_id)
    try:
        await context.bot.leave_chat(target_id)
    except TelegramError:
        pass
    await msg.reply_text(M.REMOVE_OK.format(group_id=target_id))
    await log_to_channel(
        context,
        log_templates.group_disaffiliated(
            title=title,
            chat_id=target_id,
            by_user_id=user.id,
            by_user_name=safe_first_name(user),
        ),
    )


# ------------------------------------------------------- my_chat_member sink

async def on_my_chat_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle bot status changes: removal and promotion-to-admin."""
    upd = update.my_chat_member
    if upd is None:
        return
    chat = upd.chat
    new = upd.new_chat_member
    new_status = new.status

    if new_status in ("kicked", "left"):
        if await affiliations.is_active(chat.id):
            await affiliations.deactivate_group(chat.id)
            await log_to_channel(
                context,
                log_templates.group_removed_bot(
                    title=chat.title or str(chat.id), chat_id=chat.id
                ),
            )
        await joins_repo.delete(chat.id)
        return

    if not affiliations.has_required_perms(new):
        return

    pending = await joins_repo.get(chat.id)
    if not pending:
        return

    requested_by = pending.get("requested_by", 0)
    requested_by_name = (await resolve_identity(context, requested_by)).display_name
    title = chat.title or pending.get("title") or str(chat.id)

    await affiliations.finalize_affiliation(
        context,
        chat_id=chat.id,
        title=title,
        added_by=requested_by,
        added_by_name=requested_by_name,
    )

    notice_id = pending.get("notice_message_id")
    if notice_id:
        edited = await messaging.safe_edit_text(
            context,
            chat_id=chat.id,
            message_id=notice_id,
            text=M.AFFILIATION_AUTO_COMPLETED,
            parse_mode=None,
        )
        if not edited:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=M.AFFILIATION_AUTO_COMPLETED_SHORT,
                )
            except TelegramError:
                pass
