# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group kick command entry point: validates permissions and delegates to kicking_flow."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.kicking_flow import kick_conversation, proof, reason
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    is_reason_too_long,
    parse_inline_reason,
    reason_too_long_text,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import mention
from tcbot.utils.i18n import t
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 5


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Kick"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("kicking.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("kicking.help.commands.body", locale),
        ),
        replies.who_section(replies.perm_tester_above(locale, plain=False), locale),
        replies.where_section(replies.where_connected_group(locale), locale),
        (
            replies.sec_what(locale),
            t("kicking.help.what.body", locale),
        ),
        (
            "Flow",
            t("kicking.help.flow.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("kicking.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ───────────────────── Command Kick </tckick> ───────────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the kick flow.

    Resolves the target, runs identity and role checks in parallel, auto-demotes
    any federation role, then either executes an immediate kick (with inline
    reason) or opens the reason/proof conversation. Returns
    ``ConversationHandler.END`` on validation failure.
    """
    locale = await locale_for_update(update)
    msg = update.effective_message
    admin = update.effective_user
    chat = update.effective_chat
    if msg is None or admin is None or chat is None or ctx.user_data is None:
        return ConversationHandler.END

    # * Kick is a current-chat ban-then-unban: Telegram rejects it in private
    # * chats ("Can't ban members in private chats"), so refuse up front
    # * instead of failing in the executor after role I/O and demote work.
    # * Mirrors the connecting/disconnecting group-only guards.
    if chat.type == "private":
        await safe_reply(
            msg,
            replies.err_group_only(locale, plain=True),
            log_label="cmd_kick group-only",
            parse_mode=None,
        )
        return ConversationHandler.END

    args = parse_cmd_args(msg.text)
    # * Resolution plus consumption in one call (see banning.py): a
    # * verified explicit ID/@username overrides the reply target, and the
    # * consumed flag tells the reason parser to drop args[0] as target.
    (target_id, target_name), has_explicit_target = await extraction.extract_mod_target(
        update, args, ctx.bot
    )

    inline_reason = parse_inline_reason(
        args,
        has_explicit_target=has_explicit_target,
        # * Reply path only (see banning.py): strip a restated target ID.
        reply_target_id=target_id if not has_explicit_target else None,
    )

    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="cmd_kick no-target",
            parse_mode=None,
        )
        return ConversationHandler.END

    # * Fail fast on overlong inline reasons with the shared cap and text,
    # * before any role I/O or demote work.
    if inline_reason and is_reason_too_long(inline_reason):
        await safe_reply(
            msg,
            reason_too_long_text(len(inline_reason), locale),
            log_label="cmd_kick reason-too-long",
            parse_mode=None,
        )
        return ConversationHandler.END

    # * return_exceptions=True prevents a DB failure from leaving the ConversationHandler open.
    ident, role_result = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_name),
        resolve_and_check(msg, admin.id, target_id, min_role="tester"),
        return_exceptions=True,
    )
    throw_if_cancelled((ident, role_result))
    if isinstance(ident, BaseException):
        log.exception("identity.classify failed in cmd_kick: %s", ident)
        return ConversationHandler.END
    if isinstance(role_result, BaseException):
        log.exception("resolve_and_check failed in cmd_kick: %s", role_result)
        return ConversationHandler.END
    # * isinstance + early return above already narrows role_result to the
    # * success tuple; no assert needed (asserts vanish under python -O).
    executor_role, target_role = role_result
    # * Guard first: if resolve_and_check already replied and rejected (e.g. target
    # * outranks executor), skip the identity refusal to avoid sending two replies.
    if executor_role is None:
        return ConversationHandler.END

    refusal = identity.refuse_message("kick", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_kick refusal")
        return ConversationHandler.END

    # * Auto-demote must succeed before the kick to preserve the
    # * role-vs-state invariant. The helper replies and signals abort
    # * when the demote fails, so the kick never proceeds on a role holder.
    if target_role and not await Demote.auto_demote_or_abort(
        msg,
        ctx.bot,
        target_id,
        target_name or str(target_id),
        target_role,
        admin.id,
        admin.first_name,
        trigger="kick",
    ):
        return ConversationHandler.END

    ctx.user_data.update(
        {
            "kick_target_id": target_id,
            "kick_target_name": target_name or str(target_id),
            "kick_prompt_chat": msg.chat.id,
        }
    )

    target_mention = mention(target_id, target_name or str(target_id))

    _KICK_KEYS = (
        "kick_target_id",
        "kick_target_name",
        "kick_prompt_chat",
        "kick_prompt_id",
    )

    if inline_reason:
        ctx.user_data["kick_reason"] = inline_reason
        try:
            prompt = await msg.reply_text(
                proof.noted_prompt(
                    "kick", inline_reason, target_mention, locale=locale
                ),
                parse_mode="MarkdownV2",
                reply_markup=proof.keyboard(locale),
            )
            ctx.user_data["kick_prompt_id"] = prompt.message_id
        except Exception as exc:
            log.debug("cmd_kick proof-prompt reply failed: %s", exc)
            for key in (*_KICK_KEYS, "kick_reason"):
                ctx.user_data.pop(key, None)
            return ConversationHandler.END
        return WAITING_PROOF

    try:
        prompt = await msg.reply_text(
            reason.prompt(target_mention, "kick", locale=locale),
            parse_mode="MarkdownV2",
            reply_markup=reason.keyboard(locale),
        )
        ctx.user_data["kick_prompt_id"] = prompt.message_id
    except Exception as exc:
        log.debug("cmd_kick reason-prompt reply failed: %s", exc)
        for key in _KICK_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_REASON


# ──────────────────────────── Handlers ──────────────────────────── #

_KICK_CMDS = build_prefixed_filters("tckick") | build_prefixed_filters("tck")

__handlers__ = [kick_conversation(cmd_kick, _KICK_CMDS)]
