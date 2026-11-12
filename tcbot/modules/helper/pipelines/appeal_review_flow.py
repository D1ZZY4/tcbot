# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal review: staff approve/reject decisions on the shared review card."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from telegram import Bot, CallbackQuery, Update, User
from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import messages
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.messages import cb_error_edit, send_log
from tcbot.modules.helper.pipelines.demote_flow import demote_before_unban
from tcbot.utils.dispatch import (
    fan_out,
    summarize_fanout,
    throw_if_cancelled,
)
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
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
    bot: Bot, lc: int, lt: int | None, msg_id: int | None, text: str
) -> None:
    """Edit the existing appeal log message, or post a new one as fallback."""
    if msg_id:
        try:
            await bot.edit_message_text(
                text, chat_id=lc, message_id=msg_id, parse_mode="MarkdownV2"
            )
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
    """Approve path: deactivate, unban fan-out, and notifications."""

    community_name: str

    async def _approve_appeal(
        self,
        bot: Bot,
        q: CallbackQuery,
        ban: BanDoc,
        ban_id: str,
        target_id: int,
        admin: User,
        lc: int,
        lt: int | None,
        update: Update,
        approver_role: str | None,
    ) -> bool:
        """Approve the appeal; return True when the ban was actually lifted.

        Every early return means no decision was reached, so the caller
        hands the review slot back instead of leaving a dead card.
        """
        locale = await locale_for_update(update)
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
        if target_role and db.users_roles.role_rank(
            approver_role
        ) <= db.users_roles.role_rank(target_role):
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
                admin.first_name,
            )
            if not gate.may_proceed:
                await _answer_review(q, locale, "appeals.review.demote_blocked")
                return False
        deactivate_result = await db.bans_db.deactivate_all_active_bans(target_id)
        if isinstance(deactivate_result, asyncio.CancelledError):
            raise deactivate_result
        if isinstance(deactivate_result, BaseException):
            log.error(
                "approve_appeal: deactivate failed for user=%d: %s",
                target_id,
                deactivate_result,
            )
            await _answer_review(q, locale, "appeals.review.db_retry")
            return False
        try:
            await db.bans_db.clear_review(ban_id)
        except Exception:
            log.exception("approve_appeal: clear_review failed for ban %s", ban_id)
        groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
        unban_results = await fan_out(
            [
                bot.unban_chat_member(
                    grp.get("chat_id", 0), target_id, only_if_banned=True
                )
                for grp in groups
            ]
        )
        summarize_fanout(
            groups,
            unban_results,
            action="Appeal-approve",
            target_id=target_id,
        )
        appeal_link = ban.get("appeal_link") or ""
        appeal_submitted_at = ban.get("appeal_submitted_at")
        target_locale, staff_locale = await asyncio.gather(
            locale_for_user(target_id),
            locale_for_update(update),
        )
        dm_r, card_r, log_r, unban_log_r = await asyncio.gather(
            bot.send_message(
                target_id,
                t(
                    "appeals.decision.approve_dm",
                    target_locale,
                    ban_id=Safe(code(ban_id)),
                    community=self.community_name,
                ),
                parse_mode="MarkdownV2",
            ),
            q.edit_message_text(
                t(
                    "appeals.decision.approve_card",
                    staff_locale,
                    admin=Safe(user_ref(admin.id, admin.first_name)),
                ),
                parse_mode="MarkdownV2",
                reply_markup=None,
            ),
            _update_or_send_log(
                bot,
                lc,
                lt,
                int(ban.get("appeal_log_msg_id") or 0) or None,
                messages.appeal_approved_edit(
                    target_id,
                    target_fname,
                    admin.id,
                    admin.first_name,
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
                    admin.first_name,
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
        if isinstance(card_r, BaseException):
            log.warning(
                "approve_appeal review-card edit failed for ban %s: %s", ban_id, card_r
            )
        if isinstance(log_r, BaseException):
            log.warning(
                "approve_appeal appeal-log update failed for ban %s: %s", ban_id, log_r
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
        bot: Bot,
        q: CallbackQuery,
        ban: BanDoc,
        ban_id: str,
        target_id: int,
        admin: User,
        lc: int,
        lt: int | None,
        update: Update,
    ) -> bool:
        """Reject the appeal; return True when the rejection was recorded.

        The rejection marker is the decision, so a failure to write it
        means no decision was reached and the caller hands the review
        slot back.
        """
        set_r, name_r = await asyncio.gather(
            db.bans_db.set_rejected_by(ban_id, admin.id, admin.first_name),
            db.users_cache.get_first_name(target_id, str(target_id)),
            return_exceptions=True,
        )
        throw_if_cancelled((set_r, name_r))
        staff_locale = await locale_for_update(update)
        if isinstance(set_r, BaseException):
            log.exception("reject_appeal set_rejected_by failed for ban %s", ban_id)
            await _answer_review(q, staff_locale, "appeals.review.db_retry")
            return False
        target_fname: str = (
            name_r if isinstance(name_r, str) and name_r else str(target_id)
        )
        if isinstance(name_r, BaseException) and not isinstance(
            name_r, asyncio.CancelledError
        ):
            log.debug("reject_appeal name fetch failed: %s", name_r)
        target_locale = await locale_for_user(target_id)
        await cb_error_edit(
            q,
            t(
                "appeals.decision.reject_card",
                staff_locale,
                admin=Safe(user_ref(admin.id, admin.first_name)),
            ),
            log_label="reject_appeal review-card",
            log_level="warning",
        )
        results = await asyncio.gather(
            bot.send_message(
                target_id,
                t(
                    "appeals.decision.reject_dm",
                    target_locale,
                    ban_id=Safe(code(ban_id)),
                ),
                parse_mode="MarkdownV2",
            ),
            db.bans_db.clear_review(ban_id),
            return_exceptions=True,
        )
        throw_if_cancelled(results)
        if isinstance(results[0], BaseException):
            log.warning("reject_appeal DM to %d failed: %s", target_id, results[0])
        if isinstance(results[1], BaseException):
            log.error(
                "reject_appeal clear_review failed for ban %s: user %d may "
                "re-appeal within the 72-hour window",
                ban_id,
                target_id,
            )
        await _update_or_send_log(
            bot,
            lc,
            lt,
            int(ban.get("appeal_log_msg_id") or 0) or None,
            messages.appeal_rejected_edit(
                target_id,
                target_fname,
                admin.id,
                admin.first_name,
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

    async def on_decision(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Approve / Reject callback for the staff review card."""
        q = update.callback_query
        if q is None:
            return
        admin = update.effective_user
        if admin is None:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Appeal decision answer failed with no user: %s", exc)
            return
        locale = await locale_for_update(update)
        data = q.data
        if not data or not data.startswith(("appeal_approve_", "appeal_reject_")):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Appeal decision answer failed for unknown data: %s", exc)
            return
        if data.startswith("appeal_approve_"):
            action = "approve"
            ban_id = data[len("appeal_approve_") :]
        else:
            action = "reject"
            ban_id = data[len("appeal_reject_") :]
        role_result, ban_result, answer_r = await asyncio.gather(
            db.users_roles.get_effective_role(admin.id, fresh=True),
            db.bans_db.get_ban(ban_id),
            q.answer(),
            return_exceptions=True,
        )
        throw_if_cancelled((role_result, ban_result, answer_r))
        if isinstance(answer_r, BaseException):
            log.debug("Appeal decision answer failed: %s", answer_r)
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
        if role_result not in db.users_roles.FOUNDER_ADMIN_ROLES:
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
            await cb_error_edit(
                q,
                t("appeals.review.ban_not_found", locale, plain=True),
                log_label="Appeal ban-not-found (empty)",
                parse_mode=None,
            )
            return
        ban: BanDoc = ban_result
        if not ban.get("is_active"):
            if ban.get("review_message_id"):
                try:
                    await db.bans_db.clear_review(ban_id)
                except Exception:
                    log.exception(
                        "Appeal stale-card clear_review failed for ban %s", ban_id
                    )
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
        review_ts = ban.get("review_timestamp")
        if review_ts and reviewer_locked_out(
            review_ts, ban.get("admin_user_id") or 0, admin.id
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
        target_id = ban.get("banned_user_id", 0)
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
        # * checks above, but only one wins this update. The loser aborts
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
        lc, lt = cfg.logs
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
                    ctx.bot,
                    q,
                    ban,
                    ban_id,
                    target_id,
                    admin,
                    lc,
                    lt,
                    update,
                    approver_role=role_result,
                )
            else:
                decided = await self._reject_appeal(
                    ctx.bot, q, ban, ban_id, target_id, admin, lc, lt, update
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
