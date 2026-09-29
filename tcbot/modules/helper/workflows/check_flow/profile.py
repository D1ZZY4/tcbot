# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Top-level /check profile view: identity plus moderation counters."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from telegram import Bot, InlineKeyboardMarkup

from tcbot import database as db
from tcbot.modules.helper.identity import Identity, classify, profile_note
from tcbot.modules.helper.keyboards import check_profile_kb
from tcbot.modules.helper.workflows.check_flow.shared import (
    _resolve_user_info,
    log,
)
from tcbot.utils.formatter import bold, code, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.time_and_date import fmt_dt

if TYPE_CHECKING:
    from datetime import datetime

    from tcbot.database.documents import BanDoc


class CheckProfileMixin:
    """Top-level profile builder for the /check user-profile command."""

    @classmethod
    async def profile(
        cls,
        bot: Bot,
        target_id: int,
        *,
        executor_id: int | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Build the top-level profile view: identity + counts + drill-down keyboard.

        When ``executor_id`` is given, the target is also classified relative
        to the viewer so special identities get a recognition note (this bot,
        self, Telegram, anonymous admin); staff and Founder are already
        identified by the Role line.
        """
        # * All reads are independent; fire them in parallel for a single round-trip.
        # * return_exceptions=True prevents a single DB failure from crashing the whole view.
        # * fed_warn_total gives the federation-wide aggregate that user_total_warns hides
        # * (user_total_warns counts all historical warn docs; fed_warn_total sums active
        # * counters from warn_counts across all chats and is the staff-relevant number).
        # * The classify read is joined only when the viewer is known; /check is
        # * read-only and public, so a failed lookup degrades to no note (the
        # * fail-open "user" kind) instead of failing the whole card.
        _reads: list[Any] = [
            _resolve_user_info(bot, target_id),
            db.users_roles.role_meta(target_id),
            db.bans_db.get_active_ban(target_id),
            db.mutes_db.get_active_mute(target_id),
            db.bans_db.user_ban_count(target_id),
            db.bans_db.user_appeal_count(target_id),
            db.warns_db.user_total_warns(target_id),
            db.warns_db.user_warn_groups(target_id),
            db.warns_db.federation_warn_count(target_id),
            db.kicks_db.user_kick_count(target_id),
            db.mutes_db.user_mute_count(target_id),
        ]
        if executor_id is not None:
            _reads.append(classify(bot, executor_id, target_id))
        _results = await asyncio.gather(*_reads, return_exceptions=True)
        r_user_info = _results[0]
        r_role_meta = _results[1]
        ban_failed = isinstance(_results[2], BaseException)
        mute_failed = isinstance(_results[3], BaseException)
        counts_failed = any(isinstance(r, BaseException) for r in _results[4:11])
        active_ban = _results[2] if not ban_failed else None
        active_mute = _results[3] if not mute_failed else None
        ban_total = _results[4] if not isinstance(_results[4], BaseException) else 0
        appeal_total = _results[5] if not isinstance(_results[5], BaseException) else 0
        warn_total = _results[6] if not isinstance(_results[6], BaseException) else 0
        _wg = _results[7] if not isinstance(_results[7], BaseException) else None
        warn_groups: list[tuple[int, int]] = (
            cast("list[tuple[int, int]]", _wg) if _wg is not None else []
        )
        fed_warn_total = (
            _results[8] if not isinstance(_results[8], BaseException) else 0
        )
        kick_total = _results[9] if not isinstance(_results[9], BaseException) else 0
        mute_total = _results[10] if not isinstance(_results[10], BaseException) else 0

        if isinstance(r_user_info, BaseException):
            log.error("_resolve_user_info failed for %d: %s", target_id, r_user_info)
            fname, uname = str(target_id), None
        else:
            fname, uname = cast("tuple[str, str | None]", r_user_info)
        if isinstance(r_role_meta, BaseException):
            log.error("role_meta failed for %d: %s", target_id, r_role_meta)
            role, role_by_id, role_at = None, None, None
        else:
            role, role_by_id, role_at = cast(
                "tuple[str | None, int | None, datetime | None]", r_role_meta
            )

        # * Recognition note for special identities, owned by
        # * identity.profile_note (single source for "who is this?" copy).
        # * Staff and Founder need none: the Role line below already labels
        # * them. Cancellation propagates; any other lookup failure degrades
        # * to no note.
        identity_note: str | None = None
        if len(_results) > 11:
            r_ident = _results[11]
            if isinstance(r_ident, asyncio.CancelledError):
                raise r_ident
            if not isinstance(r_ident, BaseException):
                identity_note = profile_note(cast("Identity", r_ident), locale)

        role_label = (
            db.users_roles.ROLE_LABEL.get(
                role or "", t("checking.profile.regular", locale)
            )
            if role
            else t("checking.profile.regular", locale)
        )
        uname_part = (
            t("checking.profile.username", locale, name=uname or "")
            if uname
            else t("checking.profile.username_none", locale)
        )
        active_ban_doc = cast("BanDoc | None", active_ban)
        # * Never render a clean bill of health from a failed read: during a
        # * DB outage the lookups above coerce to None/0, which would show
        # * "Active Ban: No" and zero counts for a banned user. Surface
        # * Unknown instead so operators retry rather than trust the card.
        if ban_failed:
            active_part = t("checking.profile.unknown", locale)
        elif active_ban_doc:
            active_part = t(
                "checking.profile.yes_ban",
                locale,
                ban=Safe(
                    code(
                        active_ban_doc.get("ban_id", "")
                        if isinstance(active_ban_doc, dict)
                        else ""
                    )
                ),
            )
        else:
            active_part = t("checking.profile.no", locale)
        if mute_failed:
            active_mute_part = t("checking.profile.unknown", locale)
        else:
            active_mute_part = (
                t("checking.profile.yes", locale)
                if active_mute
                else t("checking.profile.no", locale)
            )

        # * Build the rich role line with assignment metadata where available.
        role_lines = [t("checking.profile.role", locale, role=Safe(bold(role_label)))]
        if role and role != "founder" and role_by_id:
            by_name = await db.users_cache.get_first_name(role_by_id, str(role_by_id))
            role_lines.append(
                t(
                    "checking.profile.assigned_by",
                    locale,
                    by=Safe(user_ref(role_by_id, by_name)),
                )
            )
        if role and role != "founder" and role_at:
            role_lines.append(
                t("checking.profile.assigned_at", locale, at=Safe(fmt_dt(role_at)))
            )
        role_block = Safe("\n".join(role_lines))

        uname_line = Safe(uname_part)
        active_ban_line = Safe(
            t("checking.profile.active_ban", locale, state=Safe(active_part))
        )
        active_mute_line = Safe(
            t("checking.profile.active_mute", locale, state=Safe(active_mute_part))
        )
        text = (
            (f"{identity_note}\n\n" if identity_note else "")
            + f"{t('checking.profile.title', locale)}\n\n"
            + f"{t('checking.profile.name', locale, user=Safe(user_ref(target_id, fname)))}\n"
            + f"{t('checking.profile.id', locale, id=Safe(code(str(target_id))))}\n"
            + f"{uname_line}\n"
            + f"{role_block}\n\n"
            + f"{t('checking.profile.activity', locale)}\n\n"
            + f"{active_ban_line}\n"
            + f"{active_mute_line}\n"
            + f"{t('checking.profile.total_bans', locale, n=ban_total)}\n"
            + f"{t('checking.profile.warnings', locale, active=fed_warn_total, groups=len(warn_groups) if warn_groups is not None else 0, total=warn_total)}\n"
            + f"{t('checking.profile.kicks', locale, n=kick_total)}\n"
            + f"{t('checking.profile.mutes', locale, n=mute_total)}\n"
            + f"{t('checking.profile.appeals', locale, n=appeal_total)}"
        )
        if counts_failed:
            text += f"\n\n{t('checking.profile.caveat', locale)}"

        return text, check_profile_kb(
            target_id,
            ban_total=ban_total,
            appeal_total=appeal_total,
            fed_warn_total=fed_warn_total,
            kick_total=kick_total,
            mute_total=mute_total,
            locale=locale,
        )
