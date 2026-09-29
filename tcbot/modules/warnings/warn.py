# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn command entry for per-group warning tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler

from tcbot import cfg
from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    is_reason_too_long,
    parse_inline_reason,
    reason_too_long_text,
)
from tcbot.modules.helper.workflows.warning_flow import (
    proof,
    reason,
)
from tcbot.utils.formatter import user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_PERIOD_S: int = 60
_RL_WARN_LIMIT: int = 5
_RL_READ_LIMIT: int = 8

# * user_data keys for one warn flow; popped on prompt failure.
_WARN_KEYS = ("warn_target_id", "warn_target_name")


# ───────────────────── Command Warn </tcwarn> ───────────────────── #


@decorators.ratelimiter(limit=_RL_WARN_LIMIT, period=_RL_CMD_PERIOD_S)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_warn_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the warn flow.

    Resolves the target, runs identity and role checks in parallel, then either
    skips to the proof step (when an inline reason is provided) or opens the
    reason-collection step. Returns ``ConversationHandler.END`` on any validation
    failure.
    """
    msg = update.effective_message
    if msg is None:
        return ConversationHandler.END
    admin = update.effective_user
    if admin is None:
        return ConversationHandler.END
    if ctx.user_data is None:
        return ConversationHandler.END
    locale = await locale_for_update(update)

    args = parse_cmd_args(msg.text)
    # * Resolution plus consumption in one call (see banning.py).
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
            log_label="cmd_warn_entry no-target",
            parse_mode=None,
        )
        return ConversationHandler.END

    # * Fail fast on overlong inline reasons with the shared cap and text,
    # * before any role I/O or notice work.
    if inline_reason and is_reason_too_long(inline_reason):
        await safe_reply(
            msg,
            reason_too_long_text(len(inline_reason), locale),
            log_label="cmd_warn_entry reason-too-long",
            parse_mode=None,
        )
        return ConversationHandler.END

    classified = await decorators.classify_and_check(
        ctx.bot,
        admin.id,
        target_id,
        target_name,
        msg,
        action="warn",
        min_role="tester",
    )
    if classified is None:
        return ConversationHandler.END
    ident, _ = classified

    refusal = identity.refuse_message("warn", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_warn_entry refusal")
        return ConversationHandler.END

    notice = identity.staff_notice("warn", ident, cfg.community_name, locale)
    if notice is not None:
        await safe_reply(msg, notice, log_label="cmd_warn_entry staff notice")

    ctx.user_data.update(
        {
            "warn_target_id": target_id,
            "warn_target_name": target_name or str(target_id),
        }
    )

    target_mention = user_ref(target_id, target_name or str(target_id))

    if inline_reason:
        ctx.user_data["warn_reason"] = inline_reason
        try:
            await msg.reply_text(
                proof.noted_prompt(
                    "warn", inline_reason, target_mention, locale=locale
                ),
                parse_mode="MarkdownV2",
                reply_markup=proof.keyboard(locale),
            )
        except Exception as exc:
            log.debug("cmd_warn_entry proof-prompt reply failed: %s", exc)
            for key in (*_WARN_KEYS, "warn_reason"):
                ctx.user_data.pop(key, None)
            return ConversationHandler.END
        return WAITING_PROOF

    try:
        await msg.reply_text(
            reason.prompt(target_mention, "warn", locale=locale),
            parse_mode="MarkdownV2",
            reply_markup=reason.keyboard(locale),
        )
    except Exception as exc:
        log.debug("cmd_warn_entry reason-prompt reply failed: %s", exc)
        for key in _WARN_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_REASON
