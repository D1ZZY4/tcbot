# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal review: staff approve/reject decisions on the shared review card."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Bot, CallbackQuery, Update, User
from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import BanDoc
from tcbot.modules.helper import parse_logmsg, replies
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.utils.dispatch import count_transient_errors, fan_out, throw_if_cancelled
from tcbot.utils.formatter import code, mention
from tcbot.utils.i18n import Safe, t
from tcbot.utils.time_and_date import to_utc, utc_now

log = logging.getLogger(__name__)

LOCK_HOURS: int = 12
_LOCK_WINDOW = timedelta(hours=LOCK_HOURS)

# * Appeal review prose lives in appeals.toml [review]/[decision];
# * only the lock-window tunable stays in code.


def reviewer_locked_out(
    review_timestamp: datetime | None,
    ban_admin_id: int | None,
    reviewer_id: int,
) -> bool:
    """Check whether reviewer_id is blocked from reviewing within the lock window."""
    # * A missing or zero ban_admin_id means the ban owner is unknown
    # * (legacy record): fail open with no lock, matching the documented
    # * contract. Failing closed here would lock out every reviewer for
    # * 12 hours with nobody able to act.
    if review_timestamp is None or not ban_admin_id:
        return False
    if reviewer_id == ban_admin_id:
        return False
    elapsed = utc_now() - to_utc(review_timestamp)
    return elapsed < _LOCK_WINDOW


# ────────────────────── Review mixin ───────────────────── #


