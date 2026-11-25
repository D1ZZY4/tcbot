# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban executor + proof collection conversation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pyrogram import Client, ContinuePropagation
from pyrogram.errors import ChatAdminRequired
from pyrogram.types import InlineKeyboardMarkup, Message

from tcbot import cfg, enforcement_worker
from tcbot import database as db
from tcbot.modules.helper import buttons, guards, messages
from tcbot.modules.helper.context import Ctx, bot_identity, chat_id_of
from tcbot.modules.helper.handlers import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
)
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.messages import (
    appeal_deep_link,
    clear_markup_cb,
    message_link,
    replies,
    reply_rich,
    safe_edit_cb,
    safe_edit_message,
)
from tcbot.modules.helper.pipelines.ban_confirmation import (
    on_ban_update_continue,
    stale_ban_callback,
)
from tcbot.modules.helper.pipelines.demote_actions import (
    demote_before_enforcement,
)
from tcbot.modules.helper.pipelines.proof_post import upload_proof_media
from tcbot.modules.helper.pipelines.proof_session import (
    ProofSession,
    proof_sessions,
    replace_live_session,
)
from tcbot.modules.helper.pipelines.proof_steps import PROOF_MEDIA_FILTER, BuildProof
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.dispatch import (
    fan_out,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import (
    ALL_PREFIXES_CMD_FILTER,
    build_conversation_escape_filter,
)
from tcbot.utils.time_and_date import monotonic, to_utc, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from pyrogram.filters import Filter as BaseFilter

    from tcbot.database.documents import BanDoc, EvidenceItemDoc, GroupDoc

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
    "ban_locale",
    "ban_rules",
    "ban_rules_note",
    "ban_rules_note_awaiting",
)
WAITING_PROOF = 0
WAITING_UPDATE_CONFIRM = 1
proof = BuildProof("ban", skip_allowed=False)
_PROOF_COLLECT_MAX_S: float = 60.0


def _clear_ban_state(scope: dict[str, Any] | None) -> None:
    """Remove all ban-related keys from the conversation scope."""
    if scope is None:
        return
    for key in BAN_USER_DATA_KEYS:
        scope.pop(key, None)


async def _cancel_proof_session(scope: dict[str, Any] | None) -> None:
    """Cancel flushes and await them before clearing state.

    An unawaited flush cleanup could delete a newer ban's scope keys.
    """
    _clear_ban_state(scope)
    if scope is None:
        return
    cancelled: list[asyncio.Task[None]] = []
    for key, session in proof_sessions.items():
        if session.scope is not scope:
            continue
        proof_sessions.pop(key, session)
        session.cancelled = True
        if session.flush_task is not None:
            session.flush_task.cancel()
            cancelled.append(session.flush_task)
    if cancelled:
        await asyncio.gather(*cancelled, return_exceptions=True)


async def replace_live_proof_session(
    scope: dict[str, Any], chat_id: int, user_id: int
) -> bool:
    """Retire an unfinished session before a re-entry replaces its scope."""
    return await replace_live_session(
        proof_sessions, scope, chat_id, user_id, _clear_ban_state
    )


async def drain_proof_sessions() -> None:
    """Let pending proof flushes finish so no ban is left half-applied."""
    await proof_sessions.drain()


# ─────────────────────── Proof session flush ────────────────────── #


async def _flush_session(key: tuple[int, int], bot: Client) -> None:
    """Flush one proof session after a silence window or the hard cap."""
    # * Own the session from the first await, so a cancellation during the
    # * silence window still releases the registry entry in the finally block.
    session: ProofSession | None = proof_sessions.get(key)
    if session is None:
        return
    try:
        while True:
            # * Sleep no longer than the collection deadline: a deployment
            # * with a very large debounce value must not defeat the hard
            # * 60-second cap and leave a ban unflushed indefinitely.
            remaining = session.deadline - monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(cfg.album_debounce, remaining))
            if (
                proof_sessions.get(key) is not session
                or session.cancelled
                or session.flushing
            ):
                return
            if (
                monotonic() - session.last_arrival >= cfg.album_debounce
                or monotonic() >= session.deadline
            ):
                break
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
        # * _execute_ban runs the shared enforcement gate before any record,
        # * proof, or fan-out, and it edits the prompt when the executor no
        # * longer holds the rank. A second rank read here could only abort
        # * the flush silently after the moderator already sent the proof.
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
        if session is not None and proof_sessions.get(key) is session:
            proof_sessions.pop(key, None)
            _clear_ban_state(session.scope)


# ────────────────────────── Ban executors ───────────────────────── #


