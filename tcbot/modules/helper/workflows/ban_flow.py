# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban executor + proof collection conversation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import telegram.error
from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg, replies
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.parse_editmsg import clear_markup_cb, safe_edit_cb, safe_reply
from tcbot.modules.helper.parse_link import appeal_deep_link, message_link
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.proof_flow import (
    PROOF_MEDIA_FILTER,
    BuildProof,
    upload_proof,
)
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    is_benign_telegram_error,
)
from tcbot.utils.formatter import mention, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.time_and_date import monotonic, to_utc, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from telegram import Bot, InlineKeyboardMarkup, Message
    from telegram.ext.filters import BaseFilter

from tcbot.database.documents import BanDoc

log = logging.getLogger(__name__)

# ──────────────── User-facing reply constants ──────────────────── #
# * Ban-flow runtime prose lives in banning.toml [state]/[db_fail]/
# * [applied]/[pm]/[summary]; only the key tuple below stays in code.

_BAN_USER_DATA_KEYS = (
    "ban_target_id",
    "ban_target_fname",
    "ban_reason",
    "ban_admin_id",
    "ban_admin_fname",
    "ban_prompt_msg_id",
    "ban_prompt_chat_id",
    "ban_target_role",
    "ban_duration",
    "ban_executing",
    "ban_locale",
)

WAITING_PROOF = 0
WAITING_UPDATE_CONFIRM = 1

# * Per-action BuildProof instance; imported by banning.py
# * skip_allowed=False: ban proof is required; there is no Skip option
proof = BuildProof("ban", skip_allowed=False)

# * Hard cap on one proof-collection session: the silence window below
# * slides with every arrival, so without a cap a steady trickle of media
# * would never flush. Far above any legitimate multi-send burst.
_PROOF_COLLECT_MAX_S: float = 60.0


@dataclass
class _ProofSession:
    """One in-progress proof collection, keyed by (chat_id, user_id).

    Gathers every proof message (album parts and sequential sends alike)
    until the Done button or a silence window flushes it. ``flushing`` is
    claimed with a synchronous check-and-set so a Done tap and the flush
    task can never execute the same session twice. The session stays
    visible (with ``flushing`` set) through execution so late arrivals
    are dropped exactly like the old executing-flag guard.
    """

    msgs: list[Message] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    user_data: dict[str, Any] | None = None
    deadline: float = 0.0
    last_arrival: float = 0.0
    flushing: bool = False
    cancelled: bool = False
    flush_task: asyncio.Task[None] | None = None


# * Live proof sessions keyed by (chat_id, user_id). user_data is per
# * (chat, user) under per_chat/per_user routing, so one key maps to one
# * conversation exactly.
_proof_sessions: dict[tuple[int, int], _ProofSession] = {}


# ─────────────────── Album state helpers ────────────────────────── #


def _clear_ban_state(user_data: dict[str, Any] | None) -> None:
    """Remove all ban-related keys from ``user_data``.

    Safe to call when ``user_data`` is ``None`` (no-op).
    """
    if user_data is None:
        return
    for key in _BAN_USER_DATA_KEYS:
        user_data.pop(key, None)


def _cancel_proof_session(user_data: dict[str, Any] | None) -> None:
    """Cancel any in-flight proof flush tasks and clear all ban state.

    Clears ban keys from ``user_data`` and cancels every flush task whose
    session references the given dict. Called from ``on_cancel_proof`` and
    ``on_proof_timeout`` so the cleanup path is defined exactly once.
    (``on_done_proof`` cleans its own claimed session inline instead.)
    """
    _clear_ban_state(user_data)
    if user_data is None:
        return
    for key in [k for k, s in _proof_sessions.items() if s.user_data is user_data]:
        session = _proof_sessions.pop(key)
        session.cancelled = True
        if session.flush_task is not None:
            session.flush_task.cancel()


# ────────────────────────── Ban executor ────────────────────────── #


async def demote_ban_target(
    msg: Message,
    bot: Bot,
    target_id: int,
    target_fname: str,
    target_role: str | None,
    admin_id: int,
    admin_fname: str,
) -> bool:
    """Auto-demote a role-holding ban target; reply and abort on failure.

    Shared by the entry fresh-ban path and the update-confirm Continue
    handler so demotion always lands after the final confirmation. Returns
    True when the caller may proceed.
    """
    if not target_role:
        return True
    return await Demote.auto_demote_or_abort(
        msg,
        bot,
        target_id,
        target_fname,
        target_role,
        admin_id,
        admin_fname,
        trigger="ban",
    )


