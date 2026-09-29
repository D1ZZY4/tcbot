# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Approve / reject executors for staff appeal review."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Bot, CallbackQuery, User

from tcbot import database as db
from tcbot.modules.helper import parse_logmsg, replies
from tcbot.modules.helper.workflows import appeal_review_flow as flow_pkg
from tcbot.utils.dispatch import count_transient_errors, fan_out
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)


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
        await bot.send_message(lc, text, parse_mode="MarkdownV2", message_thread_id=lt)
    except Exception as exc:
        log.debug("Could not send appeal submitted log: %s", exc)


class AppealVerdictsMixin:
    """Staff-side appeal verdict executors: approve fans out unbans, reject cools down.

    Combined into ``AppealReviewMixin``; ``cfg`` and locale lookups resolve
    through the package namespace (``flow_pkg``) so package-level
    monkeypatching keeps working as it did for the flat module.
    """

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
                locale = await flow_pkg.locale_for_update(update)
                await q.answer(
                    replies.err_groups_load_failed(locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("approve_appeal groups-fail answer failed: %s", exc)
            return
        # * Deactivate ALL active bans for the user (not only the appeal ban_id)
        # * in parallel with fetching the target name.
        deactivate_result, target_fname = await asyncio.gather(
            db.bans_db.deactivate_all_active_bans(target_id),
            db.users_cache.get_first_name(target_id, str(target_id)),
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
                locale = await flow_pkg.locale_for_update(update)
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

        # * Connected groups plus primaries (single merge owner in groups_db).
        groups = db.groups_db.with_primary_groups(
            groups, (flow_pkg.cfg.main_group, flow_pkg.cfg.exec_group)
        )

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
        # * Both locales resolve up front in parallel: awaiting them inline
        # * below would serialize two reads before the fan-out even starts.
        target_locale, staff_locale = await asyncio.gather(
            flow_pkg.locale_for_user(target_id),
            flow_pkg.locale_for_update(update),
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
        # * they run in parallel to save one DB round trip. A cancelled
        # * cooldown write propagates (the decision stays actionable); a
        # * cancelled name read falls back to the numeric ID so the
        # * committed cooldown still notifies.
        set_r, name_r = await asyncio.gather(
            db.bans_db.set_rejected_by(ban_id, admin.id, admin.first_name),
            db.users_cache.get_first_name(target_id, str(target_id)),
            return_exceptions=True,
        )
        if isinstance(set_r, asyncio.CancelledError):
            raise set_r
        if isinstance(set_r, BaseException):
            # * Without rejected_at the verdict card would show "rejected"
            # * while the user may re-appeal immediately. Abort with the
            # * card untouched (a re-tap retries the full sequence),
            # * mirroring the approve DB-fail path.
            log.exception("reject_appeal set_rejected_by failed for ban %s", ban_id)
            try:
                staff_locale = await flow_pkg.locale_for_update(update)
                await q.answer(
                    t("appeals.review.db_retry", staff_locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("reject_appeal DB-fail answer failed: %s", exc)
            return
        target_fname: str = (
            name_r if isinstance(name_r, str) and name_r else str(target_id)
        )
        if isinstance(name_r, BaseException) and not isinstance(
            name_r, asyncio.CancelledError
        ):
            log.debug("reject_appeal name fetch failed: %s", name_r)
        # * The target DM locale and the staff card locale are independent
        # * reads; one gather instead of two serial round trips.
        target_locale, staff_locale = await asyncio.gather(
            flow_pkg.locale_for_user(target_id),
            flow_pkg.locale_for_update(update),
        )
        # * Edit the verdict card before clearing the review marker so a
        # * successful edit removes live buttons before the DB slot frees.
        # * A transient edit failure still proceeds to DM + clear below
        # * (matching the approve path): the decision is already committed
        # * in rejected_at, so keeping the marker would block the user past
        # * the 24 h cooldown until the 72 h stale window. The card keeps
        # * live buttons that answer already-resolved on re-tap, and the
        # * failure is logged for operators.
        try:
            await q.edit_message_text(
                t(
                    "appeals.decision.reject_card",
                    staff_locale,
                    admin=Safe(user_ref(admin.id, admin.first_name)),
                ),
                parse_mode="MarkdownV2",
                reply_markup=None,
            )
        except Exception as exc:
            log.warning("reject_appeal review-card edit failed: %s", exc)
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
        if isinstance(results[0], BaseException):
            log.warning("reject_appeal DM to %d failed: %s", target_id, results[0])
        if isinstance(results[1], BaseException):
            # * ``clear_review`` failure is more serious: the user could
            # * re-submit an appeal within the 72-hour stale-review window
            # * because the DB still has the pending review. Log loudly.
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
