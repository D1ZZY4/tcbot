# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Admin management handlers: promote, demote, transfer ownership, and manage requests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import decorators, extraction, identity, keyboards, replies
from tcbot.modules.helper.decorators import (
    action_owner_mismatch,
    can_demote_admin,
    cancel_owner_mismatch,
    check_callback_staff,
    classify_and_load_role,
    resolve_executor_target,
)
from tcbot.modules.helper.identity import ANONYMOUS_BOT_ID
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_edit_cb, safe_reply
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.modules.helper.pipelines.promo_decision_flow import execute_promo_decision
from tcbot.modules.helper.pipelines.promote_flow import ROLE_ALIASES, Promote
from tcbot.modules.helper.pipelines.transfer_flow import execute_transfer
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import bold, code, esc, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

# * Rate-limiter windows shared by every admins command and callback.
_RL_PERIOD_S: int = 30
_RL_PERIOD_LONG_S: int = 60
_RL_PERIOD_BULK_S: int = 300
_RL_CMD_LIMIT: int = 10
_RL_QUERY_LIMIT: int = 5
_RL_BULK_LIMIT: int = 3


__module_name__ = "Admin"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("admins.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("admins.help.commands.body", locale),
        ),
        replies.who_section(
            t(
                "admins.help.who.body",
                locale,
                perm=Safe(replies.perm_founder_only(locale, plain=False)),
            ),
            locale,
        ),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            t("admins.help.roles.title", locale, plain=True),
            t("admins.help.roles.body", locale),
        ),
        replies.target_section(locale),
        (
            "/tcpromote",
            t("admins.help.promote.body", locale),
        ),
        (
            "/tcdemote",
            t("admins.help.demote.body", locale),
        ),
        (
            "/transferowner",
            t("admins.help.transferowner.body", locale),
        ),
        (
            replies.sec_examples(locale),
            t("admins.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ────────────────────────── Promote command ────────────────────────── #


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
        and extraction.reply_uid(msg) is None
        and args[0].lstrip("@").lower() in ROLE_ALIASES
    ):
        await safe_reply(
            msg,
            t("admins.error.promote_needs_target", locale, plain=True),
            log_label="cmd_promote needs-target",
            parse_mode=None,
        )
        return
    resolved = await resolve_executor_target(
        msg, admin.id, update, args, ctx.bot, action="promote", locale=locale
    )
    if resolved is None:
        return
    executor_role, target_id, target_fname = resolved
    remaining_args = args[1:] if has_explicit_target else args
    role_arg = remaining_args[0].lower() if remaining_args else ""

    classified = await classify_and_load_role(
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
        reply_markup=keyboards.promote_role_kb(target_id, available, locale, admin.id),
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promote_role_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the role-selection inline button from /tcpromote.

    New prompts carry the opener as ``promo_role:{role}:{target}:{executor}``
    so only that staffer can act; a different tapper gets an alert and the
    prompt stays live. Legacy three-part callbacks from in-flight keyboards
    act as the tapper. Verifies the executor still holds staff rank; rejects
    with alert if expired. Fetches the target's name and current role in
    parallel, then delegates to ``Promote.execute`` and edits the prompt to
    the result.
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
    parts = q.data.split(":")
    if len(parts) not in (3, 4):
        await q.answer()
        return
    _, role, target_id_str = parts[:3]
    try:
        target_id = int(target_id_str)
    except ValueError:
        await q.answer()
        return
    if await action_owner_mismatch(q, update, min_parts=3):
        return

    executor_role = await check_callback_staff(admin.id, q, update)
    if executor_role is None:
        return

    if await identity.is_proven_bot(update, target_id, ctx.bot):
        await safe_edit_cb(
            q,
            t(
                "admins.error.bot_target",
                await locale_for_update(update),
                plain=True,
            ),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="on_promote_role_btn bot-target",
            catch_all=True,
        )
        return

    if role not in ("admin", "developer", "tester"):
        await safe_edit_cb(
            q,
            replies.err_unknown_role(await locale_for_update(update), plain=True),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="admins promote unknown-role",
            catch_all=True,
        )
        return
    target_fname_r, current_role = await asyncio.gather(
        db.users_cache.get_first_name(target_id, str(target_id)),
        db.users_roles.get_effective_role(target_id, fresh=True),
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
        await safe_edit_cb(
            q,
            t(
                "admins.error.role_lookup_failed",
                await locale_for_update(update),
                plain=True,
            ),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="on_promote_role_btn role-lookup-failed",
            catch_all=True,
        )
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
    await safe_edit_cb(
        q,
        text,
        reply_markup=None,
        log_level="debug",
        log_label="on_promote_role_btn result",
        catch_all=True,
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promote_role_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Acknowledge the cancel button and replace the role-selection prompt with a cancellation notice.

    New prompts carry the opener as ``promo_role_cancel:{target}:{executor}``
    so only that staffer can collapse the picker; a different tapper gets an
    alert and the prompt stays live. Legacy two-part callbacks from
    in-flight keyboards keep the old behaviour (anyone may cancel).
    """
    q = update.callback_query
    if q is None:
        return
    if await cancel_owner_mismatch(q, update):
        return
    results = await asyncio.gather(
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
    throw_if_cancelled(results)


# ────────────────────────── Demote command ─────────────────────────── #


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

    resolved = await resolve_executor_target(
        msg, admin.id, update, args, ctx.bot, action="demote", locale=locale
    )
    if resolved is None:
        return
    executor_role, target_id, target_fname = resolved

    classified = await classify_and_load_role(
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

    if not can_demote_admin(executor_role, target_role):
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
        reply_markup=keyboards.demote_confirm_kb(target_id, locale, admin.id),
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_demote_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm the demote action from the inline keyboard.

    New prompts carry the opener as ``demote_confirm:{target}:{executor}``
    so only that staffer can act; a different tapper gets an alert and the
    prompt stays live. Legacy two-part callbacks from in-flight keyboards
    act as the tapper. Re-validates the executor's rank; rejects with alert
    if insufficient. Answers the query, fetches the target's current role
    and mention data in parallel, then executes ``Demote.execute`` and
    edits the prompt to the result.
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
    parts = q.data.split(":")
    if len(parts) not in (2, 3):
        await q.answer()
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await q.answer()
        return
    if await action_owner_mismatch(q, update, min_parts=2):
        return
    executor_role = await check_callback_staff(admin.id, q, update)
    if executor_role is None:
        return

    target_role, mention_data = await asyncio.gather(
        db.users_roles.get_effective_role(target_id, fresh=True),
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
        await safe_edit_cb(
            q,
            t(
                "admins.error.role_lookup_failed",
                await locale_for_update(update),
                plain=True,
            ),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="on_demote_confirm role-lookup-failed",
            catch_all=True,
        )
        return
    if isinstance(mention_data, BaseException):
        target_fname, target_uname = str(target_id), None
    else:
        target_fname, target_uname = mention_data

    if not target_role or target_role == "founder":
        await safe_edit_cb(
            q,
            t(
                "admins.error.no_longer_removable",
                await locale_for_update(update),
                plain=True,
            ),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="on_demote_confirm no-longer-removable",
            catch_all=True,
        )
        return

    if not can_demote_admin(executor_role, target_role):
        await safe_edit_cb(
            q,
            t(
                "admins.error.founder_demote_only",
                await locale_for_update(update),
                plain=True,
            ),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="on_demote_confirm founder-only",
            catch_all=True,
        )
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
        await safe_edit_cb(
            q,
            t(
                "admins.error.role_clear_failed",
                await locale_for_update(update),
                plain=True,
            ),
            parse_mode=None,
            reply_markup=None,
            log_level="debug",
            log_label="on_demote_confirm role-clear-failed",
            catch_all=True,
        )
        return

    role_label = db.users_roles.ROLE_LABEL.get(target_role, target_role)
    await safe_edit_cb(
        q,
        t(
            "admins.demote.done",
            await locale_for_update(update),
            user=Safe(user_ref(target_id, target_fname, target_uname)),
            role=esc(role_label),
        ),
        reply_markup=None,
        log_level="debug",
        log_label="on_demote_confirm success",
        catch_all=True,
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_demote_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Acknowledge the cancel button and collapse the demotion confirmation prompt.

    New prompts carry the opener as ``demote_cancel:{target}:{executor}``
    so only that staffer can collapse the confirmation; a different tapper
    gets an alert and the prompt stays live. Legacy two-part callbacks from
    in-flight keyboards keep the old behaviour (anyone may cancel).
    """
    q = update.callback_query
    if q is None:
        return
    if await cancel_owner_mismatch(q, update):
        return
    results = await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            t("admins.error.cancelled", await locale_for_update(update), plain=True),
            reply_markup=None,
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results)


# ────────────────────── Transfer command ────────────────────── #


@decorators.ratelimiter(limit=_RL_BULK_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Transfer federation ownership to another user.

    Validates the target and hands the transfer to
    ``transfer_flow.execute_transfer``, which replaces the owner record
    first and keeps the previous Founder as Admin.
    """
    await execute_transfer(update, ctx)


# ───────────────────── Promotion queue commands ────────────────── #


@decorators.ratelimiter(limit=_RL_BULK_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.log_execution
async def cmd_promote_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit a promotion request to the Founder.

    Checks the caller's existing role and any pending request in parallel.
    Rejects if the user already holds a federation role (no request needed) or
    already has an open request, then calls ``Promote.request_admin`` to create
    a new queue entry and notify the Founder.

    Note: identity.classify is intentionally not used here because the caller is
    the subject of the request (executor_id == target_id), which would always
    produce an ``Identity("self")`` refusal - incorrect for a self-submission flow.
    """
    user = update.effective_user
    msg = update.effective_message
    if user is None or msg is None:
        return
    locale = await locale_for_update(update)

    # * Reject anonymous admins: a request from the group placeholder would
    # * reach the Founder with no attributable sender. Real humans send from
    # * their own account.
    if user.id == ANONYMOUS_BOT_ID:
        await safe_reply(
            msg,
            t("admins.request.anon_admin", locale, plain=True),
            log_label="cmd_promote_request anon-admin",
            parse_mode=None,
        )
        return
    if user.is_bot:
        await safe_reply(
            msg,
            t("admins.error.bot_target", locale, plain=True),
            log_label="cmd_promote_request bot-target",
            parse_mode=None,
        )
        return

    existing_role, existing = await asyncio.gather(
        db.users_roles.get_effective_role(user.id, fresh=True),
        db.queues_db.get_request(user.id),
        return_exceptions=True,
    )
    # * Fail closed like promote/demote: an outage must not green-light a
    # * request from an already-staff user or duplicate the queue.
    for _lookup in (existing_role, existing):
        if isinstance(_lookup, asyncio.CancelledError):
            raise _lookup
    if isinstance(existing_role, BaseException) or isinstance(existing, BaseException):
        log.warning(
            "cmd_promote_request lookup failed for user=%d: role=%s request=%s",
            user.id,
            existing_role,
            existing,
        )
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label="cmd_promote_request lookup-fail",
            parse_mode=None,
        )
        return
    if existing_role:
        label = db.users_roles.ROLE_LABEL.get(existing_role, existing_role or "unknown")
        label = label.capitalize()
        await safe_reply(
            msg,
            t("admins.request.already_role", locale, role=label, plain=True),
            log_label="cmd_promote_request already-role",
            parse_mode=None,
        )
        return

    if existing:
        await safe_reply(
            msg,
            t(
                "admins.request.existing",
                locale,
                id=Safe(code(existing.get("request_id", "unknown"))),
            ),
            log_label="cmd_promote_request existing-request",
        )
        return
    _, reply = await Promote.request_admin(
        ctx.bot,
        user.id,
        user.id,
        user.first_name or "unknown",
        user.username or "",
        locale,
    )
    await safe_reply(msg, reply, log_label="cmd_promote_request result")


@decorators.ratelimiter(limit=_RL_QUERY_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_promote_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a formatted list of all pending promotion requests."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    pending_r, total_r = await asyncio.gather(
        db.queues_db.all_pending(),
        db.queues_db.pending_count(),
        return_exceptions=True,
    )
    throw_if_cancelled((pending_r, total_r))
    if isinstance(pending_r, BaseException) or isinstance(total_r, BaseException):
        log.warning(
            "all_pending/pending_count failed during promote_list: %s / %s",
            pending_r,
            total_r,
        )
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label="cmd_promote_list db-error",
            parse_mode=None,
        )
        return
    pending, total_pending = pending_r, total_r
    if not pending:
        await safe_reply(
            msg,
            t("admins.error.no_pending", locale, plain=True),
            log_label="cmd_promote_list no-pending",
            parse_mode=None,
        )
        return
    lines = [
        t(
            "admins.list.header",
            locale,
            title=Safe(
                bold(
                    t(
                        "admins.list.header_text",
                        locale,
                        n=total_pending
                        if total_pending > len(pending)
                        else len(pending),
                        plain=True,
                    )
                )
            ),
        )
        + "\n"
    ]
    # * all_pending returns at most 200 rows, so surface the true backlog
    # * count when the list is truncated.
    if total_pending > len(pending):
        lines.append(
            t(
                "admins.list.cap_notice",
                locale,
                shown=len(pending),
                total=total_pending,
            )
        )
    for req in pending:
        target_id = req.get("target_id", 0)
        target_fname = req.get("first_name", "unknown")
        uname_val = req.get("username")
        uname = (
            f"@{uname_val}"
            if uname_val
            else t("admins.list.no_username", locale, plain=True)
        )
        lines.append(
            t(
                "admins.list.row",
                locale,
                user=Safe(user_ref(target_id, target_fname, uname_val)),
                id=Safe(code(str(target_id))),
                uname=uname,
                req=Safe(code(req.get("request_id", "unknown"))),
            )
        )
    await safe_reply(msg, "\n".join(lines), log_label="cmd_promote_list result")


# ────────────────────── Promotion decisions ────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_promo_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approve / reject decisions on promotion request cards.

    Owner-only callback; the executor (owner re-check, request fetch,
    approve/reject writes, notifications) lives in
    ``promo_decision_flow.execute_promo_decision``.
    """
    await execute_promo_decision(update, ctx)


# ──────────────────────────── Handlers ──────────────────────────── #

_PMT_CMDS = build_prefixed_filters("tcpromote") | build_prefixed_filters("tcp")
_DMT_CMDS = build_prefixed_filters("tcdemote") | build_prefixed_filters("tcd")
_TF_CMDS = build_prefixed_filters("transferowner") | build_prefixed_filters("tfowner")
_PMTREQ_CMDS = build_prefixed_filters("tcpromoterequests") | build_prefixed_filters(
    "tcreqs"
)
_PMTLIST_CMDS = build_prefixed_filters("tcpromotelist") | build_prefixed_filters(
    "tcplist"
)

__handlers__ = [
    MessageHandler(_PMT_CMDS, cmd_promote),
    MessageHandler(_DMT_CMDS, cmd_demote),
    MessageHandler(_TF_CMDS, cmd_transfer),
    MessageHandler(_PMTREQ_CMDS, cmd_promote_request),
    MessageHandler(_PMTLIST_CMDS, cmd_promote_list),
    CallbackQueryHandler(on_promo_decision, pattern=r"^(promo_approve|promo_reject):"),
    CallbackQueryHandler(
        on_promote_role_btn, pattern=r"^promo_role:[a-z]+:\d+(:\d+)?$"
    ),
    CallbackQueryHandler(
        on_promote_role_cancel, pattern=r"^promo_role_cancel:\d+(:\d+)?$"
    ),
    CallbackQueryHandler(on_demote_confirm, pattern=r"^demote_confirm:\d+(:\d+)?$"),
    CallbackQueryHandler(on_demote_cancel, pattern=r"^demote_cancel:\d+(:\d+)?$"),
]