def proof_prompt_content(
    target_id: int, target_fname: str, reason: str, locale: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    """Build the proof-collection prompt text and keyboard (single owner).

    Used by the entry fresh-ban path (as a reply) and the update-confirm
    Continue handler (as an in-place edit of the confirm message).
    """
    return (
        proof.noted_prompt(
            "ban", reason, mention(target_id, target_fname), locale=locale
        ),
        proof.keyboard(locale),
    )


async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict[str, Any]) -> None:
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    locale: str | None = meta.get("ban_locale")
    reason: str = meta.get("ban_reason", replies.no_reason(locale, plain=True))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)
    ban_duration = meta.get("ban_duration")
    target_locale = await locale_for_user(target_id)

    now = utc_now()
    # * ban_duration is reserved for future timed-ban support; Telegram enforcement
    # * via until_date is not yet wired up, so we do not compute until/dur_str here.
    _ = ban_duration
    proof_chat, proof_thread = cfg.proofs

    # * Pre-fetch active groups immediately so DB round-trip overlaps with the
    # * get_active_ban call and the proof-upload I/O that follows.
    _groups_task: asyncio.Task[list] = asyncio.create_task(db.groups_db.active_groups())

    existing = await db.bans_db.get_active_ban(target_id)
    is_update = existing is not None
    bot_username = bot.username or ""
    ban_id = str(existing.get("ban_id", "")) if is_update else db.bans_db.make_ban_id()

    if is_update:
        # * Suppress any stale duplicate active bans for this user, keeping only the
        # * canonical record (existing) that will be updated. This is a no-op when
        # * there are no duplicates. Duplicates can arise from race conditions or from
        # * a re-ban that failed to find the prior active record before creating a new
        # * one. Cleaning them here ensures a single active ban at all times.
        extras = await db.bans_db.deactivate_extra_active_bans(
            target_id, existing.get("ban_id", "")
        )
        if extras > 0:
            log.warning(
                "Suppressed %d duplicate active ban(s) for user %d before update",
                extras,
                target_id,
            )

    # * Build proof caption
    if is_update:
        prev_proof_msg_id = existing.get("proof_message_id")
        prev_proof_link = (
            message_link(proof_chat, prev_proof_msg_id, proof_thread)
            if prev_proof_msg_id
            else None
        )
        caption = parse_logmsg.proof_caption_update(
            target_id,
            admin_id,
            admin_fname,
            existing.get("timestamp", now),
            prev_proof_link,
        )
    else:
        prev_proof_link = None
        caption = parse_logmsg.proof_caption_new(target_id, admin_id, admin_fname, now)

    # * Upload proof to PROOF channel
    proof_msg_id = await upload_proof(bot, msgs, caption, proof_chat, proof_thread)
    proof_link = (
        message_link(proof_chat, proof_msg_id, proof_thread) if proof_msg_id else None
    )

    logs_chat, logs_thread = cfg.logs

    if is_update:
        log_msg_id, db_ok = await _execute_ban_update(
            bot,
            existing,
            meta,
            proof_msg_id,
            proof_link,
            prev_proof_link,
            logs_chat,
            logs_thread,
        )
    else:
        # * Single canonical ban_id: generated once above and reused for the DB
        # * record, the PM appeal link, and set_log_message_id below.
        log_msg_id, db_ok = await _execute_new_ban(
            bot, meta, proof_msg_id, proof_link, now, logs_chat, logs_thread, ban_id
        )

    # * Fail closed like execute_unban and the warn auto-ban path: enforcing
    # * chats without a bans record leaves an un-appealable split brain
    # * (get_active_ban returns None, so /tcunban and appeal submit cannot
    # * find it). No group is touched below; the operator retries via /tcban
    # * once the database recovers.
    if not db_ok:
        _db_fail_text = t(
            "banning.db_fail.body",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
        )
        if prompt_msg_id and prompt_chat_id:
            try:
                await bot.edit_message_text(
                    _db_fail_text,
                    chat_id=prompt_chat_id,
                    message_id=prompt_msg_id,
                    parse_mode="MarkdownV2",
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("Ban DB-fail prompt edit failed: %s", exc)
        else:
            log.warning(
                "Ban DB write failed for target=%d with no prompt to update",
                target_id,
            )
        try:
            await _groups_task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Discarding pre-fetched groups after DB failure: %s", exc)
        return

    # * set_log_message_id and pre-fetched active_groups in parallel.
    # * _groups_task was started at the top of this function and has been
    # * running concurrently through get_active_ban, upload_proof, and log send.
    if log_msg_id:
        set_log_result, groups = await asyncio.gather(
            db.bans_db.set_log_message_id(ban_id, log_msg_id),
            _groups_task,
            return_exceptions=True,
        )
        if isinstance(set_log_result, BaseException):
            log.error(
                "set_log_message_id failed for ban_id=%s: %s", ban_id, set_log_result
            )
        # ! CRITICAL: a cancelled groups fetch must propagate, not shrink
        # ! enforcement to primaries-only mid-shutdown with a success summary.
        if isinstance(groups, asyncio.CancelledError):
            raise groups
        if isinstance(groups, BaseException):
            log.error("active_groups failed during ban of %d: %s", target_id, groups)
            groups = []
    else:
        try:
            groups = await _groups_task
        except Exception:
            log.exception("active_groups failed during ban of %d", target_id)
            groups = []

    # * Enforce across all connected groups + primary groups - semaphore-bounded.
    # * The entry auto-demote ran before the proof-collection window, so
    # * re-demote here to close the TOCTOU gap right up to the fan-out.
    # * Best-effort like the entry-point demote: the ban record above is
    # * already written, so enforcement proceeds regardless; the helper logs
    # * loudly on any failure. The role read itself is L1/L2-cached (60 s
    # * TTL), so this adds no database round trip on the hot path.
    await Demote.redemote_before_fanout(
        bot,
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        trigger="ban",
    )
    _primary_ids = [cid for cid in (cfg.main_group, cfg.exec_group) if cid]
    _existing_ids = {grp["chat_id"] for grp in groups}
    for _pid in _primary_ids:
        if _pid not in _existing_ids:
            groups = [*groups, {"chat_id": _pid, "title": ""}]
    results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )
    # * Collect per-group failures for transparent reporting to the admin.
    # * Benign Telegram refusals (user not in chat, chat gone, bot demoted)
    # * are logged but excluded from the operator-facing failed count so a
    # * ban does not look partially failed when there was nothing to enforce.
    failed_groups = [
        (grp, r)
        for grp, r in zip(groups, results, strict=False)
        if isinstance(r, BaseException)
    ]
    transient_groups = [
        (grp, r) for grp, r in failed_groups if not is_benign_telegram_error(r)
    ]
    failed = count_transient_errors(results)
    for grp, exc in failed_groups:
        log.warning(
            "Ban enforcement failed for user=%d in group=%s (%d): %s",
            target_id,
            grp.get("title", ""),
            grp["chat_id"],
            exc,
        )
    log.info(
        "Ban enforced: target=%d applied=%d/%d",
        target_id,
        len(groups) - failed,
        len(groups),
    )
    if failed:
        # * Error-level so the failure ships to LOG_ERRORS automatically;
        # * per-group warnings above stay console-only.
        log.error(
            "Ban fan-out had %d/%d transient failures for target=%d; "
            "see warnings above and retry manually where needed",
            failed,
            len(groups),
            target_id,
        )

    # * Build the applied-to line, surfacing a clear warning when no group was updated
    total_groups = len(groups)
    if total_groups == 0:
        applied_line = t("banning.applied.empty", locale)
    elif failed == total_groups:
        sample = ", ".join(
            grp.get("title") or str(grp["chat_id"]) for grp, _ in transient_groups[:5]
        )
        applied_line = t(
            "banning.applied.none",
            locale,
            total=total_groups,
            sample=sample,
            more=" ..." if len(transient_groups) > 5 else "",
        )
    elif failed > 0:
        sample = ", ".join(
            grp.get("title") or str(grp["chat_id"]) for grp, _ in transient_groups[:3]
        )
        applied_line = t(
            "banning.applied.partial",
            locale,
            done=total_groups - failed,
            total=total_groups,
            failed=failed,
            sample=sample,
            more=" ...)" if len(transient_groups) > 3 else ")",
        )
    else:
        applied_line = t("banning.applied.full", locale, total=total_groups)

    # * Build PM content before the conditional so it can fire in parallel with
    # * both upsert_user and (optionally) edit_message_text.  All three operations
    # * are independent: no output of one is an input to another.
    _pm_text = t(
        "banning.pm.body",
        target_locale,
        community=cfg.community_name,
        reason=reason,
    )
    _pm_kb = keyboards.appeal_button_kb(bot_username, ban_id, target_locale)

    # * Edit prompt summary + cache user + notify banned user in one round-trip.
    summary = t(
        "banning.summary.body",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        reason=reason,
        applied=Safe(applied_line),
    )
    if prompt_msg_id and prompt_chat_id:
        # * The text edit below keeps the old keyboard (the parameter is
        # * omitted from the API call), so strip it explicitly: the
        # * conversation ends here and the buttons would otherwise spin
        # * forever on tap.
        edit_result, upsert_result, pm_result, markup_result = await asyncio.gather(
            bot.edit_message_text(
                summary,
                chat_id=prompt_chat_id,
                message_id=prompt_msg_id,
                parse_mode="MarkdownV2",
            ),
            db.users_cache.upsert_user(target_id, None, target_fname),
            bot.send_message(
                target_id, _pm_text, parse_mode="MarkdownV2", reply_markup=_pm_kb
            ),
            bot.edit_message_reply_markup(
                chat_id=prompt_chat_id, message_id=prompt_msg_id
            ),
            return_exceptions=True,
        )
        if isinstance(markup_result, BaseException):
            log.debug("Ban summary markup clear failed: %s", markup_result)
        if isinstance(edit_result, BaseException):
            log.debug("Ban summary prompt edit failed: %s", edit_result)
        if isinstance(upsert_result, BaseException):
            log.error("upsert_user failed for target=%d: %s", target_id, upsert_result)
    else:
        upsert_result, pm_result = await asyncio.gather(
            db.users_cache.upsert_user(target_id, None, target_fname),
            bot.send_message(
                target_id, _pm_text, parse_mode="MarkdownV2", reply_markup=_pm_kb
            ),
            return_exceptions=True,
        )
        if isinstance(upsert_result, BaseException):
            log.error(
                "upsert_user (no-prompt path) failed for target=%d: %s",
                target_id,
                upsert_result,
            )
    if isinstance(pm_result, telegram.error.Forbidden):
        log.info(
            "Cannot DM banned user %d: user has not started the bot or has blocked it",
            target_id,
        )
    elif isinstance(pm_result, BaseException):
        log.warning("Failed to send ban PM to user %d: %s", target_id, pm_result)


