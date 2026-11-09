# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban executor + proof collection conversation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import telegram.error
from telegram import Message, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, keyboards, parse_logmsg, replies
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.parse_editmsg import (
    clear_markup_cb,
    safe_edit_cb,
    safe_edit_message,
    safe_reply,
)
from tcbot.modules.helper.parse_link import appeal_deep_link, message_link
from tcbot.modules.helper.pipelines.demote_flow import Demote
from tcbot.modules.helper.pipelines.proof_flow import (
    PROOF_MEDIA_FILTER,
    BuildProof,
    upload_proof,
)
from tcbot.utils.dispatch import (
    fan_out,
    is_benign_telegram_error,
    log_fanout_error,
    throw_if_cancelled,
)
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.time_and_date import monotonic, to_utc, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from telegram import Bot, InlineKeyboardMarkup
    from telegram.ext.filters import BaseFilter

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)

# ────────────────────────── Proof session ───────────────────────── #


BAN_USER_DATA_KEYS = (
    "ban_target_id",
    "ban_target_fname",
    "ban_reason",
    "ban_admin_id",
    "ban_admin_fname",
    "ban_prompt_msg_id",
    "ban_prompt_chat_id",
    "ban_target_role",
    "ban_executing",
    "ban_locale",
)
WAITING_PROOF = 0
WAITING_UPDATE_CONFIRM = 1
proof = BuildProof("ban", skip_allowed=False)
_PROOF_COLLECT_MAX_S: float = 60.0


@dataclass
class _ProofSession:
    """One in-progress proof collection keyed by (chat_id, user_id)."""

    msgs: list[Message] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    user_data: dict[str, Any] | None = None
    deadline: float = 0.0
    last_arrival: float = 0.0
    flushing: bool = False
    cancelled: bool = False
    flush_task: asyncio.Task[None] | None = None


_proof_sessions: dict[tuple[int, int], _ProofSession] = {}


def _clear_ban_state(user_data: dict[str, Any] | None) -> None:
    """Remove all ban-related keys from user_data."""
    if user_data is None:
        return
    for key in BAN_USER_DATA_KEYS:
        user_data.pop(key, None)


def _cancel_proof_session(user_data: dict[str, Any] | None) -> None:
    """Cancel in-flight flush tasks and clear all ban state."""
    _clear_ban_state(user_data)
    if user_data is None:
        return
    for key in [k for k, s in _proof_sessions.items() if s.user_data is user_data]:
        session = _proof_sessions.pop(key)
        session.cancelled = True
        if session.flush_task is not None:
            session.flush_task.cancel()


# ─────────────────────── Proof session flush ────────────────────── #


async def _flush_session(key: tuple[int, int], bot: Bot) -> None:
    """Flush one proof session after a silence window or the hard cap."""
    session: _ProofSession | None = None
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
        session = _proof_sessions.get(key)
        if session is None or session.flushing or session.cancelled:
            return
        # * Claim is synchronous: Done and this timer can never double-execute.
        session.flushing = True
        if (
            not session.msgs
            or not session.meta.get("ban_target_id")
            or not session.meta.get("ban_admin_id")
        ):
            if session.msgs:
                log.warning("Session flush aborted: meta missing target or admin")
            return
        admin_id = int(session.meta.get("ban_admin_id") or 0)
        try:
            executor_role = await db.users_roles.get_effective_role(
                admin_id, fresh=True
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "Session flush aborted: executor role lookup failed for %d: %s",
                admin_id,
                exc,
            )
            return
        if db.users_roles.role_rank(executor_role) < db.users_roles.role_rank(
            "developer"
        ):
            log.warning(
                "Session flush aborted: executor %d no longer meets developer rank (role=%s)",
                admin_id,
                executor_role,
            )
            return
        log.info(
            "Flushing proof session %s with %d media items", key, len(session.msgs)
        )
        try:
            await _execute_ban(bot, session.msgs, session.meta)
        except Exception:
            log.exception("_execute_ban raised in _flush_session for %s", key)
    except asyncio.CancelledError:
        raise
    finally:
        if session is not None and _proof_sessions.get(key) is session:
            _proof_sessions.pop(key, None)
            _clear_ban_state(session.user_data)


# ────────────────────────── Ban executors ───────────────────────── #


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
    """Build log text, keyboard, and DB update for a re-ban."""
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
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
    """Build log text, keyboard, and DB insert for a fresh ban."""
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
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


