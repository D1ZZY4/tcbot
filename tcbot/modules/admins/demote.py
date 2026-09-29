# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Demote command and confirmation callbacks."""

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
from tcbot.modules.helper import decorators, identity, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import bold, esc, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


@decorators.ratelimiter(limit=_RL_QUERY_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_demote(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a user's federation role.

    Fetches the executor role and resolves the target in parallel. Then fetches
    identity classification and the target's current role in a second parallel
    gather, since both are independent reads. Shows a confirmation keyboard for
    the target's current role. Identity guards prevent demoting the Founder or
    self without the correct flow.
    """
    admin = update.effective_user
    msg = update.effective_message
    if admin is None or msg is None:
        return
    locale = await locale_for_update(update)
    args = parse_cmd_args(msg.text)

    resolved = await _resolve_executor_target(
        msg, admin.id, update, args, ctx.bot, action="demote", locale=locale
    )
    if resolved is None:
        return
    executor_role, target_id, target_fname = resolved

    classified = await _classify_and_load_role(
        ctx.bot,
        admin.id,
        target_id,
        target_fname,
        msg,
        action="demote",
        locale=locale,
    )
    if classified is None:
        return
    ident, target_role = classified
    refusal = identity.refuse_message("demote", ident, locale)
    if refusal is not None:
        await safe_reply(msg, refusal, log_label="cmd_demote refusal")
        return

    if not target_role:
        await safe_reply(
            msg,
            t("admins.error.no_removable_role", locale, plain=True),
            log_label="cmd_demote no-role",
            parse_mode=None,
        )
        return

    if target_role == "admin" and executor_role != "founder":
        await safe_reply(
            msg,
            t("admins.error.founder_demote_only", locale, plain=True),
            log_label="cmd_demote founder-only",
            parse_mode=None,
        )
        return

    role_label = db.users_roles.ROLE_LABEL.get(target_role, target_role)
    await safe_reply(
        msg,
        t(
            "admins.demote.confirm",
            locale,
            user=Safe(
                user_ref(target_id, target_fname or str(target_id), ident.username)
            ),
            role=Safe(bold(role_label)),
        ),
        log_label="cmd_demote confirm-prompt",
        reply_markup=keyboards.demote_confirm_kb(target_id, locale),
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_demote_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm the demote action from the inline keyboard.

    Re-validates the executor's rank; rejects with alert if insufficient.
    Answers the query, fetches the target's current role and mention data in
    parallel, then executes ``Demote.execute`` and edits the prompt to the result.
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
    try:
        target_id = int(q.data.split(":", 1)[1])
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    executor_role = await _check_callback_staff(admin.id, q, update)
    if executor_role is None:
        return

    target_role, mention_data = await asyncio.gather(
        db.users_roles.get_effective_role(target_id),
        db.users_cache.get_user_mention_data(target_id),
        return_exceptions=True,
    )
    throw_if_cancelled((target_role, mention_data))
    if isinstance(target_role, BaseException):
        log.error(
            "target role lookup failed during demote callback for target=%d: %s",
            target_id,
            target_role,
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
            log.debug("on_demote_confirm role-lookup-failed edit failed: %s", exc)
        return
    if isinstance(mention_data, BaseException):
        target_fname, target_uname = str(target_id), None
    else:
        target_fname, target_uname = mention_data

    if not target_role or target_role == "founder":
        try:
            await q.edit_message_text(
                t(
                    "admins.error.no_longer_removable",
                    await locale_for_update(update),
                    plain=True,
                ),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("on_demote_confirm no-longer-removable edit failed: %s", exc)
        return

    if target_role == "admin" and executor_role != "founder":
        try:
            await q.edit_message_text(
                t(
                    "admins.error.founder_demote_only",
                    await locale_for_update(update),
                    plain=True,
                ),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("on_demote_confirm founder-only edit failed: %s", exc)
        return

    try:
        removed = await Demote.execute(
            ctx.bot,
            target_id,
            target_fname,
            target_role,
            admin.id,
            admin.first_name,
            trigger=None,
        )
    except Exception:
        log.exception(
            "Demote.execute raised for target=%d in on_demote_confirm", target_id
        )
        removed = False
    if not removed:
        try:
            await q.edit_message_text(
                t(
                    "admins.error.role_clear_failed",
                    await locale_for_update(update),
                    plain=True,
                ),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("on_demote_confirm role-clear-failed edit failed: %s", exc)
        return

    role_label = db.users_roles.ROLE_LABEL.get(target_role, target_role)
    try:
        await q.edit_message_text(
            t(
                "admins.demote.done",
                await locale_for_update(update),
                user=Safe(user_ref(target_id, target_fname, target_uname)),
                role=esc(role_label),
            ),
            parse_mode="MarkdownV2",
            reply_markup=None,
        )
    except Exception as exc:
        log.debug("on_demote_confirm success edit failed: %s", exc)


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_demote_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge the cancel button and collapse the demotion confirmation prompt."""
    q = update.callback_query
    if q is None:
        return
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            t("admins.error.cancelled", await locale_for_update(update), plain=True),
            reply_markup=None,
        ),
        return_exceptions=True,
    )