# ──────────────────────── Ban update / create helpers ───────────────── #
# * Extracted from _execute_ban to keep the main flow under 200 lines.


async def _execute_ban_update(
    bot: Bot,
    existing: BanDoc,
    meta: dict[str, Any],
    proof_msg_id: int | None,
    proof_link: str | None,
    prev_proof_link: str | None,
    logs_chat: int,
    logs_thread: int | None,
) -> tuple[int, bool]:
    """Build log text, keyboard, and DB update for an existing ban re-enforcement.

    Returns ``(log_msg_id, db_ok)`` so the caller can fail closed when the
    ``bans`` write fails instead of enforcing chats without a record.
    """
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    # TODO: Thread render locale through flow meta so state defaults
    # TODO: render per-locale (Batch 3); raw default is identical today.
    reason: str = meta.get(
        "ban_reason", replies.no_reason(meta.get("ban_locale"), plain=True)
    )
    ban_id = str(existing.get("ban_id", ""))
    old_admin_id = int(existing.get("admin_user_id", admin_id))
    bot_username = bot.username or ""
    old_proof_msg_id = int(existing.get("proof_message_id", 0))
    old_log_msg_id = int(existing.get("log_message_id", 0))
    new_proof_msg_id = proof_msg_id if proof_msg_id else old_proof_msg_id

    try:
        old_admin_fname = await db.users_cache.get_first_name(old_admin_id, "Admin")
    except Exception:
        old_admin_fname = "Admin"

    log_text = parse_logmsg.ban_update_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        old_admin_id,
        old_admin_fname,
        reason,
        ban_id,
        to_utc(existing.get("timestamp", utc_now())),
        proof_link,
        prev_proof_link,
    )
    _appeal_url = appeal_deep_link(bot_username, ban_id)
    kb = (
        keyboards.ban_log_update(
            target_id, proof_link, prev_proof_link, _appeal_url, meta.get("ban_locale")
        )
        if proof_link and prev_proof_link
        else (
            keyboards.ban_log_new(
                target_id, proof_link, _appeal_url, meta.get("ban_locale")
            )
            if proof_link
            else None
        )
    )

    send_kwargs: dict = {"parse_mode": "MarkdownV2", "message_thread_id": logs_thread}
    if kb:
        send_kwargs["reply_markup"] = kb
    # * Sequential, not gather: the DB row is authoritative and the log
    # * post is observable. Racing them lets a DB failure leave a phantom
    # * ban card in the logs channel (dead appeal link, /check miss), so
    # * the log only goes out after the write succeeds.
    try:
        await db.bans_db.update_ban(
            ban_id,
            reason,
            admin_id,
            new_proof_msg_id,
            0,
            old_proof_msg_id,
            old_log_msg_id,
        )
    except Exception:
        log.exception("update_ban failed for ban_id=%s", ban_id)
        return 0, False

    try:
        log_msg = await bot.send_message(logs_chat, log_text, **send_kwargs)
    except Exception:
        log.exception("Ban log send failed for ban_id=%s", ban_id)
        return 0, True
    log_msg_id = log_msg.message_id
    log.info("Ban log posted: ban_id=%s msg_id=%s", ban_id, log_msg_id)
    return log_msg_id, True


