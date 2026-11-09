# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation ban command entry point: validates permissions and starts the ban flow."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import BanDoc
from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.keyboards import ban_update_confirm_kb
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.pipelines.ban_flow import (
    BAN_USER_DATA_KEYS,
    WAITING_PROOF,
    WAITING_UPDATE_CONFIRM,
    ban_conversation,
    proof_prompt_content,
)
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.modules.helper.pipelines.reason_flow import (
    is_reason_too_long,
    parse_inline_reason,
    reason_too_long_text,
)
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Message, Update

log = get_logger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #
# * Ban runtime prose lives in banning.toml; no constants stay here.

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 3


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Ban"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("banning.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("banning.help.commands.body", locale),
        ),
        replies.who_section(replies.perm_dev_above(locale, plain=False), locale),
        replies.where_section(replies.context_exec_or_group(locale), locale),
        (
            replies.sec_what(locale),
            t("banning.help.what.body", locale),
        ),
        (
            replies.sec_flow(locale),
            t("banning.help.flow.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("banning.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ────────────────────── Command Ban </tcban> ────────────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.mod_only
@decorators.log_execution
async def cmd_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the federation ban flow.

    Resolves the target, validates the inline reason, runs identity and role
    checks in parallel, then either asks for re-ban confirmation (active ban
    exists) or demotes any federation role held by the target. Stores
    ban metadata in ``user_data`` and shows the proof prompt. Returns
    ``WAITING_UPDATE_CONFIRM``, ``WAITING_PROOF``, or
    ``ConversationHandler.END`` on any failure.
    """
    resolved = await decorators.resolve_mod_target(
        update,
        ctx,
        action="ban",
        min_role="developer",
        allow_private=True,
        log_prefix="cmd_ban_start",
    )
    if resolved is None or ctx.user_data is None:
        return ConversationHandler.END
    # * Private stays allowed (exec-or-group scope per help); a disconnected
    # * group never drives federation-wide enforcement.
    msg = resolved.msg
    admin = resolved.admin
    locale = resolved.locale
    target_id = resolved.target_id
    target_fname = resolved.target_name
    has_explicit_target = resolved.has_explicit_target
    raw_args = resolved.args
    target_role = resolved.target_role

    ban_reason = parse_inline_reason(
        raw_args,
        has_explicit_target=has_explicit_target,
        # * Reply path only: a leading numeric token equal to the replied-to
        # * user is the ID restated, not reason text (None otherwise, so the
        # * explicit path can never strip a reason token that happens to match).
        reply_target_id=target_id if not has_explicit_target else None,
    )

    if not ban_reason:
        await safe_reply(
            msg,
            t("banning.error.reason_required", locale, plain=True),
            log_label="cmd_ban_start no-reason",
            parse_mode=None,
        )
        return ConversationHandler.END

    # * Fail fast on overlong inline reasons with the same cap and text as
    # * the typed-reason path, before any role I/O or demote work.
    if is_reason_too_long(ban_reason):
        await safe_reply(
            msg,
            reason_too_long_text(len(ban_reason), locale),
            log_label="cmd_ban_start reason-too-long",
            parse_mode=None,
        )
        return ConversationHandler.END

    ctx.user_data["ban_target_id"] = target_id
    ctx.user_data["ban_target_fname"] = target_fname or str(target_id)
    ctx.user_data["ban_reason"] = ban_reason
    ctx.user_data["ban_admin_id"] = admin.id
    ctx.user_data["ban_admin_fname"] = admin.first_name
    ctx.user_data["ban_locale"] = locale

    # * Re-ban check before any side effect: demotion must not land when
    # * the admin may still cancel at the confirmation below. A lookup
    # * outage fails closed with a retry reply instead of degrading to
    # * a fresh ban that wastes a proof round before the executor aborts.
    try:
        existing = await db.bans_db.get_active_ban(target_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("cmd_ban_start active-ban lookup failed for target=%d", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="cmd_ban_start lookup-failed",
            parse_mode=None,
        )
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END

    if existing is not None:
        ctx.user_data["ban_target_role"] = target_role
        return await _ask_update_confirm(
            msg,
            ctx,
            target_id,
            target_fname,
            ban_reason,
            existing,
            update,
            locale=locale,
        )

    # * Demote is required before the ban to preserve the
    # * role-vs-state invariant: a banned user must not still hold a
    # * federation role. The helper replies and signals abort when the
    # * demote fails, so the ban never proceeds on a role holder.
    if target_role and not await Demote.execute(
        ctx.bot,
        target_id,
        target_fname or str(target_id),
        target_role,
        admin.id,
        admin.first_name,
        trigger="ban",
        msg=msg,
    ):
        return ConversationHandler.END

    text, kb = proof_prompt_content(
        target_id, target_fname or str(target_id), ban_reason, locale
    )
    try:
        prompt = await msg.reply_text(text, parse_mode="MarkdownV2", reply_markup=kb)
        ctx.user_data["ban_prompt_msg_id"] = prompt.message_id
        ctx.user_data["ban_prompt_chat_id"] = msg.chat.id
    except Exception as exc:
        log.debug("cmd_ban_start proof-prompt reply failed: %s", exc)
        for key in BAN_USER_DATA_KEYS:
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
    update: Update,
    locale: str | None = None,
) -> int:
    """Show the re-ban confirmation card with log/proof links.

    Returns ``WAITING_UPDATE_CONFIRM`` with the prompt IDs stored, or
    ``ConversationHandler.END`` when the prompt cannot be delivered
    (with the stored metadata cleaned up).
    """
    if ctx.user_data is None:
        return ConversationHandler.END
    if locale is None:
        locale = await locale_for_update(update)
    logs_chat, logs_thread = cfg.logs
    proofs_chat, proofs_thread = cfg.proofs
    log_msg_id = int(existing.get("log_message_id", 0) or 0)
    proof_msg_id = int(existing.get("proof_message_id", 0) or 0)
    kb = ban_update_confirm_kb(
        message_link(logs_chat, log_msg_id, logs_thread) if log_msg_id else None,
        message_link(proofs_chat, proof_msg_id, proofs_thread)
        if proof_msg_id
        else None,
        locale,
    )
    text = t(
        "banning.confirm.body",
        locale,
        user=Safe(user_ref(target_id, target_fname or str(target_id))),
        ban_id=Safe(code(str(existing.get("ban_id", "")))),
        old_reason=str(existing.get("reason", "")),
        new_reason=ban_reason,
    )
    try:
        prompt = await msg.reply_text(text, parse_mode="MarkdownV2", reply_markup=kb)
        ctx.user_data["ban_prompt_msg_id"] = prompt.message_id
        ctx.user_data["ban_prompt_chat_id"] = msg.chat.id
    except Exception as exc:
        log.debug("cmd_ban_start confirm-prompt reply failed: %s", exc)
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_UPDATE_CONFIRM


# ──────────────────────────── Handlers ──────────────────────────── #

_BAN_CMDS = build_prefixed_filters("tcban") | build_prefixed_filters("tcb")

__handlers__ = [ban_conversation(cmd_ban_start, _BAN_CMDS)]
