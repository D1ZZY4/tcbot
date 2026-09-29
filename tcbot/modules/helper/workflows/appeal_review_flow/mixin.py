# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal review: staff approve/reject decisions on the shared review card."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.helper.workflows import appeal_review_flow as flow_pkg
from tcbot.modules.helper.workflows.appeal_review_flow.lock import (
    LOCK_HOURS,
    reviewer_locked_out,
)
from tcbot.modules.helper.workflows.appeal_review_flow.verdicts import (
    AppealVerdictsMixin,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from tcbot.database.documents import BanDoc

log = get_logger(__name__)


# ────────────────────── Review mixin ───────────────────── #


class AppealReviewMixin(AppealVerdictsMixin):
    """Staff-side appeal review: decision routing plus approve/reject executors.

    Combined with ``AppealSubmitMixin`` in ``appeal_flow.BuildAppeal``; the
    attribute declaration below is provided by that concrete subclass.
    The verdict executors live in ``AppealVerdictsMixin``; ``cfg`` and
    locale lookups resolve through the package namespace (``flow_pkg``) so
    package-level monkeypatching keeps working as it did for the flat module.
    """

    community_name: str

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

        locale = await flow_pkg.locale_for_update(update)
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
            # * Same rule as the role lookup above: never edit the shared
            # * review card on an unmade decision. A transient read failure
            # * is not evidence the ban is gone.
            try:
                await q.answer(
                    t("appeals.review.db_retry", locale, plain=True),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("Appeal ban-retry answer failed: %s", exc)
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
        ban: BanDoc = ban_result

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
        lc, lt = flow_pkg.cfg.logs

        if action == "approve":
            await self._approve_appeal(
                ctx.bot, q, ban, ban_id, target_id, admin, lc, lt, update
            )
        elif action == "reject":
            await self._reject_appeal(
                ctx.bot, q, ban, ban_id, target_id, admin, lc, lt, update
            )