async def _execute_new_ban(
    bot: Bot,
    meta: dict[str, Any],
    proof_msg_id: int | None,
    proof_link: str | None,
    now: datetime,
    logs_chat: int,
    logs_thread: int | None,
    ban_id: str,
) -> tuple[int, bool]:
    """Build log text, keyboard, and DB insert for a fresh ban.

    Returns ``(log_msg_id, db_ok)`` so the caller can fail closed when the
    ``bans`` write fails instead of enforcing chats without a record.
    """
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    # TODO: Thread render locale through flow meta so state defaults
    # TODO: render per-locale (Batch 3); raw default is identical today.
    reason: str = meta.get(
        "ban_reason", replies.no_reason(meta.get("ban_locale"), plain=True)
    )
    bot_username = bot.username or ""

    log_text = parse_logmsg.ban_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        reason,
        ban_id,
        proof_link,
        now,
    )
    kb = (
        keyboards.ban_log_new(
            target_id,
            proof_link,
            appeal_deep_link(bot_username, ban_id),
            meta.get("ban_locale"),
        )
        if proof_link
        else None
    )

    send_kwargs = {"parse_mode": "MarkdownV2", "message_thread_id": logs_thread}
    if kb:
        send_kwargs["reply_markup"] = kb
    # * Sequential, not gather: same phantom-log rationale as
    # * _execute_ban_update above; the insert must land before the card.
    try:
        await db.bans_db.create_ban(
            target_id, reason, admin_id, proof_msg_id or 0, 0, ban_id
        )
    except Exception:
        log.exception("create_ban failed for ban_id=%s", ban_id)
        return 0, False

    try:
        log_msg = await bot.send_message(logs_chat, log_text, **send_kwargs)
    except Exception:
        log.exception("Ban log send failed for ban_id=%s", ban_id)
        return 0, True
    log_msg_id = log_msg.message_id
    log.info("Ban log posted: ban_id=%s msg_id=%s", ban_id, log_msg_id)
    return log_msg_id, True


