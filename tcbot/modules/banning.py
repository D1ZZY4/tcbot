# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation ban command entry point: validates permissions and starts the ban flow."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import BanDoc
from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.keyboards import ban_update_confirm_kb
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.workflows.ban_flow import (
    WAITING_PROOF,
    WAITING_UPDATE_CONFIRM,
    ban_conversation,
    demote_ban_target,
    proof_prompt_content,
)
from tcbot.modules.helper.workflows.reason_flow import (
    is_reason_too_long,
    parse_inline_reason,
    reason_too_long_text,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import code, esc, mention
from tcbot.utils.i18n import t
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Message, Update

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #

_ERR_REASON_REQUIRED = "A reason is required - /tcban <target> <reason>."

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 3


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Ban"
__help_text__ = t("ban.help.overview")

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        t("ban.help.commands.body"),
    ),
    replies.who_section(replies.PERM_DEV_ABOVE),
    replies.where_section(replies.CONTEXT_EXEC_OR_GROUP),
    (
        replies.SEC_WHAT,
        t("ban.help.what.body"),
    ),
    (
        "Flow",
        t("ban.help.flow.body"),
    ),
    replies.target_section(),
    (
        replies.SEC_EXAMPLES,
        t("ban.help.examples.body"),
    ),
]

__help__: replies.HelpEntry = {
    "name": __module_name__,
    "overview": __help_text__,
    "sections": __help_sections__,
}


