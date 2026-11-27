# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal review: staff approve/reject decisions on the shared review card."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pyrogram import Client
from pyrogram.types import CallbackQuery, User

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import guards, messages
from tcbot.modules.helper.context import Ctx, display_name
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.messages import (
    answer_ack,
    cb_error_edit,
    safe_edit_cb,
    safe_edit_message,
    send_log,
    send_text,
)
from tcbot.modules.helper.pipelines import moderation_enforcement
from tcbot.modules.helper.pipelines.demote_actions import demote_before_unban
from tcbot.modules.helper.rich.edit_msg import callback_text_of
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, code, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import to_utc, utc_now

if TYPE_CHECKING:
    from tcbot.database.documents import BanDoc

log = get_logger(__name__)

# ───────────────────────── Review helpers ───────────────────────── #


LOCK_HOURS: int = 12
_LOCK_WINDOW = timedelta(hours=LOCK_HOURS)

# * Ceiling for handing a consumed review slot back. The restore runs on
# * the failure path and while the handler is being cancelled, so it
# * must not hold the shutdown drain for a long write.
_RESTORE_TIMEOUT_S: float = 5.0


def reviewer_locked_out(
    review_timestamp: datetime | None,
    ban_admin_id: int | None,
    reviewer_id: int,
) -> bool:
    """Check whether reviewer_id is blocked within the lock window."""
    if review_timestamp is None or not ban_admin_id:
        return False
    if reviewer_id == ban_admin_id:
        return False
    elapsed = utc_now() - to_utc(review_timestamp)
    return elapsed < _LOCK_WINDOW


async def _update_or_send_log(
    bot: Client, lc: int, msg_id: int | None, text: str
) -> None:
    """Edit the existing appeal log message, or post a new one as fallback."""
    if msg_id:
        try:
            await safe_edit_message(bot, lc, msg_id, text)
            return
        except Exception as exc:
            log.warning("Could not edit appeal submitted log: %s", exc)
    try:
        await send_log(bot, text)
    except Exception as exc:
        log.debug("Could not send appeal submitted log: %s", exc)


async def _answer_review(
    q: CallbackQuery, locale: str | None, key: str, *, role: str | None = None
) -> None:
    """Answer the review card with a localized plain-text alert; never raises.

    Callback alerts are plain text (Telegram does not parse MarkdownV2 in
    an answer), so the message is rendered with ``plain=True``. ``role`` is
    the optional placeholder of the refusal copy; templates that do not use
    it ignore the value.
    """
    try:
        await q.answer(
            t(key, locale, role=role or "", plain=True),
            show_alert=True,
        )
    except Exception as exc:
        log.debug("Appeal review answer failed for %s: %s", key, exc)