# ───────────────── Proof collection state handlers ──────────────── #


async def on_ban_update_continue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Proceed from the re-ban confirmation to proof collection."""
    q = update.callback_query
    msg = update.effective_message
    if q is None or msg is None or ctx.user_data is None:
        return ConversationHandler.END
    await q.answer()
    # * Entry-point authorization covers this tap like every other flow
    # * callback: the tapping admin passed resolve_and_check moments ago,
    # * and demotion below still runs before anything enforces.
    target_id = int(ctx.user_data.get("ban_target_id", 0) or 0)
    target_fname = str(ctx.user_data.get("ban_target_fname") or target_id)
    reason = str(ctx.user_data.get("ban_reason") or "")
    admin_id = int(ctx.user_data.get("ban_admin_id", 0) or 0)
    admin_fname = str(ctx.user_data.get("ban_admin_fname") or "Admin")
    target_role = ctx.user_data.get("ban_target_role")
    if not target_id or not reason:
        # * Keys cleared under us (e.g. a timeout raced the tap):
        # * nothing actionable to continue with.
        return ConversationHandler.END
    if not await demote_ban_target(
        msg,
        ctx.bot,
        target_id,
        target_fname,
        target_role if isinstance(target_role, str) else None,
        admin_id,
        admin_fname,
    ):
        return ConversationHandler.END
    text, kb = proof_prompt_content(
        target_id, target_fname, reason, await locale_for_update(update)
    )
    try:
        await q.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    except Exception as exc:
        log.debug("Ban continue prompt edit failed: %s", exc)
        for key in _BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_PROOF


async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Buffer proof media into the live session; flush on Done or silence."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if msg is None or chat is None or user is None:
        return WAITING_PROOF
    if ctx.user_data is None:
        return ConversationHandler.END

    key = (chat.id, user.id)
    session = _proof_sessions.get(key)
    if session is not None and session.flushing:
        # * A flush already claimed this session (Done tap or silence
        # * window won the race): first submission wins, drop the rest.
        return ConversationHandler.END
    if session is None:
        ctx.user_data["ban_executing"] = True
        now = monotonic()
        session = _ProofSession(
            meta=dict(ctx.user_data),
            user_data=ctx.user_data,
            deadline=now + _PROOF_COLLECT_MAX_S,
            last_arrival=now,
        )
        _proof_sessions[key] = session
        task = asyncio.create_task(_flush_session(key, ctx.bot))
        session.flush_task = task
    else:
        session.last_arrival = monotonic()
    session.msgs.append(msg)
    return WAITING_PROOF


async def on_done_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Flush collected proof immediately when the moderator taps Done."""
    q = update.callback_query
    if q is None or ctx.user_data is None:
        return ConversationHandler.END
    chat = update.effective_chat
    user = update.effective_user
    key = (chat.id, user.id) if chat is not None and user is not None else None
    if key is None:
        return ConversationHandler.END
    session = _proof_sessions.get(key)
    if session is None or session.flushing or not session.msgs:
        # * Nothing to flush (or the auto-flush already claimed it):
        # * nudge instead of executing an empty proof.
        try:
            locale = await locale_for_update(update)
            await q.answer(
                t(
                    "banning.state.empty",
                    locale,
                    done=t("button.done", locale, plain=True),
                    plain=True,
                ),
                show_alert=True,
            )
        except Exception as exc:
            log.debug("Ban done-proof empty answer failed: %s", exc)
        return WAITING_PROOF
    # * Synchronous claim without popping: the session stays visible with
    # * flushing set, so arrivals during execution still drop via the
    # * flushing check in on_proof_received instead of double-executing.
    session.flushing = True
    if session.flush_task is not None:
        session.flush_task.cancel()
    try:
        await q.answer()
    except Exception as exc:
        log.debug("Ban done-proof answer failed: %s", exc)
    if not session.meta.get("ban_target_id") or not session.meta.get("ban_admin_id"):
        log.warning("Done-proof flush aborted: meta missing target_id or admin_id")
        _proof_sessions.pop(key, None)
        _clear_ban_state(session.user_data)
        return ConversationHandler.END
    try:
        await _execute_ban(ctx.bot, session.msgs, session.meta)
    except Exception:
        log.exception("Done-proof _execute_ban raised")
    finally:
        _proof_sessions.pop(key, None)
        _clear_ban_state(session.user_data)
    return ConversationHandler.END