# ────────────────────── Command Ban </tcban> ────────────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.mod_only
@decorators.log_execution
async def cmd_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the federation ban flow.

    Resolves the target, validates the inline reason, runs identity and role
    checks in parallel, then either asks for re-ban confirmation (active ban
    exists) or auto-demotes any federation role held by the target. Stores
    ban metadata in ``user_data`` and shows the proof prompt. Returns
    ``WAITING_UPDATE_CONFIRM``, ``WAITING_PROOF``, or
    ``ConversationHandler.END`` on any failure.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None or ctx.user_data is None:
        return ConversationHandler.END
    raw_args = parse_cmd_args(msg.text)

    # * Single owner for the reply-wins plus shape check: with a reply
    # * target every arg is reason text, otherwise a leading numeric ID or
    # * @username token is the explicit target. Sync, so no I/O cost here.
    has_explicit_target = extraction.has_explicit_target(msg, raw_args)
    target_id, target_fname = await extraction.extract_target(update, raw_args, ctx.bot)

    ban_reason = parse_inline_reason(
        raw_args,
        has_explicit_target=has_explicit_target,
        # * Reply path only: a leading numeric token equal to the replied-to
        # * user is the ID restated, not reason text (None otherwise, so the
        # * explicit path can never strip a reason token that happens to match).
        reply_target_id=target_id if not has_explicit_target else None,
    )

    if not target_id:
        await safe_reply(
            msg,
            replies.ERR_CANNOT_RESOLVE,
            log_label="cmd_ban_start no-target",
            parse_mode=None,
        )
        return ConversationHandler.END

    if not ban_reason:
        await safe_reply(
            msg,
            _ERR_REASON_REQUIRED,
            log_label="cmd_ban_start no-reason",
            parse_mode=None,
        )
        return ConversationHandler.END

    # * Fail fast on overlong inline reasons with the same cap and text as
    # * the typed-reason path, before any role I/O or demote work.
    if is_reason_too_long(ban_reason):
        await safe_reply(
            msg,
            reason_too_long_text(len(ban_reason)),
            log_label="cmd_ban_start reason-too-long",
            parse_mode=None,
        )
        return ConversationHandler.END

    # * Identity check + role lookup happen in parallel; both depend only on
    # * already-resolved IDs so there is no need to wait for them sequentially.
    # * return_exceptions=True prevents a DB failure from leaving the ConversationHandler open.
    ident, role_result = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_fname),
        resolve_and_check(msg, admin.id, target_id, min_role="developer"),
        return_exceptions=True,
    )
    throw_if_cancelled((ident, role_result))
    if isinstance(ident, BaseException):
        log.exception("identity.classify failed in cmd_ban_start: %s", ident)
        return ConversationHandler.END
    if isinstance(role_result, BaseException):
        log.exception("resolve_and_check failed in cmd_ban_start: %s", role_result)
        return ConversationHandler.END
    # * isinstance + early return above already narrows role_result to the
    # * success tuple; no assert needed (asserts vanish under python -O).
    executor_role, target_role = role_result
    # * Guard first: if resolve_and_check already replied and rejected (e.g. target
    # * outranks executor), skip the identity refusal to avoid sending two replies.
    if executor_role is None:
        return ConversationHandler.END

    refusal = identity.refuse_message("ban", ident)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_ban_start refusal")
        return ConversationHandler.END

    ctx.user_data["ban_target_id"] = target_id
    ctx.user_data["ban_target_fname"] = target_fname or str(target_id)
    ctx.user_data["ban_reason"] = ban_reason
    ctx.user_data["ban_admin_id"] = admin.id
    ctx.user_data["ban_admin_fname"] = admin.first_name

    # * Re-ban check before any side effect: demotion must not land when
    # * the admin may still cancel at the confirmation below. A lookup
    # * outage degrades to the old straight-to-proof path; the executor
    # * re-checks and stays fail-closed downstream.
    try:
        existing = await db.bans_db.get_active_ban(target_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("cmd_ban_start active-ban lookup failed; proceeding as fresh ban")
        existing = None

    if existing is not None:
        ctx.user_data["ban_target_role"] = target_role
        return await _ask_update_confirm(
            msg, ctx, target_id, target_fname, ban_reason, existing
        )

    # * Auto-demote is required before the ban to preserve the
    # * role-vs-state invariant: a banned user must not still hold a
    # * federation role. The helper replies and signals abort when the
    # * demote fails, so the ban never proceeds on a role holder.
    if not await demote_ban_target(
        msg,
        ctx.bot,
        target_id,
        target_fname or str(target_id),
        target_role,
        admin.id,
        admin.first_name,
    ):
        return ConversationHandler.END

    text, kb = proof_prompt_content(
        target_id, target_fname or str(target_id), ban_reason
    )
    try:
        prompt = await msg.reply_text(text, parse_mode="MarkdownV2", reply_markup=kb)
        ctx.user_data["ban_prompt_msg_id"] = prompt.message_id
        ctx.user_data["ban_prompt_chat_id"] = msg.chat.id
    except Exception as exc:
        log.debug("cmd_ban_start proof-prompt reply failed: %s", exc)
        for key in (
            "ban_target_id",
            "ban_target_fname",
            "ban_reason",
            "ban_admin_id",
            "ban_admin_fname",
            "ban_target_role",
        ):
            ctx.user_data.pop(key, None)
        return ConversationHandler.END

    return WAITING_PROOF


async def _ask_update_confirm(
    msg: Message,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_fname: str | None,
    ban_reason: str,
    existing: BanDoc,
) -> int:
    """Show the re-ban confirmation card with log/proof links.

    Returns ``WAITING_UPDATE_CONFIRM`` with the prompt IDs stored, or
    ``ConversationHandler.END`` when the prompt cannot be delivered
    (with the stored metadata cleaned up).
    """
    if ctx.user_data is None:
        return ConversationHandler.END
    logs_chat, logs_thread = cfg.logs
    proofs_chat, proofs_thread = cfg.proofs
    log_msg_id = int(existing.get("log_message_id", 0) or 0)
    proof_msg_id = int(existing.get("proof_message_id", 0) or 0)
    kb = ban_update_confirm_kb(
        message_link(logs_chat, log_msg_id, logs_thread) if log_msg_id else None,
        message_link(proofs_chat, proof_msg_id, proofs_thread)
        if proof_msg_id
        else None,
    )
    text = (
        f"{mention(target_id, target_fname or str(target_id))} already has an "
        f"active federation ban \\(Ban ID {code(str(existing.get('ban_id', '')))}\\)\\.\n"
        f"Existing reason: {esc(str(existing.get('reason', '')))}\n"
        f"New reason: {esc(ban_reason)}\n\n"
        "Update the ban with the new reason and proof?"
    )
    try:
        prompt = await msg.reply_text(text, parse_mode="MarkdownV2", reply_markup=kb)
        ctx.user_data["ban_prompt_msg_id"] = prompt.message_id
        ctx.user_data["ban_prompt_chat_id"] = msg.chat.id
    except Exception as exc:
        log.debug("cmd_ban_start confirm-prompt reply failed: %s", exc)
        for key in (
            "ban_target_id",
            "ban_target_fname",
            "ban_reason",
            "ban_admin_id",
            "ban_admin_fname",
            "ban_target_role",
        ):
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_UPDATE_CONFIRM


# ──────────────────────────── Handlers ──────────────────────────── #

_BAN_CMDS = build_prefixed_filters("tcban") | build_prefixed_filters("tcb")

__handlers__ = [ban_conversation(cmd_ban_start, _BAN_CMDS)]