async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict[str, Any]) -> None:
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    locale: str | None = meta.get("ban_locale")
    reason: str = meta.get("ban_reason", replies.no_reason(locale, plain=True))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)
    target_locale = await locale_for_user(target_id)
    now = utc_now()
    proof_chat, proof_thread = cfg.proofs
    # * Groups prefetch concurrently with the ban write; cancelled on any failure.
    _groups_task: asyncio.Task[list] = asyncio.create_task(db.groups_db.active_groups())
    try:
        existing = await db.bans_db.get_active_ban(target_id)
        is_update = existing is not None
        bot_username = bot.username or ""
        ban_id = (
            str(existing.get("ban_id", "")) if is_update else db.bans_db.make_ban_id()
        )
        if is_update:
            extras = await db.bans_db.deactivate_extra_active_bans(
                target_id, existing.get("ban_id", "")
            )
            if extras > 0:
                log.warning(
                    "Suppressed %d duplicate active ban(s) for user %d before update",
                    extras,
                    target_id,
                )
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
            caption = parse_logmsg.proof_caption_new(
                target_id, admin_id, admin_fname, now
            )
        proof_msg_id = await upload_proof(bot, msgs, caption, proof_chat, proof_thread)
        proof_link = (
            message_link(proof_chat, proof_msg_id, proof_thread)
            if proof_msg_id
            else None
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
            log_msg_id, db_ok = await _execute_new_ban(
                bot, meta, proof_msg_id, proof_link, now, logs_chat, logs_thread, ban_id
            )
    except asyncio.CancelledError:
        if not _groups_task.done():
            _groups_task.cancel()
        await asyncio.gather(_groups_task, return_exceptions=True)
        raise
    except Exception:
        if not _groups_task.done():
            _groups_task.cancel()
        await asyncio.gather(_groups_task, return_exceptions=True)
        raise
    if not db_ok:
        _db_fail_text = t(
            "banning.db_fail.body",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
        )
        if prompt_msg_id and prompt_chat_id:
            await safe_edit_message(
                bot,
                prompt_chat_id,
                prompt_msg_id,
                _db_fail_text,
                reply_markup=None,
                log_level="debug",
                log_label="Ban DB-fail prompt",
                catch_all=True,
            )
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
    if log_msg_id:
        set_log_result, groups = await asyncio.gather(
            db.bans_db.set_log_message_id(ban_id, log_msg_id),
            _groups_task,
            return_exceptions=True,
        )
        if isinstance(set_log_result, BaseException):
            if isinstance(set_log_result, asyncio.CancelledError):
                raise set_log_result
            log.error(
                "set_log_message_id failed for ban_id=%s: %s", ban_id, set_log_result
            )
        if isinstance(groups, asyncio.CancelledError):
            raise groups
        if isinstance(groups, BaseException):
            log.error("active_groups failed during ban of %d: %s", target_id, groups)
            groups = []
            groups_fetch_failed = True
        else:
            groups_fetch_failed = False
    else:
        try:
            groups = await _groups_task
        except Exception:
            log.exception("active_groups failed during ban of %d", target_id)
            groups = []
            groups_fetch_failed = True
        else:
            groups_fetch_failed = False
    await Demote.redemote_before_fanout(
        bot,
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        trigger="ban",
    )
    groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
    results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )
    failed_groups = [
        (grp, r)
        for grp, r in zip(groups, results, strict=False)
        if isinstance(r, BaseException)
    ]
    transient_groups = [
        (grp, r) for grp, r in failed_groups if not is_benign_telegram_error(r)
    ]
    for grp, exc in failed_groups:
        log.warning(
            "Ban enforcement failed for user=%d in group=%s (%d): %s",
            target_id,
            grp.get("title", ""),
            grp["chat_id"],
            exc,
        )
    failed = log_fanout_error(
        results, action="Ban", total=len(groups), target_id=target_id
    )
    log.info(
        "Ban enforced: target=%d applied=%d/%d",
        target_id,
        len(groups) - failed,
        len(groups),
    )
    applied_line = replies.applied_summary(
        locale,
        "banning.applied",
        total=len(groups),
        failed=failed,
        transient=transient_groups,
    )
    if groups_fetch_failed:
        applied_line += t("banning.applied.scope_warn", locale)
    _pm_text = t(
        "banning.pm.body",
        target_locale,
        community=cfg.community_name,
        reason=reason,
    )
    _pm_kb = keyboards.appeal_button_kb(bot_username, ban_id, target_locale)
    summary = t(
        "banning.summary.body",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        reason=reason,
        applied=Safe(applied_line),
    )
    if prompt_msg_id and prompt_chat_id:
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
        throw_if_cancelled((edit_result, upsert_result, pm_result, markup_result))
        if isinstance(markup_result, BaseException):
            log.debug("Ban summary markup clear failed: %s", markup_result)
        if isinstance(edit_result, BaseException):
            log.debug("Ban summary prompt edit failed: %s", edit_result)
            try:
                await bot.send_message(
                    prompt_chat_id,
                    summary,
                    parse_mode="MarkdownV2",
                )
            except Exception as exc:
                log.debug("Ban summary fallback send failed: %s", exc)
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
        throw_if_cancelled((upsert_result, pm_result))
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