async def _flush_session(key: tuple[int, int], bot: Bot) -> None:
    """Flush one proof session after a silence window or the hard cap."""
    try:
        while True:
            await asyncio.sleep(cfg.album_debounce)
            session = _proof_sessions.get(key)
            if session is None or session.cancelled or session.flushing:
                return
            if (
                monotonic() - session.last_arrival >= cfg.album_debounce
                or monotonic() >= session.deadline
            ):
                break
        # * Synchronous claim, mirroring on_done_proof above: exactly one
        # * of the two paths proceeds, and the session stays visible with
        # * flushing set so late arrivals drop instead of double-executing.
        session = _proof_sessions.get(key)
        if session is None or session.flushing or session.cancelled:
            return
        session.flushing = True
        if (
            not session.msgs
            or not session.meta.get("ban_target_id")
            or not session.meta.get("ban_admin_id")
        ):
            if session.msgs:
                log.warning("Session flush aborted: meta missing target or admin")
            return
        log.info(
            "Flushing proof session %s with %d media items", key, len(session.msgs)
        )
        try:
            await _execute_ban(bot, session.msgs, session.meta)
        except Exception:
            log.exception("_execute_ban raised in _flush_session for %s", key)
    except asyncio.CancelledError:
        # * Done tap or cancel/timeout path took over; propagate so the
        # * task ends, with shared cleanup below.
        raise
    finally:
        session = _proof_sessions.pop(key, None)
        if session is not None:
            _clear_ban_state(session.user_data)