class AppealReviewMixin:
    """Staff-side appeal review: decision routing plus approve/reject executors.

    Combined with ``AppealSubmitMixin`` in ``appeal_flow.BuildAppeal``; the
    attribute declaration below is provided by that concrete subclass.
    """

    community_name: str

    # ── Private helpers ────────────────────────────────────────────────────

    @staticmethod
    async def _update_or_send_log(
        bot: Bot,
        lc: int,
        lt: int | None,
        msg_id: int | None,
        text: str,
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
            await bot.send_message(
                lc, text, parse_mode="MarkdownV2", message_thread_id=lt
            )
        except Exception as exc:
            log.debug("Could not send appeal submitted log: %s", exc)

    # ── Public callback handler (registered outside the ConversationHandler) ─

    async def on_decision(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Approve / Reject callback for the staff review card in the main group."""
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

        # * Pre-fetch the reviewer role alongside the ban record and q.answer();
        # * ban_id is known from callback data so the DB calls fire speculatively.
        # * get_effective_role (not is_staff) is used so a database outage
        # * surfaces as an exception and gets a retry hint instead of being
        # * coerced to False and misreported as "not authorized".
        role_result, ban_result, answer_r = await asyncio.gather(
            db.users_roles.get_effective_role(admin.id),
            db.bans_db.get_ban(ban_id),
            q.answer(),
            return_exceptions=True,
        )
        # ! CRITICAL: cancellation must never render as a verdict. A cancelled
        # ! ban read coerced into "not found" would destroy the shared review
        # ! card on shutdown; a cancelled answer must propagate, not silence.
        throw_if_cancelled((role_result, ban_result, answer_r))
        if isinstance(answer_r, BaseException):
            log.debug("Appeal decision answer failed: %s", answer_r)
        if isinstance(role_result, BaseException):
            log.warning(
                "Appeal review role lookup failed for %d: %s", admin.id, role_result
            )
            # * Never edit the shared review card on an unmade decision:
            # * the card must stay actionable for another staffer.
            try:
                await q.answer(
                    t("appeals.review.role_lookup", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal role-lookup answer failed: %s", exc)
            return
        if role_result not in ("founder", "admin"):
            # * Answer with an alert instead of editing: the tapper is not
            # * staff, and editing would destroy the shared review card that
            # * staff still need to act on.
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
                await q.edit_message_text(
                    t("appeals.review.ban_not_found", locale, plain=True),
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("Appeal ban-not-found edit failed: %s", exc)
            return
        if not ban_result:
            try:
                await q.edit_message_text(
                    t("appeals.review.ban_not_found", locale, plain=True),
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("Appeal ban-not-found (empty) edit failed: %s", exc)
            return
        ban = ban_result

        # * An inactive ban with a live review marker is a stale card left
        # * behind by a manual /tcunban (which never touches review state).
        # * Clean it up so the card reflects reality; this is the only
        # * resolved path that edits, because no verdict exists to clobber.
        if not ban.get("is_active"):
            if ban.get("review_message_id"):
                try:
                    await db.bans_db.clear_review(ban_id)
                except Exception:
                    log.exception(
                        "Appeal stale-card clear_review failed for ban %s", ban_id
                    )
                try:
                    await q.edit_message_text(
                        t("appeals.review.already_resolved", locale, plain=True),
                        reply_markup=None,
                    )
                except Exception as exc:
                    log.debug("Appeal already-resolved edit failed: %s", exc)
            else:
                try:
                    await q.answer(
                        t("appeals.review.already_resolved", locale, plain=True),
                        show_alert=True,
                    )
                except Exception as exc:
                    log.debug("Appeal already-resolved answer failed: %s", exc)
            return

        # * A review that is already rejected or has no live review marker
        # * was decided by a concurrent tap. Acting again would double-DM
        # * the user, double-edit the card, or unban after a rejection.
        # * Alert only: the winner already edited the card with its verdict
        # * and overwriting it would destroy that outcome.
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
            # * Alert only: editing would destroy the shared card that the
            # * banning admin still needs to act on within their window.
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
        lc, lt = cfg.logs

        if action == "approve":
            await self._approve_appeal(
                ctx.bot, q, ban, ban_id, target_id, admin, lc, lt, update
            )
        elif action == "reject":
            await self._reject_appeal(
                ctx.bot, q, ban, ban_id, target_id, admin, lc, lt, update
            )

    # ── Appeal decision helpers ────────────────────────────────────────── #

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
    ) -> None:
        # * Fetch groups BEFORE deactivating, mirroring execute_unban: a
        # * groups-fetch failure with an already-deactivated record leaves
        # * chats unbanned-nowhere with no re-drive path (the record is
        # * gone, so a re-tap finds no active ban). Abort with the review
        # * card untouched so the decision stays actionable, alert the
        # * tapper, and let the error log ship to LOG_ERRORS.
        try:
            groups = await db.groups_db.active_groups()
        except Exception:
            log.exception(
                "approve_appeal: groups fetch failed for user=%d; "
                "aborting before deactivation",
                target_id,
            )
            try:
                locale = await locale_for_update(update)
                await q.answer(
                    replies.err_groups_load_failed(locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("approve_appeal groups-fail answer failed: %s", exc)
            return
        # * Deactivate ALL active bans for the user (not only the appeal ban_id)
        # * in parallel with fetching the target name and cancelling any
        # * pending timed-unban APScheduler job (future-proofing: no-op when
        # * no timed ban exists, same pattern as execute_unban in unban_flow.py).
        deactivate_result, target_fname, _ = await asyncio.gather(
            db.bans_db.deactivate_all_active_bans(target_id),
            db.users_cache.get_first_name(target_id, str(target_id)),
            db.scheduler.cancel_schedule(f"unban.{ban_id}"),
            return_exceptions=True,
        )
        # ! CRITICAL: a cancelled deactivation must propagate with the card
        # ! untouched so a re-tap retries the full sequence. Coercing it
        # ! into the DB-fail edit below would destroy the actionable card.
        if isinstance(deactivate_result, asyncio.CancelledError):
            raise deactivate_result
        if isinstance(deactivate_result, BaseException):
            # * Same trade-off as execute_unban in unban_flow.py: when the
            # * DB deactivation fails we must NOT continue to the fan-out,
            # * otherwise the user is unbanned in chats but the DB still
            # * marks them banned. The greeting handler's join-auto-ban
            # * would then re-ban them the next time they join any
            # * connected group. Abort with the review card untouched (a
            # * re-tap retries the full sequence) instead of editing it
            # * into a dead failure card with no recovery path, mirroring
            # * the groups-fetch failure path above.
            log.error(
                "approve_appeal: deactivate_all_active_bans failed for "
                "user=%d; aborting fan-out to avoid split-brain state: %s",
                target_id,
                deactivate_result,
            )
            try:
                locale = await locale_for_update(update)
                await q.answer(
                    t("appeals.review.db_retry", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("approve_appeal DB-fail answer failed: %s", exc)
            return
        if isinstance(target_fname, BaseException):
            # * Display-only fallback (covers a cancelled name read too):
            # * enforcement already committed above, so the fan-out below
            # * must still run rather than abort over a missing name.
            target_fname = str(target_id)

        # * Clear the review marker now that the ban is inactive. Without
        # * this a concurrent second decision would still see a live review
        # * and act again; the resolved-guard above relies on its absence.
        try:
            await db.bans_db.clear_review(ban_id)
        except Exception:
            log.exception("approve_appeal: clear_review failed for ban %s", ban_id)

        _primary_ids = [cid for cid in (cfg.main_group, cfg.exec_group) if cid]
        _existing_ids = {grp.get("chat_id", 0) for grp in groups}
        for _pid in _primary_ids:
            if _pid not in _existing_ids:
                groups = [*groups, {"chat_id": _pid, "title": ""}]

        unban_results = await fan_out(
            [
                bot.unban_chat_member(
                    grp.get("chat_id", 0), target_id, only_if_banned=True
                )
                for grp in groups
            ]
        )
        unban_failed = count_transient_errors(unban_results)
        if unban_failed:
            log.error(
                "Appeal-approve fan-out had %d/%d transient failures for "
                "target=%d; user may still be banned in those chats",
                unban_failed,
                len(groups),
                target_id,
            )

        appeal_link = ban.get("appeal_link") or ""
        appeal_submitted_at = ban.get("appeal_submitted_at")
        # * The four notifications are independent; capture each result so a
        # * silent DM, card-edit, or log failure is visible to operators
        # * instead of being swallowed like the reject path used to do.
        dm_r, card_r, log_r, unban_log_r = await asyncio.gather(
            bot.send_message(
                target_id,
                t(
                    "appeals.decision.approve_dm",
                    await locale_for_user(target_id),
                    ban_id=Safe(code(ban_id)),
                    community=self.community_name,
                ),
                parse_mode="MarkdownV2",
            ),
            q.edit_message_text(
                t(
                    "appeals.decision.approve_card",
                    await locale_for_update(update),
                    admin=Safe(mention(admin.id, admin.first_name)),
                ),
                parse_mode="MarkdownV2",
                reply_markup=None,
            ),
            self._update_or_send_log(
                bot,
                lc,
                lt,
                int(ban.get("appeal_log_msg_id") or 0) or None,
                parse_logmsg.appeal_approved_edit(
                    target_id,
                    target_fname,
                    admin.id,
                    admin.first_name,
                    ban_id,
                    str(appeal_link),
                    appeal_submitted_at,
                ),
            ),
            bot.send_message(
                lc,
                parse_logmsg.appeal_unban_log(
                    target_id,
                    target_fname,
                    admin.id,
                    admin.first_name,
                    ban_id,
                ),
                parse_mode="MarkdownV2",
                message_thread_id=lt,
            ),
            return_exceptions=True,
        )
        if isinstance(dm_r, BaseException):
            log.warning(
                "approve_appeal DM to %d failed for ban %s: %s",
                target_id,
                ban_id,
                dm_r,
            )
        if isinstance(card_r, BaseException):
            log.warning(
                "approve_appeal review-card edit failed for ban %s: %s", ban_id, card_r
            )
        if isinstance(log_r, BaseException):
            log.warning(
                "approve_appeal appeal-log update failed for ban %s: %s",
                ban_id,
                log_r,
            )
        if isinstance(unban_log_r, BaseException):
            log.error(
                "approve_appeal unban log send failed for user %d ban %s: %s",
                target_id,
                ban_id,
                unban_log_r,
            )

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
    ) -> None:
        # * The cooldown write and the display-name read are independent, so
        # * they run in parallel to save one DB round trip. Ordering against
        # * clear_review below is preserved: set_rejected_by still lands
        # * before the DM/edit/clear batch, so the 24 h cooldown holds even
        # * if the review clear fails. A cancelled cooldown write propagates
        # * (the decision stays actionable); a cancelled name read falls
        # * back to the numeric ID so the committed cooldown still notifies.
        set_r, name_r = await asyncio.gather(
            db.bans_db.set_rejected_by(ban_id, admin.id, admin.first_name),
            db.users_cache.get_first_name(target_id, str(target_id)),
            return_exceptions=True,
        )
        if isinstance(set_r, asyncio.CancelledError):
            raise set_r
        if isinstance(set_r, BaseException):
            # * Without rejected_at the user may re-appeal immediately; the
            # * ban itself still stands, so this fails safe toward re-review.
            log.exception("reject_appeal set_rejected_by failed for ban %s", ban_id)
        target_fname: str = (
            name_r if isinstance(name_r, str) and name_r else str(target_id)
        )
        if isinstance(name_r, BaseException) and not isinstance(
            name_r, asyncio.CancelledError
        ):
            log.debug("reject_appeal name fetch failed: %s", name_r)
        target_locale = await locale_for_user(target_id)
        staff_locale = await locale_for_update(update)
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
            q.edit_message_text(
                t(
                    "appeals.decision.reject_card",
                    staff_locale,
                    admin=Safe(mention(admin.id, admin.first_name)),
                ),
                parse_mode="MarkdownV2",
                reply_markup=None,
            ),
            db.bans_db.clear_review(ban_id),
            return_exceptions=True,
        )
        if isinstance(results[0], BaseException):
            log.warning("reject_appeal DM to %d failed: %s", target_id, results[0])
        if isinstance(results[1], BaseException):
            log.debug("reject_appeal review-card edit failed: %s", results[1])
        if isinstance(results[2], BaseException):
            # * ``clear_review`` failure is more serious: the user could
            # * re-submit an appeal within the 72-hour stale-review window
            # * because the DB still has the pending review. Log loudly.
            log.error(
                "reject_appeal clear_review failed for ban %s: user %d may "
                "re-appeal within the 72-hour window",
                ban_id,
                target_id,
            )

        await self._update_or_send_log(
            bot,
            lc,
            lt,
            int(ban.get("appeal_log_msg_id") or 0) or None,
            parse_logmsg.appeal_rejected_edit(
                target_id,
                target_fname,
                admin.id,
                admin.first_name,
                ban_id,
                str(ban.get("appeal_link") or ""),
                ban.get("appeal_submitted_at"),
            ),
        )
