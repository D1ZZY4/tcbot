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
from tcbot.modules.helper import guards, keyboards, messages
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.messages import (
    appeal_deep_link,
    clear_markup_cb,
    message_link,
    replies,
    safe_edit_cb,
    safe_edit_message,
    safe_reply,
)
from tcbot.modules.helper.pipelines.demote_flow import (
    demote_before_enforcement,
)
from tcbot.modules.helper.pipelines.proof_flow import (
    PROOF_MEDIA_FILTER,
    BuildProof,
    upload_proof_media,
)
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import (
    fan_out,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER
from tcbot.utils.time_and_date import monotonic, to_utc, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from telegram import Bot, InlineKeyboardMarkup
    from telegram.ext.filters import BaseFilter

    from tcbot.database.documents import BanDoc, GroupDoc

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
    "ban_executing",
    "ban_locale",
)
WAITING_PROOF = 0
WAITING_UPDATE_CONFIRM = 1
proof = BuildProof("ban", skip_allowed=False)
_PROOF_COLLECT_MAX_S: float = 60.0
# * Upper bound for the shutdown drain of the pending proof flushes.
_PROOF_DRAIN_TIMEOUT_S: float = 30.0


@dataclass
class _ProofSession:
    """One in-progress proof collection keyed by (chat_id, user_id)."""

    msgs: list[Message] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    deadline: float = 0.0
    last_arrival: float = 0.0
    flushing: bool = False
    cancelled: bool = False
    flush_task: asyncio.Task[None] | None = None


_proof_sessions: dict[tuple[int, int], _ProofSession] = {}


def _clear_ban_state(scope: dict[str, Any] | None) -> None:
    """Remove all ban-related keys from the conversation scope."""
    if scope is None:
        return
    for key in BAN_USER_DATA_KEYS:
        scope.pop(key, None)


def _cancel_proof_session(scope: dict[str, Any] | None) -> None:
    """Cancel in-flight flush tasks and clear all ban state."""
    _clear_ban_state(scope)
    if scope is None:
        return
    for key in [k for k, s in _proof_sessions.items() if s.scope is scope]:
        session = _proof_sessions.pop(key)
        session.cancelled = True
        if session.flush_task is not None:
            session.flush_task.cancel()


async def drain_proof_sessions() -> None:
    """Let the pending proof flushes finish so no ban is left half-applied.

    A flush that is already executing the ban must not be cancelled: the
    ban record may already be stored while the Telegram fan-out is still
    running, and cancelling there would leave the federation with a ban
    nobody was told about. The drain waits for the running flushes and
    only cancels the ones that are still waiting for their silence window.
    """
    pending = [s.flush_task for s in _proof_sessions.values() if s.flush_task]
    if not pending:
        return
    live = [t for t in pending if not t.done()]
    if not live:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*live, return_exceptions=True),
            timeout=_PROOF_DRAIN_TIMEOUT_S,
        )
        return
    except TimeoutError:
        log.warning(
            "Ban proof flush still running after %.0fs; cancelling.",
            _PROOF_DRAIN_TIMEOUT_S,
        )
    for task in live:
        if not task.done():
            task.cancel()
    await asyncio.gather(*[t for t in live if not t.done()], return_exceptions=True)


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
            _clear_ban_state(session.scope)


# ────────────────────────── Ban executors ───────────────────────── #


