# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn, unwarn, warnlist, and resetwarns command handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler, MessageHandler

from tcbot import cfg
from tcbot.modules.helper import decorators, extraction, guards, identity, targets
from tcbot.modules.helper.guards import resolve_and_check
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, safe_reply
from tcbot.modules.helper.pipelines.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    is_reason_too_long,
    parse_inline_reason,
    reason_too_long_text,
)
from tcbot.modules.helper.pipelines.warn_flow import (
    execute_resetwarns,
    execute_unwarn,
    execute_warnlist,
    proof,
    reason,
    warn_conversation,
)
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.formatter import bold, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


# * user_data keys for one warn flow; popped on prompt failure.
_WARN_KEYS = ("warn_target_id", "warn_target_name")


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Warnings"


def _warn_limit_label(locale: str | None = None) -> Safe:
    """Pre-formatted warn-limit fragment for help placeholders.

    Markup around a dynamic value cannot come from TOML, so it is
    composed here per locale.
    """
    return Safe(
        bold(f"{cfg.warn_limit} {t('warnings.help.limit_noun', locale, plain=True)}")
    )


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("warnings.help.overview", locale, limit=_warn_limit_label(locale)),
        commands=t("warnings.help.commands.body", locale),
        who=t("warnings.help.who.body", locale),
        where=replies.where_connected_group(locale),
        what=t("warnings.help.what.body", locale, limit=_warn_limit_label(locale)),
        flow=t("warnings.help.flow.body", locale),
        examples=t("warnings.help.examples.body", locale),
    )


__help__: replies.HelpEntry = get_help()


# ───────────────────── Command Warn </tcwarn> ───────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_warn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the warn flow.

    Resolves the target, runs identity and role checks in parallel, then either
    skips to the proof step (when an inline reason is provided) or opens the
    reason-collection step. Returns ``ConversationHandler.END`` on any validation
    failure.
    """
    # * Warn audit rows are scoped to the origin chat: only a connected
    # * group (or primary) may create, aggregate, or trigger threshold ban.
    resolved = await targets.resolve_mod_target(
        update,
        ctx,
        action="warn",
        min_role="tester",
        allow_private=False,
        log_prefix="cmd_warn",
        bot_check=True,
    )
    if resolved is None or ctx.user_data is None:
        return ConversationHandler.END
    msg = resolved.msg
    locale = resolved.locale
    target_id = resolved.target_id
    target_name = resolved.target_name
    has_explicit_target = resolved.has_explicit_target
    args = resolved.args
    ident = resolved.ident

    inline_reason = parse_inline_reason(
        args,
        has_explicit_target=has_explicit_target,
        # * Reply path only (see bans.py): strip a restated target ID.
        reply_target_id=target_id if not has_explicit_target else None,
    )

    # * Fail fast on overlong inline reasons with the shared cap and text,
    # * before any role I/O or notice work.
    if inline_reason and is_reason_too_long(inline_reason):
        await safe_reply(
            msg,
            reason_too_long_text(len(inline_reason), locale),
            log_label="cmd_warn reason-too-long",
            parse_mode=None,
        )
        return ConversationHandler.END

    notice = identity.staff_notice("warn", ident, cfg.community_name, locale)
    if notice is not None:
        await safe_reply(msg, notice, log_label="cmd_warn staff notice")

    scope = flow_scope(ctx, update)
    scope.update(
        {
            "warn_target_id": target_id,
            "warn_target_name": target_name or str(target_id),
        }
    )

    target_mention = user_ref(target_id, target_name or str(target_id))

    if inline_reason:
        scope["warn_reason"] = inline_reason
        try:
            await msg.reply_text(
                proof.noted_prompt(
                    "warn", inline_reason, target_mention, locale=locale
                ),
                parse_mode="MarkdownV2",
                reply_markup=proof.keyboard(locale),
            )
        except Exception as exc:
            log.debug("cmd_warn proof-prompt reply failed: %s", exc)
            for key in (*_WARN_KEYS, "warn_reason"):
                scope.pop(key, None)
            return ConversationHandler.END
        return WAITING_PROOF

    try:
        await msg.reply_text(
            reason.prompt(target_mention, "warn", locale=locale),
            parse_mode="MarkdownV2",
            reply_markup=reason.keyboard(locale),
        )
    except Exception as exc:
        log.debug("cmd_warn reason-prompt reply failed: %s", exc)
        for key in _WARN_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    return WAITING_REASON


# ─────────────────── Command Unwarn </tcunwarn> ─────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_unwarn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove one warning from the target in the current group.

    Resolves the target, runs the identity check, optionally emits a
    staff-action notice, then delegates to ``execute_unwarn``.
    """
    await targets.run_staff_action(
        update,
        ctx,
        action="unwarn",
        min_role="tester",
        log_prefix="cmd_unwarn",
        execute=execute_unwarn,
    )


# ─────────────────── Command Warn List </warns> ─────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_warnlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a paginated warning history for the specified target user."""
    msg = update.effective_message
    if msg is None:
        return
    admin = update.effective_user
    if admin is None:
        return
    locale = await locale_for_update(update)
    if not await guards.require_federation_origin(
        msg,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=False,
        log_label="cmd_warnlist origin",
    ):
        return
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="cmd_warnlist no-target",
            parse_mode=None,
        )
        return

    role_result = await resolve_and_check(msg, admin.id, target_id, min_role="tester")
    # * resolve_and_check replies on rejection and returns (None, None).
    # * Read-only path: the rank check alone gates staff-history enumeration.
    if role_result[0] is None:
        return

    await execute_warnlist(update, ctx, target_id, target_name or str(target_id))


# ──────────────── Command Reset Warns </resetwarns> ─────────────── #


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_resetwarns(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all warnings for the target in the current group.

    Resolves the target, runs the identity check, optionally emits a
    staff-action notice, then delegates to ``execute_resetwarns``.
    """
    await targets.run_staff_action(
        update,
        ctx,
        action="resetwarns",
        min_role="tester",
        log_prefix="cmd_resetwarns",
        execute=execute_resetwarns,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

_WARN_CMDS = build_prefixed_filters("tcwarn") | build_prefixed_filters("tcw")
_UNWARN_CMDS = build_prefixed_filters("tcunwarn") | build_prefixed_filters("tcunw")
_WARNLIST_CMDS = build_prefixed_filters("warns") | build_prefixed_filters("warnlist")
_RESET_CMDS = build_prefixed_filters("resetwarns") | build_prefixed_filters(
    "clearwarns"
)

# * Commands that must NOT be swallowed by the warn conversation fallback.
_WARN_ESCAPE_CMDS = _UNWARN_CMDS | _WARNLIST_CMDS | _RESET_CMDS

__handlers__ = [
    warn_conversation(cmd_warn, _WARN_CMDS, escape_filter=_WARN_ESCAPE_CMDS),
    MessageHandler(_UNWARN_CMDS, cmd_unwarn),
    MessageHandler(_WARNLIST_CMDS, cmd_warnlist),
    MessageHandler(_RESET_CMDS, cmd_resetwarns),
]