async def _execute_ban_record(
    bot: Client,
    meta: dict[str, Any],
    *,
    existing: BanDoc | None,
    ban_id: str,
    proof_msg_id: int | None,
    proof_link: str | None,
    prev_proof_link: str | None,
    now: datetime,
    proof_chat: int,
    proof_thread: int | None,
    proof_items: Sequence[EvidenceItemDoc] | None,
    proof_expected_count: int,
    enforcement_chat_ids: Sequence[int],
) -> tuple[int, bool, str, int | None]:
    """Write the ban record and post the federation log.

    The fresh-ban and re-ban paths differ only in the log template, the
    previous-proof link, and the database write. Returns
    ``(log_message_id, db_ok, canonical_ban_id, enforcement_run_id)``.
    The record is written first so a concurrent insert race names the
    surviving record in the log, the appeal link, and the target button.
    """
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    reason: str = meta.get(
        "ban_reason", replies.no_reason(meta.get("ban_locale"), plain=True)
    )
    rule_ids: list[int] = list(meta.get("ban_rules") or [])
    rule_note: str | None = meta.get("ban_rules_note")
    raw_origin = meta.get("ban_prompt_chat_id")  # negative = connected chat
    link_context = int(raw_origin) if raw_origin and int(raw_origin) < 0 else None
    bot_username = (await bot_identity(bot)).username or ""
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
                proof_items=proof_items,
                proof_expected_count=proof_expected_count,
                destination_thread_id=proof_thread,
                enforcement_chat_ids=enforcement_chat_ids,
                origin_chat_id=link_context,
                rule_item_ids=rule_ids,
                rule_selection_note=rule_note,
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
                proof_items=proof_items,
                proof_expected_count=proof_expected_count,
                destination_thread_id=proof_thread,
                enforcement_chat_ids=enforcement_chat_ids,
                origin_chat_id=link_context,
                rule_item_ids=rule_ids,
                rule_selection_note=rule_note,
            )
    except Exception:
        log.exception("Ban record write failed for ban_id=%s", ban_id)
        return 0, False, ban_id, None
    # * The canonical id lives on the stored record: a concurrent ban that
    # * won the insert race owns the record now.
    canonical_ban_id = str(written.get("ban_id") or ban_id) if written else ban_id
    enforcement_run_id = (
        int(written.get("enforcement_run_id") or 0) if written else 0
    ) or None
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
        buttons.ban_log_btn(
            target_id,
            proof_link,
            appeal_deep_link(bot_username, canonical_ban_id),
            meta.get("ban_locale"),
            previous_proof_link=prev_proof_link or None,
        )
        if proof_link
        else None
    )
    try:
        log_msg = await messages.send_log(bot, log_text, reply_markup=kb)
    except Exception:
        log.exception("Ban log send failed for ban_id=%s", canonical_ban_id)
        return 0, True, canonical_ban_id, enforcement_run_id
    log_msg_id = log_msg.id
    log.info("Ban log posted: ban_id=%s msg_id=%s", canonical_ban_id, log_msg_id)
    return log_msg_id, True, canonical_ban_id, enforcement_run_id


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