async def _execute_ban_record(
    bot: Bot,
    meta: dict[str, Any],
    *,
    existing: BanDoc | None,
    ban_id: str,
    proof_msg_id: int | None,
    proof_link: str | None,
    prev_proof_link: str | None,
    now: datetime,
    logs_chat: int,
    logs_thread: int | None,
    proof_chat: int,
) -> tuple[int, bool, str]:
    """Write the ban record and post the federation log.

    One executor for the fresh-ban and the re-ban path: the two differ
    only in the log template, the keyboard's previous-proof link, and the
    database write. Returns ``(log_message_id, db_ok, canonical_ban_id)``.

    The record is written before the log is rendered: a concurrent ban for
    the same target can win the insert race, and the record that survives
    owns the ban id. The log, its appeal link, and the target's appeal
    button must all name that record.
    """
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    reason: str = meta.get(
        "ban_reason", replies.no_reason(meta.get("ban_locale"), plain=True)
    )
    bot_username = bot.username or ""
    old_admin_id = (
        int(existing.get("actor_user_id", admin_id)) if existing else admin_id
    )
    old_admin_fname = admin_fname
    if existing is not None:
        try:
            old_admin_fname = await db.users_cache.get_first_name(old_admin_id, "Admin")
        except Exception as exc:
            log.debug("Old-admin name fallback for %d: %s", old_admin_id, exc)
            old_admin_fname = "Admin"
    written: BanDoc | None
    try:
        if existing is not None:
            old_proof_msg_id = int(existing.get("proof_message_id", 0))
            old_log_msg_id = int(existing.get("log_message_id", 0))
            new_proof_msg_id = proof_msg_id if proof_msg_id else old_proof_msg_id
            written = await db.bans_db.update_ban(
                ban_id,
                reason,
                admin_id,
                new_proof_msg_id,
                0,
                old_proof_msg_id,
                old_log_msg_id,
                destination_chat_id=proof_chat,
            )
        else:
            written = await db.bans_db.create_ban(
                target_id,
                reason,
                admin_id,
                proof_msg_id or 0,
                0,
                ban_id,
                destination_chat_id=proof_chat,
            )
    except Exception:
        log.exception("Ban record write failed for ban_id=%s", ban_id)
        return 0, False, ban_id
    # * The canonical id lives on the stored record: a concurrent ban that
    # * won the insert race owns the record now.
    canonical_ban_id = str(written.get("ban_id") or ban_id) if written else ban_id
    if canonical_ban_id != ban_id:
        log.warning(
            "Ban %s lost the insert race to %s; logging the canonical record",
            ban_id,
            canonical_ban_id,
        )
    if existing is not None:
        log_text = messages.ban_update_log(
            target_id,
            target_fname,
            admin_id,
            admin_fname,
            old_admin_id,
            old_admin_fname,
            reason,
            canonical_ban_id,
            to_utc(existing.get("timestamp", utc_now())),
        )
    else:
        log_text = messages.ban_log(
            target_id,
            target_fname,
            admin_id,
            admin_fname,
            reason,
            canonical_ban_id,
            now,
        )
    kb = (
        keyboards.ban_log_kb(
            target_id,
            proof_link,
            appeal_deep_link(bot_username, canonical_ban_id),
            meta.get("ban_locale"),
            previous_proof_link=prev_proof_link or None,
        )
        if proof_link
        else None
    )
    send_kwargs: dict[str, Any] = {
        "parse_mode": "MarkdownV2",
        "message_thread_id": logs_thread,
    }
    if kb is not None:
        send_kwargs["reply_markup"] = kb
    try:
        log_msg = await bot.send_message(logs_chat, log_text, **send_kwargs)
    except Exception:
        log.exception("Ban log send failed for ban_id=%s", canonical_ban_id)
        return 0, True, canonical_ban_id
    log_msg_id = log_msg.message_id
    log.info("Ban log posted: ban_id=%s msg_id=%s", canonical_ban_id, log_msg_id)
    return log_msg_id, True, canonical_ban_id


def _enforcement_scope(
    groups: Sequence[GroupDoc], origin_chat_id: int
) -> list[dict[str, Any]]:
    """Return the chats a ban is applied in.

    The scope is the connected groups plus the federation primary group.
    The origin group joins it: when the connected-group list cannot be
    read, the ban must still land where the moderator issued it. A ban
    issued from the bot PM has no group origin, so it never joins and the
    scope stays the primary group alone.
    """
    origin = origin_chat_id if origin_chat_id < 0 else 0
    return db.groups_db.with_primary_groups(groups, (cfg.main_group,), origin)


