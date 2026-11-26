# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban record write, enforcement scope, and the ban executor."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pyrogram import Client
from pyrogram.types import Message

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import buttons, guards, messages
from tcbot.modules.helper.context import bot_identity
from tcbot.modules.helper.locale import locale_for_user
from tcbot.modules.helper.messages import (
    appeal_deep_link,
    message_link,
    replies,
    safe_edit_message,
)
from tcbot.modules.helper.pipelines import moderation_enforcement
from tcbot.modules.helper.pipelines.demote_actions import demote_before_enforcement
from tcbot.modules.helper.pipelines.errors.exceptions import is_chat_admin_required
from tcbot.modules.helper.pipelines.proof_post import upload_proof_media
from tcbot.modules.helper.rich.edit import clear_markup
from tcbot.utils.dispatch import (
    fan_out,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.i18n import Safe, code, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import to_utc, utc_now

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from tcbot.database.documents import BanDoc, EvidenceItemDoc, GroupDoc

log = get_logger(__name__)

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


async def execute_ban(bot: Client, msgs: list[Message], meta: dict[str, Any]) -> None:
    """Enforce a federation ban from a collected proof batch and flow scope."""
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
    finally:
        # * Every return and failure path owns this prefetch: leaving it
        # * alive after a refusal would hold a pool slot and can surface
        # * an unretrieved exception later.
        if not _groups_task.done():
            _groups_task.cancel()
        await asyncio.gather(_groups_task, return_exceptions=True)
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
            await moderation_enforcement.deliver_queued_run(bot, enforcement_run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Ban delivery failed for run %s; it stays queued", enforcement_run_id
            )
        try:
            report = await db.enforcement_ledger.run_report(enforcement_run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ban run report failed for run %s", enforcement_run_id)
            report = None
        failed_targets = db.enforcement_ledger.failed_report_targets(report)
        delivery = db.enforcement_ledger.delivery_outcome(report, len(groups))
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
            # * The durable path builds its exceptions from stored target
            # * fields. Without one attached, the error channel classifies the
            # * report as [?] Unknown and the operator cannot see why the
            # * groups failed. The legacy fan-out path below already passes
            # * its first transient error through summarize_fanout().
            log.error(
                "Ban enforcement for user=%d left %d/%d group(s) failed (run %s)",
                target_id,
                failed,
                total,
                enforcement_run_id,
                exc_info=transient[0][1] if transient else None,
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
    # * A moderation outcome is a rich card, not a bare sentence. The reason
    # * goes through the renderer so moderator free text stays escaped; the
    # * applied line is already rendered and is passed through as a cell.
    summary = replies.outcome_card(
        t("banning.summary.title", locale, plain=True),
        [
            (
                t("checking.ban_info.table.user", locale, plain=True),
                buttons.mention_button(target_id, target_fname),
            ),
            (
                t("checking.ban_info.table.reason", locale, plain=True),
                t("common.outcome.reason", locale, reason=reason),
            ),
            (
                t("checking.ban_info.table.ban_id", locale, plain=True),
                Safe(code(ban_id)),
            ),
            (t("common.outcome.result", locale, plain=True), Safe(applied_line)),
        ],
        locale,
    )
    if prompt_msg_id and prompt_chat_id:
        edit_result, upsert_result, pm_result, markup_result = await asyncio.gather(
            safe_edit_message(bot, prompt_chat_id, prompt_msg_id, summary),
            db.users_cache.upsert_user(target_id, None, target_fname),
            messages.send_text(bot, target_id, _pm_text, reply_markup=_pm_btn),
            clear_markup(bot, prompt_chat_id, prompt_msg_id),
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
    if is_chat_admin_required(pm_result):
        log.info(
            "Cannot DM banned user %d: user has not started the bot or has blocked it",
            target_id,
        )
    elif isinstance(pm_result, BaseException):
        log.warning("Failed to send ban PM to user %d: %s", target_id, pm_result)


__all__ = ["_enforcement_scope", "_execute_ban_record", "execute_ban"]
