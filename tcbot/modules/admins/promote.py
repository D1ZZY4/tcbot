# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promote command and role-selection callbacks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.admins.shared import (
    _RL_CMD_LIMIT,
    _RL_PERIOD_LONG_S,
    _RL_PERIOD_S,
    _RL_QUERY_LIMIT,
    _check_callback_staff,
    _classify_and_load_role,
    _resolve_executor_target,
)
from tcbot.modules.helper import decorators, extraction, identity, keyboards, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.promote_flow import ROLE_ALIASES, Promote
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


@decorators.ratelimiter(limit=_RL_QUERY_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_promote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Assign a federation role to a user (admin / developer / tester).

    Fetches the executor role and resolves the target in parallel. Then fetches
    identity classification and the target's current role in a second parallel
    gather, since both are independent reads. When a role name is given inline,
    executes the promotion immediately via ``Promote.execute``. When no role is
    given, shows a role-selection keyboard. Identity and rank checks prevent
    self-promotion or promoting above one's own rank.
    """
    admin = update.effective_user
    msg = update.effective_message
    if admin is None or msg is None:
        return
    locale = await locale_for_update(update)
    args = parse_cmd_args(msg.text)

    has_explicit_target = bool(args) and (
        args[0].lstrip("-").isdigit() or args[0].startswith("@")
    )
    # * A bare role token with no reply target is ambiguous: name search
    # * could resolve "developer" to an unrelated cached user and promote
    # * a stranger. Ask for an explicit target instead.
    if (
        not has_explicit_target
        and args
        and extraction._reply_uid(msg) is None
        and args[0].lstrip("@").lower() in ROLE_ALIASES
    ):
        await safe_reply(
            msg,
            t("admins.error.promote_needs_target", locale, plain=True),
            log_label="cmd_promote needs-target",
            parse_mode=None,
        )
        return
    resolved = await _resolve_executor_target(
        msg, admin.id, update, args, ctx.bot, action="promote", locale=locale
    )
    if resolved is None:
        return
    executor_role, target_id, target_fname = resolved
    remaining_args = args[1:] if has_explicit_target else args
    role_arg = remaining_args[0].lower() if remaining_args else ""

    classified = await _classify_and_load_role(
        ctx.bot,
        admin.id,
        target_id,
        target_fname,
        msg,
        action="promote",
        locale=locale,
    )
    if classified is None:
        return
    ident, current_role = classified
    refusal = identity.refuse_message("promote", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_promote refusal")
        return

    # * Bots hold no actionable identity, so promoting one grants privilege
    # * to a non-actor. Verified-only; unknown stays allowed so off-group
    # * promotions keep working.
    if await identity.is_proven_bot(update, target_id, ctx.bot):
        await safe_reply(
            msg,
            t("admins.error.bot_target", locale, plain=True),
            log_label="cmd_promote bot-target",
            parse_mode=None,
        )
        return

    role = ROLE_ALIASES.get(role_arg)

    if role:
        _, text = await Promote.execute(
            ctx.bot,
            admin.id,
            admin.first_name,
            executor_role,
            target_id,
            target_fname or str(target_id),
            current_role,
            role,
            locale,
        )
        await safe_reply(msg, text, log_label="cmd_promote result")
        return

    available = Promote.available_roles_for(executor_role)
    if not available:
        await safe_reply(
            msg,
            t("admins.error.no_assign_perms", locale, plain=True),
            log_label="cmd_promote no-perms",
            parse_mode=None,
        )
        return
    await safe_reply(
        msg,
        t(
            "admins.promote_ui.role_picker",
            locale,
            user=Safe(
                user_ref(target_id, target_fname or str(target_id), ident.username)
            ),
        ),
        log_label="cmd_promote role-picker",
        reply_markup=keyboards.promote_role_kb(target_id, available, locale),
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promote_role_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the role-selection inline button from /tcpromote.

    Verifies the executor still holds staff rank; rejects with alert if expired.
    Fetches the target's name and current role in parallel, then delegates to
    ``Promote.execute`` and edits the prompt to the result.
    """
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    admin = update.effective_user
    if admin is None:
        await q.answer()
        return
    parts = q.data.split(":", 2)
    if len(parts) != 3:
        await q.answer()
        return
    _, role, target_id_str = parts
    try:
        target_id = int(target_id_str)
    except ValueError:
        await q.answer()
        return

    executor_role = await _check_callback_staff(admin.id, q, update)
    if executor_role is None:
        return

    if await identity.is_proven_bot(update, target_id, ctx.bot):
        try:
            await q.edit_message_text(
                t(
                    "admins.error.bot_target",
                    await locale_for_update(update),
                    plain=True,
                ),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("on_promote_role_btn bot-target edit failed: %s", exc)
        return

    if role not in ("admin", "developer", "tester"):
        try:
            await q.edit_message_text(
                replies.err_unknown_role(await locale_for_update(update), plain=True),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("admins promote unknown-role edit failed: %s", exc)
        return
    target_fname_r, current_role = await asyncio.gather(
        db.users_cache.get_first_name(target_id, str(target_id)),
        db.users_roles.get_effective_role(target_id),
        return_exceptions=True,
    )
    throw_if_cancelled((target_fname_r, current_role))
    target_fname = (
        target_fname_r
        if not isinstance(target_fname_r, BaseException)
        else str(target_id)
    )
    if isinstance(current_role, BaseException):
        log.error(
            "target role lookup failed during promote callback for target=%d: %s",
            target_id,
            current_role,
        )
        try:
            await q.edit_message_text(
                t(
                    "admins.error.role_lookup_failed",
                    await locale_for_update(update),
                    plain=True,
                ),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("on_promote_role_btn role-lookup-failed edit failed: %s", exc)
        return

    _, text = await Promote.execute(
        ctx.bot,
        admin.id,
        admin.first_name,
        executor_role,
        target_id,
        target_fname,
        current_role,
        role,
        await locale_for_update(update),
    )
    try:
        await q.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=None)
    except Exception as exc:
        log.debug("on_promote_role_btn result edit failed: %s", exc)


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promote_role_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Acknowledge the cancel button and replace the role-selection prompt with a cancellation notice."""
    q = update.callback_query
    if q is None:
        return
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            t(
                "admins.error.promote_cancelled",
                await locale_for_update(update),
                plain=True,
            ),
            reply_markup=None,
        ),
        return_exceptions=True,
    )