async def _execute_ban(bot: Client, msgs: list[Message], meta: dict[str, Any]) -> None:
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
                parse_mode=None,
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
        bot_username = (await bot_identity(bot)).username or ""
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
        # * Proof is required for new bans: a proof-less record would let
        # * /check and audit logs reference evidence that never landed.
        # * A gallery that lost a file is a partial upload, and the schema
        # * refuses a manual ban that attaches one: the moderator has to
        # * retry the evidence instead of filing a ban on incomplete proof.
        # * Updates keep the old proof via the re-ban branch.
        proof_incomplete = (
            upload.expected_item_count > 0
            and len(upload.items) < upload.expected_item_count
        )
        if proof_incomplete or (not is_update and not upload.landed):
            log.error(
                "Ban aborted for target=%d: proof upload returned %d/%d items",
                target_id,
                len(upload.items),
                upload.expected_item_count,
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
        try:
            groups = await _groups_task
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("active_groups failed during ban of %d", target_id)
            groups = []
            groups_fetch_failed = True
        else:
            groups_fetch_failed = False
        # * The origin group joins the scope: a failed connected-group fetch
        # * must not leave the ban unenforced where the moderator issued it.
        # * A ban issued from the bot PM has no group origin, so it never
        # * joins and the scope stays the primary group alone.
        groups = _enforcement_scope(groups, prompt_chat_id)
        # * The proof upload can outlive a demotion or a target promotion.
        # * Re-run the same fresh executor-versus-target gate immediately
        # * before the decision is written; a refused action leaves no ban
        # * record and no queued delivery.
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
                    parse_mode=None,
                    reply_markup=None,
                    log_level="debug",
                    log_label="Ban rank-refusal after proof",
                    catch_all=True,
                )
            return
        # * The demote gate must run before the decision write: create_ban
        # * queues a durable run, so an "owner" verdict discovered afterwards
        # * would leave that run to be delivered by the worker anyway.
        enforced_role = await demote_before_enforcement(
            bot,
            target_id,
            target_fname,
            trigger="ban",
            executor_id=admin_id,
            executor_fname=admin_fname,
        )
        if enforced_role == "owner":
            # * The target became Owner after the entry gates. The protected
            # * role cannot be demoted, so no record and no run may be queued.
            log.warning(
                "Ban refused: target=%d became Owner before the decision write",
                target_id,
            )
            if prompt_msg_id and prompt_chat_id:
                await safe_edit_message(
                    bot,
                    prompt_chat_id,
                    prompt_msg_id,
                    t(
                        "identity.refuse.ban.owner",
                        locale,
                        line=Safe(user_ref(target_id, target_fname)),
                    ),
                    reply_markup=None,
                    log_level="debug",
                    log_label="Ban Owner protection",
                    catch_all=True,
                )
            return
        log_msg_id, db_ok, ban_id, enforcement_run_id = await _execute_ban_record(
            bot,
            meta,
            existing=existing if is_update else None,
            ban_id=ban_id,
            proof_msg_id=proof_msg_id,
            proof_link=proof_link,
            prev_proof_link=prev_proof_link if is_update else None,
            now=now,
            proof_chat=proof_chat,
            proof_thread=proof_thread,
            proof_items=upload.documents(),
            proof_expected_count=upload.expected_item_count,
            enforcement_chat_ids=[int(grp["chat_id"]) for grp in groups],
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
                "Ban DB write failed for target=%d with no prompt to ctx",
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
        try:
            await db.bans_db.set_log_message_id(ban_id, log_msg_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("set_log_message_id failed for ban_id=%s", ban_id)
    applied = 0
    total = len(groups)
    failed = 0
    pending = 0
    transient: list[tuple[dict[str, Any], BaseException]] = []
    if enforcement_run_id is not None:
        try:
            await enforcement_worker.deliver_queued_run(bot, enforcement_run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Ban delivery failed for run %s; it stays queued", enforcement_run_id
            )
        try:
            report = await db.enforcement_db.run_report(enforcement_run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ban run report failed for run %s", enforcement_run_id)
            report = None
        failed_targets = db.enforcement_db.failed_report_targets(report)
        delivery = db.enforcement_db.delivery_outcome(report, len(groups))
        total = delivery.total
        applied = delivery.applied
        failed = delivery.failed
        pending = delivery.pending
        transient = [
            (
                {
                    "chat_id": target.get("chat_id", 0),
                    "title": target.get("title") or "",
                },
                RuntimeError(str(target.get("last_error_detail") or "failed")),
            )
            for target in failed_targets
        ]
        for group, error in transient:
            log.warning(
                "Ban enforcement failed for user=%d in group=%s (%d): %s",
                target_id,
                group.get("title", ""),
                group.get("chat_id", 0),
                error,
            )
        if failed:
            log.error(
                "Ban enforcement for user=%d left %d/%d group(s) failed (run %s)",
                target_id,
                failed,
                total,
                enforcement_run_id,
            )
    else:
        # * Legacy callers without a queued run keep the direct fan-out.
        results = await fan_out(
            [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
        )
        outcome = summarize_fanout(groups, results, action="Ban", target_id=target_id)
        applied = outcome.applied
        total = outcome.total
        failed = outcome.failed
        transient = list(outcome.transient)
    log.info(
        "Ban enforced: target=%d applied=%d/%d pending=%d",
        target_id,
        applied,
        total,
        pending,
    )
    applied_line = replies.applied_summary(
        locale,
        "banning.applied",
        total=total,
        failed=failed,
        pending=pending,
        transient=transient,
    )
    if groups_fetch_failed:
        applied_line += t("banning.applied.scope_warn", locale)
    _pm_text = t(
        "banning.pm.body",
        target_locale,
        community=cfg.community_name,
        reason=reason,
    )
    _pm_btn = buttons.appeal_button_btn(bot_username, ban_id, target_locale)
    summary = t(
        "banning.summary.body",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        reason=reason,
        applied=Safe(applied_line),
    )
    if prompt_msg_id and prompt_chat_id:
        edit_result, upsert_result, pm_result, markup_result = await asyncio.gather(
            safe_edit_message(bot, prompt_chat_id, prompt_msg_id, summary),
            db.users_cache.upsert_user(target_id, None, target_fname),
            messages.send_text(bot, target_id, _pm_text, reply_markup=_pm_btn),
            bot.edit_message_reply_markup(
                chat_id=prompt_chat_id,
                message_id=prompt_msg_id,
                reply_markup=InlineKeyboardMarkup([]),
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((edit_result, upsert_result, pm_result, markup_result))
        if isinstance(markup_result, BaseException):
            log.debug("Ban summary markup clear failed: %s", markup_result)
        if isinstance(edit_result, BaseException):
            log.debug("Ban summary prompt edit failed: %s", edit_result)
            try:
                await messages.send_text(bot, prompt_chat_id, summary)
            except Exception as exc:
                log.debug("Ban summary fallback send failed: %s", exc)
        if isinstance(upsert_result, BaseException):
            log.error("upsert_user failed for target=%d: %s", target_id, upsert_result)
    else:
        upsert_result, pm_result = await asyncio.gather(
            db.users_cache.upsert_user(target_id, None, target_fname),
            messages.send_text(bot, target_id, _pm_text, reply_markup=_pm_btn),
            return_exceptions=True,
        )
        throw_if_cancelled((upsert_result, pm_result))
        if isinstance(upsert_result, BaseException):
            log.error(
                "upsert_user (no-prompt path) failed for target=%d: %s",
                target_id,
                upsert_result,
            )
    if isinstance(pm_result, ChatAdminRequired):
        log.info(
            "Cannot DM banned user %d: user has not started the bot or has blocked it",
            target_id,
        )
    elif isinstance(pm_result, BaseException):
        log.warning("Failed to send ban PM to user %d: %s", target_id, pm_result)


# ──────────────────── Proof collection handlers ─────────────────── #


async def on_proof_received(ctx: Ctx) -> int:
    """Buffer proof media into the live session; flush on Done or silence."""
    msg = ctx.effective_message
    chat = ctx.effective_chat
    user = ctx.effective_user
    if msg is None or chat is None or user is None:
        return WAITING_PROOF
    if ctx.user_data is None:
        return ConversationHandler.END
    scope = flow_scope(ctx)
    if not scope.get("ban_target_id"):
        return ConversationHandler.END
    key = (chat_id_of(chat), user.id)
    session = proof_sessions.get(key)
    if session is not None and session.flushing:
        return ConversationHandler.END
    if session is None:
        now = monotonic()
        session = ProofSession(
            # * The snapshot carries this conversation's payload only, so a
            # * second action in another group cannot change the target the
            # * flush enforces against.
            meta=dict(scope),
            scope=scope,
            deadline=now + _PROOF_COLLECT_MAX_S,
            last_arrival=now,
        )
        proof_sessions.add(key, session)
        task = asyncio.create_task(_flush_session(key, ctx.bot))
        session.flush_task = task
    else:
        session.last_arrival = monotonic()
    session.msgs.append(msg)
    return WAITING_PROOF


async def on_done_proof(ctx: Ctx) -> int | None:
    """Flush collected proof immediately when the moderator taps Done."""
    q = ctx.callback_query
    if q is None or ctx.user_data is None:
        return ConversationHandler.END
    if await stale_ban_callback(ctx):
        return None
    chat = ctx.effective_chat
    user = ctx.effective_user
    key = (chat_id_of(chat), user.id) if chat is not None and user is not None else None
    if key is None:
        return ConversationHandler.END
    scope = flow_scope(ctx)
    session = proof_sessions.get(key)
    if session is None or session.flushing or not session.msgs:
        if not scope.get("ban_target_id"):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Ban done-proof zombie answer failed: %s", exc)
            return ConversationHandler.END
        try:
            locale = await locale_for_update(ctx)
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
        # * Await the cancelled timer before the execution path continues.
        # * Its finally clause may pop the registry entry; the cleanup below
        # * must still clear this session's scope even when that happened.
        await asyncio.gather(session.flush_task, return_exceptions=True)
    try:
        await q.answer()
    except Exception as exc:
        log.debug("Ban done-proof answer failed: %s", exc)
    if not session.meta.get("ban_target_id") or not session.meta.get("ban_admin_id"):
        log.warning("Done-proof flush aborted: meta missing target_id or admin_id")
        proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    tap_msg = ctx.effective_message
    if user is None or not isinstance(tap_msg, Message):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    if not await guards.recheck_executor_rank(tap_msg, user.id, min_role="developer"):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Ban done-proof recheck answer failed: %s", exc)
        proof_sessions.pop(key, None)
        _clear_ban_state(session.scope)
        return ConversationHandler.END
    try:
        await _execute_ban(ctx.bot, session.msgs, session.meta)
    except Exception:
        log.exception("Done-proof _execute_ban raised")
    finally:
        # * Always clear this conversation's payload. The cancelled timer may
        # * already have removed the registry entry, but the scope still
        # * belongs to the session that this handler just consumed. A
        # * successor session registered meanwhile keeps its own entry.
        if proof_sessions.get(key) is session:
            proof_sessions.pop(key, session)
        _clear_ban_state(session.scope)
    return ConversationHandler.END


async def on_proof_unexpected(ctx: Ctx) -> int:
    """Reject unexpected message types during proof collection."""
    if ctx.user_data is not None and not flow_scope(ctx).get("ban_target_id"):
        # * This handler is flattened into the shared group-0 list. Without an
        # * active ban it must not consume a message another module's flow owns.
        raise ContinuePropagation()
    if ctx.effective_message:
        await reply_rich(
            ctx.effective_message,
            t(
                "banning.state.proof_expected",
                await locale_for_update(ctx),
                plain=True,
            ),
            log_label="Ban proof-unexpected",
            parse_mode=None,
        )
    return WAITING_PROOF


async def on_cancel_proof(ctx: Ctx) -> int | None:
    """Acknowledge the cancel button and end the proof-collection conversation."""
    q = ctx.callback_query
    if q is None:
        return ConversationHandler.END
    scope = flow_scope(ctx)
    if await stale_ban_callback(ctx):
        return None
    # * Once flushing has started the ban is executing; cancelling mid-
    # * _execute_ban would cancel the in-flight fan-out (partial ban, DB
    # * written, no summary). Ignore the tap and let execution finish.
    for sess in proof_sessions.values():
        if sess.scope is scope and sess.flushing:
            await q.answer()
            return ConversationHandler.END
    await q.answer()
    await _cancel_proof_session(scope)
    await safe_edit_cb(
        q, t("banning.state.cancelled", await locale_for_update(ctx), plain=False)
    )
    await clear_markup_cb(q)
    return ConversationHandler.END


async def on_proof_timeout(ctx: Ctx) -> int:
    """Notify the user that the proof window expired."""
    scope = flow_scope(ctx)
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
    for sess in proof_sessions.values():
        if sess.scope is scope and sess.flushing:
            log.info("Ban proof timeout ignored: the ban is already executing.")
            return ConversationHandler.END
    await _cancel_proof_session(scope)
    if prompt_chat and prompt_msg_id:
        try:
            await ctx.bot.edit_message_reply_markup(
                chat_id=prompt_chat,
                message_id=prompt_msg_id,
                reply_markup=InlineKeyboardMarkup([]),
            )
        except Exception as exc:
            log.debug("Ban proof-timeout markup clear failed: %s", exc)
    if not had_state:
        return ConversationHandler.END
    if ctx.effective_message:
        await reply_rich(
            ctx.effective_message,
            t(
                "banning.state.timeout",
                await locale_for_update(ctx),
                plain=True,
            ),
            log_label="Ban proof-timeout",
            parse_mode=None,
        )
    return ConversationHandler.END


# ─────────────────── ConversationHandler factory ────────────────── #


def ban_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    extra_states: dict[Any, list[Any]] | None = None,
) -> ConversationHandler:
    """Return the ban ConversationHandler with the given entry-point function."""
    states: dict[Any, list[Any]] = {
        WAITING_PROOF: [
            CallbackQueryHandler(on_cancel_proof, pattern=rf"^{proof.action}_cancel$"),
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
            CallbackQueryHandler(on_cancel_proof, pattern=rf"^{proof.action}_cancel$"),
        ],
    }
    if extra_states:
        states.update(extra_states)
    return ConversationHandler(
        entry_points=[MessageHandler(entry_filter, entry_fn)],
        states=states,
        fallbacks=[
            # * Only this conversation's own re-entry command may end proof collection.
            # * Swallowing other commands loses the moderator's intent: /tcunban
            # * sent here would cancel the ban and never unban anyone.
            MessageHandler(
                ALL_PREFIXES_CMD_FILTER
                & ~build_conversation_escape_filter("tcban", "tcb"),
                on_proof_timeout,
            ),
            CallbackQueryHandler(on_cancel_proof, pattern=r"^rules_step:cancel$"),
            CallbackQueryHandler(on_cancel_proof, pattern=r"^ban_cancel$"),
        ],
        per_chat=True,
        per_user=True,
        per_message=False,
    )