async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict[str, Any]) -> None:
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    locale: str | None = meta.get("ban_locale")
    reason: str = meta.get("ban_reason", replies.no_reason(locale, plain=True))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)
    now = utc_now()
    proof_chat, proof_thread = cfg.proofs
    # * Re-check the executor against the target before anything is
    # * recorded or uploaded. The entry command compared the two roles,
    # * but the proof window can stay open for a minute, and a target
    # * promoted in that window must not be banned by a moderator who no
    # * longer outranks them. The check runs first so a refused ban
    # * leaves no record, no proof, and no partial fan-out behind.
    refusal = await guards.enforcement_refusal(
        admin_id,
        target_id,
        min_role="developer",
        action="Ban",
        locale=locale,
    )
    if refusal is not None:
        if prompt_msg_id and prompt_chat_id:
            await safe_edit_message(
                bot,
                prompt_chat_id,
                prompt_msg_id,
                refusal,
                log_level="debug",
                log_label="Ban rank-refusal prompt",
                catch_all=True,
            )
        return
    # * Groups prefetch concurrently with the ban write; cancelled on any failure.
    _groups_task: asyncio.Task[list] = asyncio.create_task(db.groups_db.active_groups())
    try:
        # * Target locale and active-ban read are independent; gather them so
        # * the critical ban path pays one round trip, not two.
        target_locale, existing = await asyncio.gather(
            locale_for_user(target_id),
            db.bans_db.get_active_ban(target_id),
        )
        is_update = existing is not None
        bot_username = bot.username or ""
        ban_id = (
            str(existing.get("ban_id", "")) if is_update else db.bans_db.make_ban_id()
        )
        if is_update:
            prev_proof_msg_id = existing.get("proof_message_id")
            prev_proof_link = (
                message_link(proof_chat, prev_proof_msg_id, proof_thread)
                if prev_proof_msg_id
                else None
            )
            caption = messages.proof_caption_update(
                target_id,
                admin_id,
                admin_fname,
                existing.get("timestamp", now),
                prev_proof_link,
            )
        else:
            prev_proof_link = None
            caption = messages.proof_caption_new(target_id, admin_id, admin_fname, now)
        upload = await upload_proof_media(bot, msgs, caption)
        proof_msg_id = upload.message_id
        proof_link = upload.link
        logs_chat, logs_thread = cfg.logs
        # * Proof is required for new bans: a proof-less record would let
        # * /check and audit logs reference evidence that never landed.
        # * Updates keep the old proof via the re-ban branch.
        if not is_update and not upload.landed:
            log.error(
                "Ban aborted for target=%d: proof upload returned None", target_id
            )
            _proof_fail_text = t(
                "banning.proof_fail.body",
                locale,
                user=Safe(user_ref(target_id, target_fname)),
            )
            if prompt_msg_id and prompt_chat_id:
                await safe_edit_message(
                    bot,
                    prompt_chat_id,
                    prompt_msg_id,
                    _proof_fail_text,
                    reply_markup=None,
                    log_level="debug",
                    log_label="Ban proof-fail prompt",
                    catch_all=True,
                )
            if not _groups_task.done():
                _groups_task.cancel()
            await asyncio.gather(_groups_task, return_exceptions=True)
            return
        log_msg_id, db_ok, ban_id = await _execute_ban_record(
            bot,
            meta,
            existing=existing if is_update else None,
            ban_id=ban_id,
            proof_msg_id=proof_msg_id,
            proof_link=proof_link,
            prev_proof_link=prev_proof_link if is_update else None,
            now=now,
            logs_chat=logs_chat,
            logs_thread=logs_thread,
            proof_chat=proof_chat,
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
    await demote_before_enforcement(
        bot,
        target_id,
        target_fname,
        trigger="ban",
        executor_id=admin_id,
        executor_fname=admin_fname,
    )
    # * The origin group joins the scope: a failed connected-group fetch
    # * must not leave the ban unenforced where the moderator issued it.
    # * A ban issued from the bot PM has no group origin, so it never joins
    # * and the scope stays the primary group alone.
    groups = _enforcement_scope(groups, prompt_chat_id)
    results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )
    outcome = summarize_fanout(groups, results, action="Ban", target_id=target_id)
    failed = outcome.failed
    log.info(
        "Ban enforced: target=%d applied=%d/%d",
        target_id,
        outcome.applied,
        outcome.total,
    )
    applied_line = replies.applied_summary(
        locale,
        "banning.applied",
        total=outcome.total,
        failed=failed,
        transient=outcome.transient,
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
    scope = flow_scope(ctx, update)
    if not isinstance(msg, Message):
        for key in BAN_USER_DATA_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    await q.answer()
    tapper = update.effective_user
    if tapper is None or not await guards.recheck_executor_rank(
        msg, tapper.id, min_role="developer"
    ):
        for key in BAN_USER_DATA_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    target_id = int(scope.get("ban_target_id", 0) or 0)
    target_fname = str(scope.get("ban_target_fname") or target_id)
    reason = str(scope.get("ban_reason") or "")
    if not target_id or not reason:
        return ConversationHandler.END
    # * The demote runs at enforcement time, not here: the proof step that
    # * follows is still cancelable, and a demote that lands on a cancelled
    # * flow strips a federation role and tells the target they were banned
    # * without the re-ban ever happening.
    text, kb = proof_prompt_content(
        target_id, target_fname, reason, await locale_for_update(update)
    )
    try:
        await q.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=kb)
    except Exception as exc:
        log.debug("Ban continue prompt edit failed: %s", exc)
        for key in BAN_USER_DATA_KEYS:
            scope.pop(key, None)
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
    scope = flow_scope(ctx, update)
    if not scope.get("ban_target_id"):
        return ConversationHandler.END
    key = (chat.id, user.id)
    session = _proof_sessions.get(key)
    if session is not None and session.flushing:
        return ConversationHandler.END
    if session is None:
        scope["ban_executing"] = True
        now = monotonic()
        session = _ProofSession(
            # * The snapshot carries this conversation's payload only, so a
            # * second action in another group cannot change the target the
            # * flush enforces against.
            meta=dict(scope),
            scope=scope,
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
    scope = flow_scope(ctx, update)
    session = _proof_sessions.get(key)
    if session is None or session.flushing or not session.msgs:
        if not scope.get("ban_target_id"):
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
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    tap_msg = update.effective_message
    if user is None or not isinstance(tap_msg, Message):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        _proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    if not await guards.recheck_executor_rank(tap_msg, user.id, min_role="developer"):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        _proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    try:
        await _execute_ban(ctx.bot, session.msgs, session.meta)
    except Exception:
        log.exception("Done-proof _execute_ban raised")
    finally:
        if _proof_sessions.get(key) is session:
            _proof_sessions.pop(key, None)
            _clear_ban_state(session.scope)
    return ConversationHandler.END


async def on_proof_unexpected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Reject unexpected message types during proof collection."""
    if ctx.user_data is not None and not flow_scope(ctx, update).get("ban_target_id"):
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
    scope = flow_scope(ctx, update)
    # * Once flushing has started the ban is executing; cancelling mid-
    # * _execute_ban would cancel the in-flight fan-out (partial ban, DB
    # * written, no summary). Ignore the tap and let execution finish.
    for sess in list(_proof_sessions.values()):
        if sess.scope is scope and sess.flushing:
            await q.answer()
            return ConversationHandler.END
    await q.answer()
    _cancel_proof_session(scope)
    await safe_edit_cb(
        q, t("banning.state.cancelled", await locale_for_update(update), plain=False)
    )
    await clear_markup_cb(q)
    return ConversationHandler.END


async def on_proof_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Notify the user that the proof window expired."""
    scope = flow_scope(ctx, update)
    had_state = bool(scope.get("ban_target_id"))
    prompt_chat: int | None = None
    prompt_msg_id: int | None = None
    raw_chat = scope.get("ban_prompt_chat_id")
    raw_msg = scope.get("ban_prompt_msg_id")
    prompt_chat = raw_chat if isinstance(raw_chat, int) else None
    prompt_msg_id = raw_msg if isinstance(raw_msg, int) else None
    # * Once flushing has started the ban is executing. The timeout is the
    # * conversation fallback, so it fires for any prefixed command the
    # * moderator sends during the window. Cancelling here would cancel the
    # * in-flight fan-out after the ban record and the federation log were
    # * written: the federation would carry a ban no group enforces. The
    # * running flush owns the prompt and replaces it with its summary.
    for sess in list(_proof_sessions.values()):
        if sess.scope is scope and sess.flushing:
            log.info("Ban proof timeout ignored: the ban is already executing.")
            return ConversationHandler.END
    _cancel_proof_session(scope)
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