async def on_proof_unexpected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Reject unexpected message types during proof collection."""
    if update.effective_message:
        await safe_reply(
            update.effective_message,
            t(
                "banning.state.proof_expected",
                await locale_for_update(update),
                plain=True,
            ),
            log_label="Ban proof-unexpected",
            parse_mode=None,
        )
    return WAITING_PROOF


async def on_cancel_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Acknowledge the cancel button and end the proof-collection conversation."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()

    _cancel_proof_session(ctx.user_data)

    # * Edit the prompt in place instead of a new reply, and strip its
    # * buttons: a text-only edit keeps the old keyboard, which would leave
    # * dead Cancel/Done buttons behind on an ended conversation.
    await safe_edit_cb(
        q, t("banning.state.cancelled", await locale_for_update(update), plain=False)
    )
    await clear_markup_cb(q)
    return ConversationHandler.END


async def on_proof_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Notify the user that the proof window expired and end the conversation."""
    prompt_chat: int | None = None
    prompt_msg_id: int | None = None
    if ctx.user_data is not None:
        raw_chat = ctx.user_data.get("ban_prompt_chat_id")
        raw_msg = ctx.user_data.get("ban_prompt_msg_id")
        prompt_chat = raw_chat if isinstance(raw_chat, int) else None
        prompt_msg_id = raw_msg if isinstance(raw_msg, int) else None
    _cancel_proof_session(ctx.user_data)

    # * Strip the stale prompt's buttons so a late Cancel/Done tap does not
    # * spin forever on an ended conversation; the timeout notice below
    # * answers the triggering command itself.
    if prompt_chat and prompt_msg_id:
        try:
            await ctx.bot.edit_message_reply_markup(
                chat_id=prompt_chat, message_id=prompt_msg_id
            )
        except Exception as exc:
            log.debug("Ban proof-timeout markup clear failed: %s", exc)
    if update.effective_message:
        await safe_reply(
            update.effective_message,
            t(
                "banning.state.timeout",
                await locale_for_update(update),
                plain=True,
            ),
            log_label="Ban proof-timeout",
            parse_mode=None,
        )
    return ConversationHandler.END


# ─────────────────── ConversationHandler factory ────────────────── #


def ban_conversation(
    entry_fn: Callable[..., Any], entry_filter: BaseFilter
) -> ConversationHandler:
    """Return the ban ConversationHandler with the given entry-point function.

    Note: ``conversation_timeout`` is intentionally omitted.  PTB's timeout
    support requires the ``job-queue`` extra (APScheduler 3.x backend) which
    conflicts with this project's persistent MongoDBJobStore setup.  Conversations
    are ended via the fallback ``on_proof_timeout`` handler (triggered on any
    command) or by the user pressing Cancel.
    """
    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, entry_fn)],
        states={
            WAITING_PROOF: [
                CallbackQueryHandler(
                    on_cancel_proof, pattern=rf"^{proof.action}_cancel$"
                ),
                CallbackQueryHandler(
                    on_done_proof, pattern=rf"^{proof.action}_done_proof$"
                ),
                MessageHandler(PROOF_MEDIA_FILTER, on_proof_received),
                MessageHandler(
                    ~PROOF_MEDIA_FILTER & ~ALL_PREFIXES_CMD_FILTER,
                    on_proof_unexpected,
                ),
            ],
            WAITING_UPDATE_CONFIRM: [
                CallbackQueryHandler(on_ban_update_continue, pattern=r"^ban_continue$"),
                CallbackQueryHandler(
                    on_cancel_proof, pattern=rf"^{proof.action}_cancel$"
                ),
            ],
        },
        fallbacks=[MessageHandler(ALL_PREFIXES_CMD_FILTER, on_proof_timeout)],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