async def _decision_role_still_valid(
    q: CallbackQuery,
    locale: str | None,
    admin_id: int,
    target_role: str | None,
    *,
    action: str,
) -> bool:
    """Re-read the reviewer's rank immediately before an irreversible decision.

    The entry checks read the role before the ban fetch, the claim, and the
    target lookups. A reviewer demoted across those awaits would otherwise
    still lift a ban or reject an appeal with a stale rank.
    """
    try:
        role = await db.users_roles.get_effective_role(admin_id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning(
            "%s appeal: reviewer role re-read failed for %d: %s", action, admin_id, exc
        )
        await _answer_review(q, locale, "appeals.review.db_retry")
        return False
    if role not in db.users_roles.OWNER_ADMIN_ROLES:
        log.warning("%s appeal refused: reviewer %d was demoted", action, admin_id)
        await _answer_review(q, locale, "appeals.review.not_authorized")
        return False
    if not guards.outranks(role, target_role):
        log.warning(
            "%s appeal refused: reviewer %d (role=%s) does not outrank target (role=%s)",
            action,
            admin_id,
            role,
            target_role,
        )
        await _answer_review(
            q,
            locale,
            "common.refuse.outranked",
            role=db.users_roles.role_label(target_role),
        )
        return False
    return True


async def _restore_review_slot(
    ban_id: str, review_msg_id: int, review_timestamp: datetime | None
) -> None:
    """Hand a consumed review slot back after a decision was not reached.

    The decision claim consumes the slot so only one reviewer acts on it.
    A claim that ends without a decision (a rank refusal, a database
    outage) must give the slot back, or the review card dies with the
    appeal undecided and the banned user can appeal again at once.

    The restore never masks the failure that caused it, so its own errors
    are logged and swallowed. It is bounded, because it also runs while
    the handler is being cancelled and a long write would hold the
    shutdown drain.
    """
    try:
        restored = await asyncio.wait_for(
            db.bans_db.restore_review(ban_id, review_msg_id, review_timestamp),
            timeout=_RESTORE_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.warning("Review slot restore for ban %s timed out", ban_id)
        return
    except Exception:
        log.exception("restore_review failed for ban %s", ban_id)
        return
    if restored:
        log.info("Review slot for ban %s restored; no decision was taken.", ban_id)


# ───────────────────────────── Approve ──────────────────────────── #


class ApproveMixin:
    """Approve path: atomic decision, durable unban run, and notifications."""

    community_name: str

    async def _approve_appeal(
        self,
        ctx: Ctx,
        bot: Client,
        q: CallbackQuery,
        ban: BanDoc,
        ban_id: str,
        target_id: int,
        admin: User,
        lc: int,
        approver_role: str | None,
    ) -> bool:
        """Approve the appeal; return True when the ban was actually lifted.

        Every early return means no decision was reached, so the caller
        hands the review slot back instead of leaving a dead card.
        """
        locale = await locale_for_update(ctx)
        # * The target name is resolved alongside the role so the demote audit
        # * log records the real name instead of the raw ID.
        role_result, name_result = await asyncio.gather(
            db.users_roles.get_effective_role(target_id, fresh=True),
            db.users_cache.get_first_name(target_id, str(target_id)),
            return_exceptions=True,
        )
        throw_if_cancelled((role_result, name_result))
        target_fname = (
            str(target_id) if isinstance(name_result, BaseException) else name_result
        )
        if isinstance(role_result, BaseException):
            log.warning(
                "approve_appeal role lookup failed for user=%d: %s",
                target_id,
                role_result,
            )
            await _answer_review(q, locale, "appeals.review.db_retry")
            return False
        target_role = role_result
        # ! CRITICAL: The approver must outrank the target. Approving
        # ! strips the target's federation role (the ban lift requires it)
        # ! and lifts the ban everywhere, which is the same irreversible
        # ! action as /tcunban. Without this gate an Admin could strip a
        # ! peer Admin's rank and lift their ban, an outcome the sibling
        # ! command path refuses for equal rank.
        if not guards.outranks(approver_role, target_role):
            log.warning(
                "approve_appeal refused: approver %d (role=%s) does not outrank "
                "target %d (role=%s)",
                admin.id,
                approver_role,
                target_id,
                target_role,
            )
            await _answer_review(
                q,
                locale,
                "common.refuse.outranked",
                role=db.users_roles.role_label(target_role),
            )
            return False
        try:
            groups = await db.groups_db.active_groups()
        except Exception:
            log.exception("approve_appeal: groups fetch failed for user=%d", target_id)
            await _answer_review(q, locale, "common.err.groups_load_failed")
            return False
        groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
        chat_ids = [
            int(grp.get("chat_id", 0))
            for grp in groups
            if int(grp.get("chat_id", 0) or 0)
        ]
        # ! CRITICAL: re-read the reviewer's rank before any irreversible
        # ! write. The demote below strips the target's role and cannot be
        # ! undone here, so a reviewer demoted during the claim or the group
        # ! read must be refused before it runs.
        if not await _decision_role_still_valid(
            q, locale, admin.id, target_role, action="approve"
        ):
            return False
        if target_role in db.users_roles.STAFF_ROLES:
            # * Fail closed: the shared gate blocks the approval when the
            # * demote raised, or when it cleared no row while the role still
            # * resolves. A staff holder must never keep rank after the ban
            # * lifts, and the ban record stays active when the gate blocks.
            gate = await demote_before_unban(
                bot,
                target_id,
                target_fname,
                target_role,
                admin.id,
                display_name(admin),
                trigger="appeal",
            )
            if not gate.may_proceed:
                await _answer_review(q, locale, "appeals.review.demote_blocked")
                return False
        # * Decision and delivery intent land together: the appeal is
        # * accepted, the ban is revoked, the review slot is released, and
        # * the unban run owns every group. A split here used to leave an
        # * accepted appeal beside an active ban, or a revoked ban beside a
        # * pending appeal.
        try:
            accepted, run_id = await db.bans_db.approve_appeal_and_queue_unban(
                ban_id,
                admin.id,
                display_name(admin),
                admin.id,
                chat_ids,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("approve_appeal: atomic decision failed for ban %s", ban_id)
            await _answer_review(q, locale, "appeals.review.db_retry")
            return False
        if not accepted or run_id is None:
            log.warning("approve_appeal: no pending appeal found for ban %s", ban_id)
            await _answer_review(q, locale, "appeals.review.already_resolved")
            return False
        # * The decision is committed; ack before the bookkeeping and the
        # * notification fan-out, none of which answers the query again.
        await answer_ack(q)
        try:
            await moderation_enforcement.deliver_queued_run(bot, run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "approve_appeal: unban delivery failed for run %s; it stays queued",
                run_id,
            )
        try:
            report = await db.enforcement_ledger.run_report(run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("approve_appeal: run report failed for run %s", run_id)
            report = None
        failed = db.enforcement_ledger.report_count(report, "failed_count")
        if failed:
            # * Reuse the single owner of partial-delivery reporting so the
            # * stored Telegram refusal becomes the attached exception. Logging
            # * the count alone produced an "Unknown / no exception" report.
            failed_targets = db.enforcement_ledger.failed_report_targets(report)
            detail = next(
                (
                    str(target["last_error_detail"])
                    for target in failed_targets
                    if target.get("last_error_detail")
                ),
                None,
            )
            moderation_enforcement.report_partial_failure(
                action="Appeal approve",
                target_id=target_id,
                failed=failed,
                total=len(chat_ids),
                run_id=run_id,
                error_detail=detail,
            )
        appeal_link = ban.get("appeal_link") or ""
        appeal_submitted_at = ban.get("appeal_submitted_at")
        # * The staff locale is the one resolved at the top of the handler;
        # * only the target's own locale needs a second lookup.
        target_locale = await locale_for_user(target_id)
        dm_r, card_r, log_r, unban_log_r = await asyncio.gather(
            send_text(
                bot,
                target_id,
                t(
                    "appeals.decision.approve_dm",
                    target_locale,
                    ban_id=Safe(code(ban_id)),
                    community=self.community_name,
                ),
            ),
            safe_edit_cb(
                q,
                t(
                    "appeals.decision.approve_card",
                    locale,
                    admin=Safe(user_ref(admin.id, display_name(admin))),
                ),
                # * An empty markup is sent explicitly: omitting it leaves the
                # * old Approve/Reject buttons on a card that is already decided.
                clear_markup=True,
            ),
            _update_or_send_log(
                bot,
                lc,
                int(ban.get("appeal_log_msg_id") or 0) or None,
                messages.appeal_approved_edit(
                    target_id,
                    target_fname,
                    admin.id,
                    display_name(admin),
                    ban_id,
                    str(appeal_link),
                    appeal_submitted_at,
                ),
            ),
            send_log(
                bot,
                messages.appeal_unban_log(
                    target_id,
                    target_fname,
                    admin.id,
                    display_name(admin),
                    ban_id,
                ),
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((dm_r, card_r, log_r, unban_log_r))
        if isinstance(dm_r, BaseException):
            log.warning(
                "approve_appeal DM to %d failed for ban %s: %s", target_id, ban_id, dm_r
            )
        if isinstance(card_r, BaseException) or card_r is False:
            log.warning(
                "approve_appeal review-card edit failed for ban %s: %s", ban_id, card_r
            )
            action_id = int(ban.get("id") or 0)
            review_id = int(ban.get("review_message_id") or 0)
            if action_id and review_id and cfg.main_group:
                await db.notifications_db.enqueue_review_card_edit(
                    action_id, cfg.main_group, review_id
                )
        if isinstance(log_r, BaseException):
            log.warning(
                "approve_appeal appeal-log ctx failed for ban %s: %s", ban_id, log_r
            )
        if isinstance(unban_log_r, BaseException):
            log.error(
                "approve_appeal unban log send failed for user %d ban %s: %s",
                target_id,
                ban_id,
                unban_log_r,
            )
        return True


# ───────────────────────────── Reject ───────────────────────────── #


class RejectMixin:
    """Reject path: cooldown write, card edit, DM, and marker clear."""

    async def _reject_appeal(
        self,
        ctx: Ctx,
        bot: Client,
        q: CallbackQuery,
        ban: BanDoc,
        ban_id: str,
        target_id: int,
        admin: User,
        lc: int,
        approver_role: str | None,
    ) -> bool:
        """Reject the appeal; return True when the rejection was recorded.

        The rejection marker is the decision, so a failure to write it
        means no decision was reached and the caller hands the review
        slot back. The target is read fresh and checked against the
        reviewer first, so rejecting follows the same executor-versus-target
        rule as approving and /tcunban.
        """
        role_r, name_r = await asyncio.gather(
            db.users_roles.get_effective_role(target_id, fresh=True),
            db.users_cache.get_first_name(target_id, str(target_id)),
            return_exceptions=True,
        )
        throw_if_cancelled((role_r, name_r))
        staff_locale = await locale_for_update(ctx)
        if isinstance(role_r, BaseException):
            log.warning(
                "reject_appeal role lookup failed for user=%d: %s",
                target_id,
                role_r,
            )
            await _answer_review(q, staff_locale, "appeals.review.db_retry")
            return False
        if not guards.outranks(approver_role, role_r):
            log.warning(
                "reject_appeal refused: approver %d (role=%s) does not outrank "
                "target %d (role=%s)",
                admin.id,
                approver_role,
                target_id,
                role_r,
            )
            await _answer_review(
                q,
                staff_locale,
                "common.refuse.outranked",
                role=db.users_roles.role_label(role_r),
            )
            return False
        if not await _decision_role_still_valid(
            q, staff_locale, admin.id, role_r, action="reject"
        ):
            return False
        try:
            rejected = await db.bans_db.reject_appeal(
                ban_id, admin.id, display_name(admin)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reject_appeal failed for ban %s", ban_id)
            await _answer_review(q, staff_locale, "appeals.review.db_retry")
            return False
        if not rejected:
            log.warning("reject_appeal: no pending appeal found for ban %s", ban_id)
            await _answer_review(q, staff_locale, "appeals.review.already_resolved")
            return False
        # * The rejection and the slot release are recorded; ack before the
        # * card edit and DMs.
        await answer_ack(q)
        target_fname: str = (
            name_r if isinstance(name_r, str) and name_r else str(target_id)
        )
        if isinstance(name_r, BaseException) and not isinstance(
            name_r, asyncio.CancelledError
        ):
            log.debug("reject_appeal name fetch failed: %s", name_r)
        target_locale = await locale_for_user(target_id)
        card_ok = True
        try:
            card_ok = await safe_edit_cb(
                q,
                t(
                    "appeals.decision.reject_card",
                    staff_locale,
                    admin=Safe(user_ref(admin.id, display_name(admin))),
                ),
                clear_markup=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "reject_appeal review-card edit failed for ban %s: %s", ban_id, exc
            )
            # * The decision is already committed, so an edit failure is not a
            # * reason to abort: the durable outbox must close the live card.
            card_ok = False
        if not card_ok:
            action_id = int(ban.get("id") or 0)
            review_id = int(ban.get("review_message_id") or 0)
            if action_id and review_id and cfg.main_group:
                await db.notifications_db.enqueue_review_card_edit(
                    action_id, cfg.main_group, review_id
                )
        try:
            await send_text(
                bot,
                target_id,
                t(
                    "appeals.decision.reject_dm",
                    target_locale,
                    ban_id=Safe(code(ban_id)),
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("reject_appeal DM to %d failed: %s", target_id, exc)
        await _update_or_send_log(
            bot,
            lc,
            int(ban.get("appeal_log_msg_id") or 0) or None,
            messages.appeal_rejected_edit(
                target_id,
                target_fname,
                admin.id,
                display_name(admin),
                ban_id,
                str(ban.get("appeal_link") or ""),
                ban.get("appeal_submitted_at"),
            ),
        )
        return True


# ──────────────────────── Decision routing ──────────────────────── #


class AppealVerdictsMixin(ApproveMixin, RejectMixin):
    """Staff-side appeal verdict executors."""


class AppealReviewMixin(AppealVerdictsMixin):
    """Staff-side appeal review: decision routing plus approve/reject executors."""

    community_name: str

    async def on_decision(self, ctx: Ctx) -> None:
        """Approve / Reject callback for the staff review card."""
        q = ctx.callback_query
        if q is None:
            return
        admin = ctx.effective_user
        if admin is None:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Appeal decision answer failed with no user: %s", exc)
            return
        locale = await locale_for_update(ctx)
        data = callback_text_of(q)
        if not data or not data.startswith(("appeal_approve_", "appeal_reject_")):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Appeal decision answer failed for unknown data: %s", exc)
            return
        if data.startswith("appeal_approve_"):
            action = "approve"
            payload = data[len("appeal_approve_") :]
        else:
            action = "reject"
            payload = data[len("appeal_reject_") :]
        # * The trailing segment names the review card the button belongs to.
        # * A card left over from an earlier appeal carries its old id, so the
        # * live review id check below refuses it. A card posted before this
        # * payload shape existed carries no id; its own message id is the
        # * card it belongs to, so a live legacy card keeps working while a
        # * replaced one is still refused.
        ban_id, separator, raw_review_id = payload.rpartition("_")
        if separator and ban_id and raw_review_id.isdigit():
            tapped_review_id = int(raw_review_id)
        else:
            ban_id = payload
            message = q.message
            # * Kurigram exposes the message id as ``id``; ``message_id`` is
            # * the DB-column and test-double spelling. Accept both so a live
            # * legacy card still matches its stored review id.
            raw_id = getattr(message, "id", None) or getattr(message, "message_id", 0)
            tapped_review_id = int(raw_id or 0) if message else 0
        if not ban_id:
            log.warning("Appeal decision payload malformed: %r", data)
            try:
                await q.answer(
                    t("appeals.review.stale_card", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal malformed-payload answer failed: %s", exc)
            return
        role_result, ban_result = await asyncio.gather(
            db.users_roles.get_effective_role(admin.id, fresh=True),
            db.bans_db.get_ban(ban_id),
            return_exceptions=True,
        )
        throw_if_cancelled((role_result, ban_result))
        # * The query is answered per branch, never up front: Telegram
        # * accepts one answer, so an early ack would swallow every alert
        # * below and leave a refused tapper with no feedback at all.
        if isinstance(role_result, BaseException):
            log.warning(
                "Appeal review role lookup failed for %d: %s", admin.id, role_result
            )
            try:
                await q.answer(
                    t("appeals.review.role_lookup", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal role-lookup answer failed: %s", exc)
            return
        if role_result not in db.users_roles.OWNER_ADMIN_ROLES:
            try:
                await q.answer(
                    t("appeals.review.not_authorized", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal not-authorized answer failed: %s", exc)
            return
        if isinstance(ban_result, BaseException):
            log.error("get_ban failed in appeal review for %s: %s", ban_id, ban_result)
            try:
                await q.answer(
                    t("appeals.review.db_retry", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal ban-retry answer failed: %s", exc)
            return
        if not ban_result:
            await answer_ack(q)
            await cb_error_edit(
                q,
                t("appeals.review.ban_not_found", locale, plain=True),
                log_label="Appeal ban-not-found (empty)",
                parse_mode=None,
            )
            return
        ban: BanDoc = ban_result
        if not ban.get("is_active"):
            review_id = int(ban.get("review_message_id") or 0)
            if review_id:
                try:
                    # * A settled decision also settles the appeal behind the
                    # * card: leaving it pending would keep a question alive
                    # * that no reviewer can decide.
                    await db.bans_db.release_stale_review(ban_id, review_id)
                except Exception:
                    log.exception("Appeal stale-card release failed for ban %s", ban_id)
                await answer_ack(q)
                await cb_error_edit(
                    q,
                    t("appeals.review.already_resolved", locale, plain=True),
                    log_label="Appeal already-resolved",
                    parse_mode=None,
                )
            else:
                try:
                    await q.answer(
                        t("appeals.review.already_resolved", locale, plain=True),
                        show_alert=True,
                    )
                except Exception as exc:
                    log.debug("Appeal already-resolved answer failed: %s", exc)
            return
        if ban.get("rejected_at") is not None or not ban.get("review_message_id"):
            try:
                await q.answer(
                    t("appeals.review.already_resolved", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal already-resolved answer failed: %s", exc)
            return
        expected_review_id = int(ban.get("review_message_id") or 0)
        if tapped_review_id != expected_review_id:
            # ! CRITICAL: a stale card must never decide a newer appeal. The
            # ! payload is bound to the card it was rendered on, and the live
            # ! review id lives on the ban record.
            log.info(
                "Appeal review refused for ban %s: card %d is not the live review %d",
                ban_id,
                tapped_review_id,
                expected_review_id,
            )
            await answer_ack(q)
            await cb_error_edit(
                q,
                t("appeals.review.stale_card", locale, plain=True),
                log_label="Appeal stale-card",
                parse_mode=None,
            )
            return
        review_ts = ban.get("review_timestamp")
        if review_ts and reviewer_locked_out(
            review_ts, ban.get("actor_user_id") or 0, admin.id
        ):
            try:
                await q.answer(
                    t(
                        "appeals.review.review_locked",
                        locale,
                        hours=LOCK_HOURS,
                        plain=True,
                    ),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal review-locked answer failed: %s", exc)
            return
        target_id = ban.get("target_user_id", 0)
        # ! CRITICAL: A banned user who gains staff must never judge their own appeal.
        if admin.id == target_id:
            try:
                await q.answer(
                    t("appeals.review.not_authorized", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal self-review answer failed: %s", exc)
            return
        # * Atomic decision claim: two concurrent taps both pass the read
        # * checks above, but only one wins this ctx. The loser aborts
        # * instead of double-unbanning or approve+reject racing.
        review_msg_id = int(ban.get("review_message_id") or 0)
        try:
            claimed = await db.bans_db.claim_appeal_decision(ban_id, review_msg_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("claim_appeal_decision failed for ban %s", ban_id)
            try:
                await q.answer(
                    t("appeals.review.db_retry", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal claim-fail answer failed: %s", exc)
            return
        if not claimed:
            try:
                await q.answer(
                    t("appeals.review.already_resolved", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal claim-loser answer failed: %s", exc)
            return
        lc = cfg.logs[0]
        # * The claim consumed the review slot. A path that ends without a
        # * decision must hand the slot back, or the card dies with the
        # * appeal undecided and the banned user can appeal again at once.
        # *
        # * The restore must never replace the failure that made it
        # * necessary, so it runs outside a finally block and swallows a
        # * cancellation of its own.
        decided = False
        try:
            if action == "approve":
                decided = await self._approve_appeal(
                    ctx,
                    ctx.bot,
                    q,
                    ban,
                    ban_id,
                    target_id,
                    admin,
                    lc,
                    approver_role=role_result,
                )
            else:
                decided = await self._reject_appeal(
                    ctx,
                    ctx.bot,
                    q,
                    ban,
                    ban_id,
                    target_id,
                    admin,
                    lc,
                    approver_role=role_result,
                )
        except asyncio.CancelledError:
            # * A cancelled decision reaches no verdict either, so the
            # * slot goes back before the cancellation continues.
            with contextlib.suppress(asyncio.CancelledError):
                await _restore_review_slot(ban_id, review_msg_id, review_ts)
            raise
        except Exception:
            log.exception("Appeal decision failed for ban %s", ban_id)
            with contextlib.suppress(asyncio.CancelledError):
                await _restore_review_slot(ban_id, review_msg_id, review_ts)
            raise
        if not decided:
            await _restore_review_slot(ban_id, review_msg_id, review_ts)
