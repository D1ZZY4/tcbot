# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group kick command entry point: validates permissions and delegates to kick_flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, ConversationHandler

from tcbot.modules.helper import decorators
from tcbot.modules.helper.messages import replies, safe_reply
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.modules.helper.pipelines.kick_flow import kick_conversation, proof, reason
from tcbot.modules.helper.pipelines.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    is_reason_too_long,
    parse_inline_reason,
    reason_too_long_text,
)
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


# * user_data keys for one kick flow; popped on prompt failure.
_KICK_KEYS = (
    "kick_target_id",
    "kick_target_name",
    "kick_prompt_chat",
    "kick_prompt_id",
)


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
            replies.sec_flow(locale),
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


# ───────────────────── Command Kick </tckick> ───────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the kick flow.

    Resolves the target, runs identity and role checks in parallel, demotes
    any federation role, then either executes an immediate kick (with inline
    reason) or opens the reason/proof conversation. Returns
    ``ConversationHandler.END`` on validation failure.
    """
    # * Kick is a current-chat ban-then-unban: Telegram rejects it in private
    # * chats ("Can't ban members in private chats"), so the shared resolver
    # * refuses private origins up front via allow_private=False; it also
    # * blocks disconnected groups from kicking in a non-federation chat.
    resolved = await decorators.resolve_mod_target(
        update,
        ctx,
        action="kick",
        min_role="tester",
        allow_private=False,
        log_prefix="cmd_kick",
    )
    if resolved is None or ctx.user_data is None:
        return ConversationHandler.END
    msg = resolved.msg
    admin = resolved.admin
    locale = resolved.locale
    target_id = resolved.target_id
    target_name = resolved.target_name
    has_explicit_target = resolved.has_explicit_target
    args = resolved.args
    target_role = resolved.target_role

    inline_reason = parse_inline_reason(
        args,
        has_explicit_target=has_explicit_target,
        # * Reply path only (see bans.py): strip a restated target ID.
        reply_target_id=target_id if not has_explicit_target else None,
    )

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

    # * Demote must succeed before the kick to preserve the
    # * role-vs-state invariant. The helper replies and signals abort
    # * when the demote fails, so the kick never proceeds on a role holder.
    if target_role and not await Demote.execute(
        ctx.bot,
        target_id,
        target_name or str(target_id),
        target_role,
        admin.id,
        admin.first_name,
        trigger="kick",
        msg=msg,
    ):
        return ConversationHandler.END

    scope = flow_scope(ctx, update)
    scope.update(
        {
            "kick_target_id": target_id,
            "kick_target_name": target_name or str(target_id),
            "kick_prompt_chat": msg.chat.id,
        }
    )

    target_mention = user_ref(target_id, target_name or str(target_id))

    if inline_reason:
        scope["kick_reason"] = inline_reason
        try:
            prompt = await msg.reply_text(
                proof.noted_prompt(
                    "kick", inline_reason, target_mention, locale=locale
                ),
                parse_mode="MarkdownV2",
                reply_markup=proof.keyboard(locale),
            )
            scope["kick_prompt_id"] = prompt.message_id
        except Exception as exc:
            log.debug("cmd_kick proof-prompt reply failed: %s", exc)
            for key in (*_KICK_KEYS, "kick_reason"):
                scope.pop(key, None)
            return ConversationHandler.END
        return WAITING_PROOF

    try:
        prompt = await msg.reply_text(
            reason.prompt(target_mention, "kick", locale=locale),
            parse_mode="MarkdownV2",
            reply_markup=reason.keyboard(locale),
        )
        scope["kick_prompt_id"] = prompt.message_id
    except Exception as exc:
        log.debug("cmd_kick reason-prompt reply failed: %s", exc)
        for key in _KICK_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    return WAITING_REASON


# ──────────────────────────── Handlers ──────────────────────────── #

_KICK_CMDS = build_prefixed_filters("tckick") | build_prefixed_filters("tck")

__handlers__ = [kick_conversation(cmd_kick, _KICK_CMDS)]
