# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Target resolution: who a moderation command acts on, and how it is found."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import extraction, guards, identity
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, safe_reply
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from telegram import Bot, Message, Update, User
    from telegram.ext import ContextTypes

    from tcbot.database.users_roles import RoleName
    from tcbot.modules.helper.identity import Identity

    # * Signature of the executor a single-action command delegates to.
    StaffAction = Callable[
        [Update, ContextTypes.DEFAULT_TYPE, int, str], Awaitable[None]
    ]

log = get_logger(__name__)


@dataclass(frozen=True)
class ModTarget:
    """Resolved moderation target shared by the ban/kick/mute/warn entries.

    ``args`` are the raw command tokens and ``has_explicit_target`` tells
    the reason parser whether the first token was consumed as the target.
    """

    msg: Message
    admin: User
    locale: str
    target_id: int
    target_name: str | None
    has_explicit_target: bool
    args: list[str]
    ident: identity.Identity


@dataclass(frozen=True)
class StaffTarget:
    """Resolved target of a single-action moderation command.

    The commands that act once and finish (unwarn, resetwarns, unmute)
    share the same entry sequence and need nothing more than the target
    and the identity that was classified for it.
    """

    target_id: int
    target_name: str
    ident: identity.Identity
    locale: str


# * One owner for the executor-plus-target fetch so a future fix cannot
# * land in one command and miss the other. Gathers stay parallel so the
# * hot path costs one cached round trip, never two serial ones.
async def resolve_executor_target(
    msg: Message,
    admin_id: int,
    update: Update,
    args: list[str],
    bot: Bot | None,
    *,
    action: str,
    locale: str | None = None,
) -> tuple[str, int, str | None] | None:
    """Fetch executor role and target in parallel, fail closed.

    Returns ``(executor_role, target_id, target_fname)`` or ``None`` when
    the caller must return (retry reply already sent, or a genuinely
    role-less executor denied silently like the decorator would).
    Callers pass their already-resolved locale so the two DB reads behind
    locale resolution do not run twice per command.
    """
    if locale is None:
        locale = await locale_for_update(update)
    _exec_r, _target_r = await asyncio.gather(
        db.users_roles.get_effective_role(admin_id),
        extraction.extract_target(update, args, bot),
        return_exceptions=True,
    )
    throw_if_cancelled((_exec_r, _target_r))
    if isinstance(_exec_r, BaseException):
        # * Fail closed on transient outage instead of going silently dead.
        # * A genuinely role-less caller gets None below; the decorator
        # * denies them properly on retry.
        log.warning("cmd_%s executor role lookup failed: %s", action, _exec_r)
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label=f"cmd_{action} lookup-fail",
            parse_mode=None,
        )
        return None
    executor_role = _exec_r
    if executor_role is None:
        return None
    if isinstance(_target_r, BaseException):
        log.error("extract_target failed during %s: %s", action, _target_r)
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"cmd_{action} no-target",
            parse_mode=None,
        )
        return None
    target_id, target_fname = _target_r
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"cmd_{action} no-target-id",
            parse_mode=None,
        )
        return None
    return executor_role, target_id, target_fname


async def classify_and_load_role(
    bot: Bot,
    admin_id: int,
    target_id: int,
    target_fname: str | None,
    msg: Message,
    *,
    action: str,
    locale: str | None = None,
) -> tuple[Identity, str | None] | None:
    """Classify the target and load its live role in parallel, fail closed.

    Returns ``(ident, current_role)`` or ``None`` when the caller must
    return (retry reply already sent). Cancellation always propagates.
    """
    ident_r, role_r = await asyncio.gather(
        identity.classify(bot, admin_id, target_id, target_fname),
        db.users_roles.get_effective_role(target_id, fresh=True),
        return_exceptions=True,
    )
    throw_if_cancelled((ident_r, role_r))
    if isinstance(ident_r, BaseException):
        log.error(
            "identity.classify failed during %s for target=%d: %s",
            action,
            target_id,
            ident_r,
        )
        await safe_reply(
            msg,
            t("admins.error.classify_failed", locale, plain=True),
            log_label=f"cmd_{action} classify-failed",
            parse_mode=None,
        )
        return None
    if isinstance(role_r, BaseException):
        log.error(
            "target role lookup failed during %s for target=%d: %s",
            action,
            target_id,
            role_r,
        )
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label=f"cmd_{action} role-lookup-failed",
            parse_mode=None,
        )
        return None
    return ident_r, role_r


