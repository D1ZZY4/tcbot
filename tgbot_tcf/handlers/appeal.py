# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Appeal handlers (PROMPT Features 7, 8).

Telegram update plumbing only — the parsing rules, the 12-hour reviewer
rule, all DB writes, and the two channel postings live in
:mod:`tgbot_tcf.modules.appeals`.
"""
import logging
from typing import Any, Dict, Optional

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from .. import APPEAL_INSTRUCTION_TEMPLATE
from ..modules import appeals, bans, keyboards, log_templates
from ..modules.messages import M
from ..utils.format import safe_first_name, user_link
from ..utils.logger import edit_log_message, log_to_channel
from ..utils.users import resolve_identity
from .helper import auth, enforce_unban_across_groups, messaging

logger = logging.getLogger(__name__)


def _get_sessions(context: ContextTypes.DEFAULT_TYPE) -> Dict[Any, Any]:
    """In-memory map of ``user_id`` to the appeal session metadata."""
    return context.application.bot_data.setdefault("appeal_sessions", {})


# -------------------------------------------------------- /start appeal_<id>

async def start_appeal(
    update: Update, context: ContextTypes.DEFAULT_TYPE, ban_id: str
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    if msg.chat.type != ChatType.PRIVATE:
        await msg.reply_text(M.APPEAL_PRIVATE_ONLY)
        return

    record = await bans.find_by_ban_id(ban_id)
    if not record or not record.get("is_active"):
        await msg.reply_text(M.INVALID_OR_EXPIRED_BAN)
        return

    sent = await msg.reply_text(
        APPEAL_INSTRUCTION_TEMPLATE.format(ban_id=ban_id),
        reply_markup=keyboards.appeal_cancel(),
        disable_web_page_preview=True,
    )

    sessions = _get_sessions(context)
    sessions[user.id] = {
        "ban_id": ban_id,
        "log_message_id": record["log_message_id"],
        "instruction_msg_id": sent.message_id,
        "chat_id": msg.chat.id,
    }


# ----------------------------------------------------------- session control

async def on_cancel_appeal(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    cq = update.callback_query
    if cq is None or cq.message is None or getattr(cq, "from_user", None) is None:
        return
    sessions: Dict[Any, Any] = _get_sessions(context)
    sessions.pop(cq.from_user.id, None)
    await cq.answer()
    await messaging.safe_edit_callback(cq, M.APPEAL_CANCELLED, parse_mode=None)


# ------------------------------------------------------ #appeal submission

async def on_appeal_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    if msg.chat.type != ChatType.PRIVATE:
        return

    sessions: Dict[Any, Any] = _get_sessions(context)
    sess: Optional[Dict[str, Any]] = sessions.get(user.id)
    if sess is None:
        return

    text = msg.text or ""
    if not appeals.starts_with_appeal_tag(text):
        return

    if not appeals.text_references_log_message(text, sess["log_message_id"]):
        await msg.reply_text(M.APPEAL_INVALID_LOG_LINK)
        return

    posted = await appeals.post_appeal_text(context, text)
    if posted is None:
        await msg.reply_text(M.APPEAL_SUBMIT_FAILED)
        return
    _, appeal_link = posted

    ban_id = sess["ban_id"]
    submitted_at = appeals.now()

    review_msg_id = await appeals.post_review_message(
        context,
        user_id=user.id,
        user_name=safe_first_name(user),
        ban_id=ban_id,
        appeal_link=appeal_link,
        submitted_at=submitted_at,
    )
    if review_msg_id is None:
        await msg.reply_text(M.APPEAL_SUBMIT_FAILED)
        return

    await appeals.attach_review_metadata(
        ban_id=ban_id,
        review_message_id=review_msg_id,
        when=submitted_at,
    )
    await messaging.safe_edit_text(
        context,
        chat_id=sess["chat_id"],
        message_id=sess["instruction_msg_id"],
        text=M.APPEAL_SUBMITTED,
        parse_mode=None,
    )
    sessions.pop(user.id, None)

    appeal_log_msg_id = await log_to_channel(
        context,
        log_templates.appeal_submitted(
            user_id=user.id,
            user_name=safe_first_name(user),
            ban_id=ban_id,
            appeal_link=appeal_link,
            submitted_at=submitted_at,
        ),
    )
    if appeal_log_msg_id is not None:
        await appeals.remember_appeal_log_message(
            ban_id=ban_id,
            appeal_log_message_id=appeal_log_msg_id,
        )


# ----------------------------------------------------------- review buttons

async def on_appeal_review(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    cq = update.callback_query
    if (
        cq is None
        or cq.message is None
        or getattr(cq, "from_user", None) is None
        or getattr(cq, "data", None) is None
    ):
        return

    data = str(cq.data)
    if data.startswith("appeal_approve_"):
        decision = "approve"
        ban_id = data[len("appeal_approve_"):]
    elif data.startswith("appeal_reject_"):
        decision = "reject"
        ban_id = data[len("appeal_reject_"):]
    else:
        return

    reviewer = cq.from_user
    if not await auth.is_authorized(reviewer.id):
        await cq.answer(M.NOT_AUTHORIZED, show_alert=True)
        return

    record = await bans.find_by_ban_id(ban_id)
    if not record or not record.get("is_active"):
        await cq.answer(M.APPEAL_BAN_INACTIVE_ALERT, show_alert=True)
        await messaging.safe_edit_callback(cq, M.APPEAL_RESOLVED_ALREADY_INACTIVE)
        return

    if appeals.reviewer_locked_out(
        review_timestamp=record.get("review_timestamp"),
        ban_admin_id=record.get("admin_user_id"),
        reviewer_id=reviewer.id,
    ):
        await cq.answer(M.APPEAL_TWELVE_HOUR_RULE_ALERT, show_alert=True)
        return

    await cq.answer()

    appellant_id = record["banned_user_id"]
    appellant = await resolve_identity(context, appellant_id)
    reviewer_link = user_link(reviewer.id, safe_first_name(reviewer))

    appeal_log_msg_id = record.get("appeal_log_message_id")

    if decision == "approve":
        # 1. Cross-group unban first — this is the action the user is paying for.
        enforce_success, enforce_failure = await enforce_unban_across_groups(
            context, appellant_id
        )
        # 2. Mark the ban inactive so further appeals / commands see it resolved.
        await appeals.mark_resolved_inactive(ban_id)
        # 3. Update the in-group review message so admins see who approved.
        await messaging.safe_edit_callback(
            cq, M.APPEAL_DECISION_APPROVED.format(reviewer_link=reviewer_link)
        )
        # 4. Edit the original "New Appeal Submitted" log post in place.
        approved_log_text = log_templates.appeal_approved(
            user_id=appellant_id,
            user_name=appellant.display_name,
            ban_id=ban_id,
            reviewer_id=reviewer.id,
            reviewer_name=safe_first_name(reviewer),
        )
        edited = False
        if appeal_log_msg_id:
            edited = await edit_log_message(
                context, appeal_log_msg_id, approved_log_text
            )
        if not edited:
            logger.warning(
                "Could not edit appeal log %s; posting as new message",
                appeal_log_msg_id,
            )
            await log_to_channel(context, approved_log_text)
        # 5. Send the standalone unban log entry with cross-group summary.
        unban_log_text = log_templates.unban(
            admin_id=reviewer.id,
            admin_name=safe_first_name(reviewer),
            target_id=appellant_id,
            target_name=appellant.display_name,
            reason="Appeal Approved",
        )
        unban_log_text += log_templates.enforcement_summary(
            success=enforce_success,
            failure=enforce_failure,
            action="Unbanned",
        )
        await log_to_channel(context, unban_log_text)
        # 6. Notify the appellant.
        await messaging.safe_send_dm(
            context, user_id=appellant_id, text=M.APPEAL_NOTIFY_USER_APPROVED
        )
    else:
        # 1. Mark the ban inactive (rejection still resolves the appeal).
        await appeals.mark_resolved_inactive(ban_id)
        # 2. Update the in-group review message.
        await messaging.safe_edit_callback(
            cq, M.APPEAL_DECISION_REJECTED.format(reviewer_link=reviewer_link)
        )
        # 3. Edit the original log post in place — no separate message.
        rejected_log_text = log_templates.appeal_rejected(
            user_id=appellant_id,
            user_name=appellant.display_name,
            ban_id=ban_id,
            reviewer_id=reviewer.id,
            reviewer_name=safe_first_name(reviewer),
        )
        edited = False
        if appeal_log_msg_id:
            edited = await edit_log_message(
                context, appeal_log_msg_id, rejected_log_text
            )
        if not edited:
            logger.warning(
                "Could not edit appeal log %s; posting as new message",
                appeal_log_msg_id,
            )
            await log_to_channel(context, rejected_log_text)
        # 4. Notify the appellant.
        await messaging.safe_send_dm(
            context, user_id=appellant_id, text=M.APPEAL_NOTIFY_USER_REJECTED
        )