async def demote_ban_target(
    msg: Message,
    bot: Bot,
    target_id: int,
    target_fname: str,
    target_role: str | None,
    admin_id: int,
    admin_fname: str,
) -> bool:
    """Auto-demote a role-holding ban target; reply and abort on failure."""
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
    """Build the proof-collection prompt text and keyboard."""
    return (
        proof.noted_prompt(
            "ban", reason, user_ref(target_id, target_fname), locale=locale
        ),
        proof.keyboard(locale),
    )


# ─────────────────────── Re-ban confirmation ────────────────────── #


async def on_ban_update_continue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Proceed from the re-ban confirmation to proof collection."""
    q = update.callback_query
    msg = update.effective_message
    if q is None or msg is None or ctx.user_data is None:
        return ConversationHandler.END
    if not isinstance(msg, Message):
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    await q.answer()
    tapper = update.effective_user
    if tapper is None or not await decorators.recheck_executor_rank(
        msg, tapper.id, min_role="developer"
    ):
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    target_id = int(ctx.user_data.get("ban_target_id", 0) or 0)
    target_fname = str(ctx.user_data.get("ban_target_fname") or target_id)
    reason = str(ctx.user_data.get("ban_reason") or "")
    admin_id = int(ctx.user_data.get("ban_admin_id", 0) or 0)
    admin_fname = str(ctx.user_data.get("ban_admin_fname") or "Admin")
    target_role = ctx.user_data.get("ban_target_role")
    if not target_id or not reason:
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
        for key in BAN_USER_DATA_KEYS:
            ctx.user_data.pop(key, None)
        return ConversationHandler.END
    return WAITING_PROOF


# ──────────────────── Proof collection handlers ─────────────────── #


async def on_proof_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Buffer proof media into the live session; flush on Done or silence."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if msg is None or chat is None or user is None:
        return WAITING_PROOF
    if ctx.user_data is None:
        return ConversationHandler.END
    if not ctx.user_data.get("ban_target_id"):
        return ConversationHandler.END
    key = (chat.id, user.id)
    session = _proof_sessions.get(key)
    if session is not None and session.flushing:
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
        if not ctx.user_data.get("ban_target_id"):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Ban done-proof zombie answer failed: %s", exc)
            return ConversationHandler.END
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
    tap_msg = update.effective_message
    if user is None or not isinstance(tap_msg, Message):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        _proof_sessions.pop(key, None)
        _clear_ban_state(session.user_data)
        return ConversationHandler.END
    if not await decorators.recheck_executor_rank(
        tap_msg, user.id, min_role="developer"
    ):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        _proof_sessions.pop(key, None)
        _clear_ban_state(session.user_data)
        return ConversationHandler.END
    try:
        await _execute_ban(ctx.bot, session.msgs, session.meta)
    except Exception:
        log.exception("Done-proof _execute_ban raised")
    finally:
        if _proof_sessions.get(key) is session:
            _proof_sessions.pop(key, None)
            _clear_ban_state(session.user_data)
    return ConversationHandler.END


async def on_proof_unexpected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Reject unexpected message types during proof collection."""
    if ctx.user_data is not None and not ctx.user_data.get("ban_target_id"):
        return ConversationHandler.END
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
    await safe_edit_cb(
        q, t("banning.state.cancelled", await locale_for_update(update), plain=False)
    )
    await clear_markup_cb(q)
    return ConversationHandler.END


async def on_proof_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Notify the user that the proof window expired."""
    had_state = bool((ctx.user_data or {}).get("ban_target_id"))
    prompt_chat: int | None = None
    prompt_msg_id: int | None = None
    if ctx.user_data is not None:
        raw_chat = ctx.user_data.get("ban_prompt_chat_id")
        raw_msg = ctx.user_data.get("ban_prompt_msg_id")
        prompt_chat = raw_chat if isinstance(raw_chat, int) else None
        prompt_msg_id = raw_msg if isinstance(raw_msg, int) else None
    _cancel_proof_session(ctx.user_data)
    if prompt_chat and prompt_msg_id:
        try:
            await ctx.bot.edit_message_reply_markup(
                chat_id=prompt_chat, message_id=prompt_msg_id
            )
        except Exception as exc:
            log.debug("Ban proof-timeout markup clear failed: %s", exc)
    if not had_state:
        return ConversationHandler.END
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
    """Return the ban ConversationHandler with the given entry-point function."""
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


__all__ = [
    "BAN_USER_DATA_KEYS",
    "WAITING_PROOF",
    "WAITING_UPDATE_CONFIRM",
    "_PROOF_COLLECT_MAX_S",
    "ConversationHandler",
    "_ProofSession",
    "_cancel_proof_session",
    "_clear_ban_state",
    "_execute_ban",
    "_execute_ban_update",
    "_execute_new_ban",
    "_flush_session",
    "_proof_sessions",
    "asyncio",
    "ban_conversation",
    "db",
    "demote_ban_target",
    "locale_for_user",
    "log",
    "on_ban_update_continue",
    "on_cancel_proof",
    "on_done_proof",
    "on_proof_received",
    "on_proof_timeout",
    "on_proof_unexpected",
    "proof",
    "proof_prompt_content",
]
