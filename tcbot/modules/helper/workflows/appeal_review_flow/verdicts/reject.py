# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reject executor for staff appeal review."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Bot, CallbackQuery, User

from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.parse_editmsg import safe_edit_cb
from tcbot.modules.helper.workflows import appeal_review_flow as flow_pkg
from tcbot.modules.helper.workflows.appeal_review_flow.verdicts.logmsg import (
    _update_or_send_log,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)


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
        await safe_edit_cb(
            q,
            t(
                "appeals.decision.reject_card",
                staff_locale,
                admin=Safe(user_ref(admin.id, admin.first_name)),
            ),
            reply_markup=None,
            log_level="warning",
            log_label="reject_appeal review-card",
            catch_all=True,
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
