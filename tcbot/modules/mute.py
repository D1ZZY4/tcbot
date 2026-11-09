# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group mute and unmute command handlers: validates permissions and delegates to mute_flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler, MessageHandler

from tcbot import cfg
from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_reply
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.modules.helper.pipelines.mute_flow import (
    execute_unmute,
    mute_conversation,
    proof,
    reason,
)
from tcbot.modules.helper.pipelines.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    is_reason_too_long,
    parse_inline_reason,
    reason_too_long_text,
)
from tcbot.utils.formatter import code, esc, user_ref
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args
from tcbot.utils.time_and_date import fmt_duration, parse_duration

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 5

# * user_data keys for one mute flow; popped on prompt failure.
_MUTE_KEYS = (
    "mute_target_id",
    "mute_target_fname",
    "mute_duration",
    "mute_admin_id",
    "mute_admin_fname",
    "mute_prompt_chat",
    "mute_prompt_id",
    "mute_reason",
    "mute_extra_info",
)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Mute"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("muting.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("muting.help.commands.body", locale),
        ),
        replies.who_section(replies.perm_tester_above(locale, plain=False), locale),
        replies.where_section(replies.where_connected_group(locale), locale),
        (
            replies.sec_what(locale),
            t("muting.help.what.body", locale),
        ),
        (
            replies.sec_flow(locale),
            t("muting.help.flow.body", locale),
        ),
        (
            t("muting.help.time.title", locale, plain=True),
            t("muting.help.time.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("muting.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ───────────────────── Command Mute </tcmute> ───────────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the mute flow.

    Resolves the target, parses an optional duration token from the inline
    arguments, runs identity and role checks in parallel, demotes any
    federation role, then opens the reason/proof conversation (an inline
    reason skips the reason prompt and goes straight to proof collection).
    Returns ``ConversationHandler.END`` on validation failure.
    """
    resolved = await decorators.resolve_mod_target(
        update,
        ctx,
        action="mute",
        min_role="tester",
        allow_private=False,
        log_prefix="cmd_mute",
    )
    if resolved is None or ctx.user_data is None:
        return ConversationHandler.END
    msg = resolved.msg
    admin = resolved.admin
    locale = resolved.locale
    target_id = resolved.target_id
    target_fname = resolved.target_name
    has_explicit_target = resolved.has_explicit_target
    raw_args = resolved.args
    target_role = resolved.target_role

    remaining_args = list(raw_args[1:] if has_explicit_target else raw_args)

    duration = None
    if remaining_args:
        # * Pop the token only when it parses: an unparsable token
        # * (overflow past timedelta range or above the 100-year cap)
        # * stays in the reason text instead of being silently dropped
        # * from the moderator's message.
        parsed = parse_duration(remaining_args[0])
        if parsed is not None:
            duration = parsed
            remaining_args.pop(0)

    inline_reason = parse_inline_reason(
        remaining_args,
        has_explicit_target=False,
        # * Reply path only (see bans.py): strip a restated target ID.
        # * Uses the shape check, not the hardcoded False above, so the
        # * explicit path (target already popped into remaining_args) can
        # * never strip a reason token that happens to match.
        reply_target_id=target_id if not has_explicit_target else None,
    )
    # * Fail fast on overlong inline reasons with the shared cap and text,
    # * before any prompt is sent or state is stored. The check runs before
    # * the demote below so an aborted command never strips a role,
    # * matching /tcban and /tckick.
    if inline_reason and is_reason_too_long(inline_reason):
        await safe_reply(
            msg,
            reason_too_long_text(len(inline_reason), locale),
            log_label="cmd_mute reason-too-long",
            parse_mode=None,
        )
        return ConversationHandler.END

    # * Demote must succeed before the federation-wide mute to
    # * preserve the role-vs-state invariant. The helper replies and
    # * signals abort when the demote fails, so the mute never proceeds
    # * on a role holder.
    if target_role and not await Demote.execute(
        ctx.bot,
        target_id,
        target_fname or str(target_id),
        target_role,
        admin.id,
        admin.first_name,
        trigger="mute",
        msg=msg,
    ):
        return ConversationHandler.END
    target_mention = user_ref(target_id, target_fname or str(target_id))
    dur_str = esc(fmt_duration(duration, locale))
    extra_info = f"{code(str(target_id))}: {dur_str}"

    ctx.user_data.update(
        {
            "mute_target_id": target_id,
            "mute_target_fname": target_fname or str(target_id),
            "mute_duration": duration,
            "mute_admin_id": admin.id,
            "mute_admin_fname": admin.first_name,
            "mute_prompt_chat": msg.chat.id,
            "mute_reason": "",
            "mute_extra_info": extra_info,
        }
    )

    if inline_reason:
        ctx.user_data["mute_reason"] = inline_reason
        try:
            prompt = await msg.reply_text(
                proof.noted_prompt(
                    "mute",
                    inline_reason,
                    target_mention,
                    extra_info=extra_info,
                    locale=locale,
                ),
                parse_mode="MarkdownV2",
                reply_markup=proof.keyboard(locale),
            )
            ctx.user_data["mute_prompt_id"] = prompt.message_id
        except Exception as exc:
            log.debug("cmd_mute proof-prompt send failed: %s", exc)
            for key in _MUTE_KEYS:
                ctx.user_data.pop(key, None)
            return ConversationHandler.END
        return WAITING_PROOF

    try:
        prompt = await msg.reply_text(
            reason.prompt(target_mention, "mute", extra_info=extra_info, locale=locale),
            parse_mode="MarkdownV2",
            reply_markup=reason.keyboard(locale),
        )
        ctx.user_data["mute_prompt_id"] = prompt.message_id
    except Exception as exc:
        log.debug("cmd_mute reason-prompt send failed: %s", exc)
        for key in _MUTE_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_REASON


# ─────────────────── Command Unmute </tcunmute> ─────────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_unmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the chat restriction from the target and restore messaging rights.

    Resolves the target, runs identity and role checks in parallel (mirroring
    ``cmd_mute``), optionally emits a staff-action notice, then delegates to
    ``execute_unmute``.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return
    locale = await locale_for_update(update)
    if not await decorators.require_federation_origin(
        msg,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=False,
        log_label="cmd_unmute origin",
    ):
        return
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="cmd_unmute no-target",
            parse_mode=None,
        )
        return

    # * return_exceptions=True prevents a DB error from leaving the command silently dead.
    classified = await decorators.classify_and_check(
        ctx.bot,
        admin.id,
        target_id,
        target_name,
        msg,
        action="unmute",
        min_role="tester",
        target_is_bot=await identity.is_proven_bot(update, target_id, ctx.bot),
    )
    if classified is None:
        return
    ident, _ = classified

    refusal = identity.refuse_message("unmute", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_unmute refusal")
        return

    notice = identity.staff_notice("unmute", ident, cfg.community_name, locale)
    if notice is not None:
        await safe_reply(msg, notice, log_label="cmd_unmute notice")

    await execute_unmute(update, ctx, target_id, target_name or str(target_id))


# ──────────────────────────── Handlers ──────────────────────────── #

_MUTE_CMDS = build_prefixed_filters("tcmute") | build_prefixed_filters("tcm")
_UNMUTE_CMDS = (
    build_prefixed_filters("tcunmute")
    | build_prefixed_filters("tcunm")
    | build_prefixed_filters("tcum")
)

__handlers__ = [
    mute_conversation(cmd_mute, _MUTE_CMDS, escape_filter=_UNMUTE_CMDS),
    MessageHandler(_UNMUTE_CMDS, cmd_unmute),
]