async def resolve_staff_target(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    min_role: RoleName,
    log_prefix: str,
    bot_check: bool = True,
) -> StaffTarget | None:
    """Run the shared entry sequence for single-action moderation commands.

    Checks the federation origin, resolves the target, classifies it, and
    refuses the protected identities. Replies on the message and returns
    ``None`` on any failure, so the caller only performs its own action.

    ``bot_check`` verifies the target is not a proven bot before the
    classification, so a bot is refused rather than acted on. Cancellation
    always propagates.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return None
    locale = await locale_for_update(update)
    if not await guards.require_federation_origin(
        msg,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=False,
        log_label=f"{log_prefix} origin",
    ):
        return None
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"{log_prefix} no-target",
            parse_mode=None,
        )
        return None
    classified = await guards.classify_and_check(
        ctx.bot,
        admin.id,
        target_id,
        target_name,
        msg,
        action=action,
        min_role=min_role,
        target_is_bot=(
            await identity.is_proven_bot(update, target_id, ctx.bot)
            if bot_check
            else None
        ),
    )
    if classified is None:
        return None
    ident, _target_role = classified
    refusal = identity.refuse_message(action, ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label=f"{log_prefix} refusal")
        return None
    return StaffTarget(
        target_id=target_id,
        target_name=target_name or str(target_id),
        ident=ident,
        locale=locale,
    )


async def resolve_mod_target(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    min_role: RoleName,
    allow_private: bool,
    log_prefix: str,
    bot_check: bool = False,
) -> ModTarget | None:
    """Run the shared entry sequence for reason/proof moderation commands.

    Resolves the locale, checks the federation origin, extracts the target,
    and runs the identity plus rank checks, replying and returning ``None``
    on any failure. The caller keeps only duty-specific parsing (reason,
    duration) and conversation setup. Cancellation always propagates.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None or ctx.user_data is None:
        return None
    locale = await locale_for_update(update)
    if not await guards.require_federation_origin(
        msg,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=allow_private,
        log_label=f"{log_prefix} origin",
    ):
        return None
    args = parse_cmd_args(msg.text)
    # * Resolution plus consumption in one call: a verified explicit
    # * ID/@username overrides the reply target, and the consumed flag
    # * tells the reason parser to drop args[0] as the target token.
    (target_id, target_name), has_explicit_target = await extraction.extract_mod_target(
        update, args, ctx.bot
    )
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"{log_prefix} no-target",
            parse_mode=None,
        )
        return None
    # * Warn needs a verified bot check before classifying so a proven bot
    # * target is refused instead of warned; other actions classify bots
    # * from the identity cache alone.
    target_is_bot = (
        await identity.is_proven_bot(update, target_id, ctx.bot) if bot_check else None
    )
    classified = await guards.classify_and_check(
        ctx.bot,
        admin.id,
        target_id,
        target_name,
        msg,
        action=action,
        min_role=min_role,
        target_is_bot=target_is_bot,
    )
    if classified is None:
        return None
    ident, _target_role = classified
    refusal = identity.refuse_message(action, ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label=f"{log_prefix} refusal")
        return None
    return ModTarget(
        msg=msg,
        admin=admin,
        locale=locale,
        target_id=target_id,
        target_name=target_name,
        has_explicit_target=has_explicit_target,
        args=args,
        ident=ident,
    )


async def run_staff_action(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    min_role: RoleName,
    log_prefix: str,
    execute: StaffAction,
) -> None:
    """Run one single-action moderation command.

    The commands that act once and finish (unmute, unwarn, resetwarns)
    share the same entry sequence: resolve the target, run the identity
    and rank checks, emit the staff-action notice, and delegate to the
    action. This helper owns that sequence so the three commands cannot
    drift apart in the checks they run or in the notice they emit.
    """
    msg = update.effective_message
    if msg is None:
        return
    resolved = await resolve_staff_target(
        update,
        ctx,
        action=action,
        min_role=min_role,
        log_prefix=log_prefix,
    )
    if resolved is None:
        return
    notice = identity.staff_notice(
        action, resolved.ident, cfg.community_name, resolved.locale
    )
    if notice is not None:
        await safe_reply(msg, notice, log_label=f"{log_prefix} notice")
    await execute(update, ctx, resolved.target_id, resolved.target_name)
