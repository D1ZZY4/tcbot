# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation overview and staff roster views."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from telegram import InlineKeyboardMarkup

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.workflows.stats_flow.shared import back_kb, main_kb
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import bold, esc, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


class OverviewViews:
    """Federation overview and staff roster builders."""

    @classmethod
    async def main(
        cls, *, viewer_id: int | None = None, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Federation overview: Founder, staff total, user cache, bans, chats.

        When ``viewer_id`` belongs to the Owner/Founder, the menu gains the
        ``Users`` button (row 3); the ``stats_users`` callbacks enforce the
        same gate. A failed viewer lookup hides the button (fail closed).
        """
        _reads: list[Any] = [
            db.users_roles.get_owner_id(),
            db.users_roles.admin_count(),
            db.users_roles.role_count("developer"),
            db.users_roles.role_count("tester"),
            db.bans_db.active_ban_count(),
            db.groups_db.active_group_count(),
            db.users_cache.total_users(),
        ]
        if viewer_id is not None:
            _reads.append(db.users_roles.is_owner(viewer_id))
            _reads.append(db.users_roles.get_effective_role(viewer_id))
        (
            owner_id,
            admin_count,
            developer_count,
            tester_count,
            ban_count,
            group_count,
            user_count,
            *viewer_reads,
        ) = await asyncio.gather(*_reads, return_exceptions=True)
        # * An outage must never read as clean zeroes: flag degraded output.
        degraded = any(
            isinstance(r, BaseException)
            for r in (
                owner_id,
                admin_count,
                developer_count,
                tester_count,
                ban_count,
                group_count,
                user_count,
            )
        )
        owner_id = (
            0 if isinstance(owner_id, BaseException) else cast("int | None", owner_id)
        )
        admin_count = (
            0 if isinstance(admin_count, BaseException) else cast("int", admin_count)
        )
        developer_count = (
            0
            if isinstance(developer_count, BaseException)
            else cast("int", developer_count)
        )
        tester_count = (
            0 if isinstance(tester_count, BaseException) else cast("int", tester_count)
        )
        if isinstance(ban_count, BaseException):
            ban_count = 0
        if isinstance(group_count, BaseException):
            group_count = 0
        if isinstance(user_count, BaseException):
            user_count = 0

        # * Cancellation propagates; other viewer-lookup failures fail closed.
        show_users = False
        if viewer_reads:
            owner_check, role_check = viewer_reads
            throw_if_cancelled((owner_check, role_check))
            show_users = (owner_check is True) or (role_check == "founder")

        if owner_id:
            owner_id_int = cast("int", owner_id)
            try:
                owner_fname, owner_uname = await db.users_cache.get_user_mention_data(
                    owner_id_int
                )
            except Exception as exc:
                log.debug(
                    "stats main: get_user_mention_data failed for owner %d: %s",
                    owner_id_int,
                    exc,
                )
                owner_fname, owner_uname = str(owner_id_int), None
            owner_line = Safe(user_ref(owner_id_int, owner_fname, owner_uname))
        else:
            owner_line = Safe(t("stats.main.owner_unset", locale))

        staff_total = (
            (1 if owner_id else 0) + admin_count + developer_count + tester_count
        )

        text = (
            f"{t('stats.main.title', locale, community=Safe(bold(cfg.community_name)))}\n\n"
            f"{t('stats.main.founder', locale, owner=owner_line)}\n"
            f"{t('stats.main.staff', locale, n=Safe(bold(str(staff_total))), admins=admin_count, devs=developer_count, testers=tester_count)}\n"
            f"{t('stats.main.users', locale, n=Safe(bold(str(user_count))))}\n"
            f"{t('stats.main.bans', locale, n=Safe(bold(str(ban_count))))}\n"
            f"{t('stats.main.chats', locale, n=Safe(bold(str(group_count))))}"
        )
        if degraded:
            text += f"\n\n{t('stats.main.degraded', locale)}"
        return text, main_kb(show_users=show_users, locale=locale)

    @classmethod
    async def staff_roster(
        cls, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Full staff breakdown: Founder, Admins, Developers, Testers."""
        owner_id, admins, developers, testers = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.users_roles.all_admins(),
            db.users_roles.all_by_role("developer"),
            db.users_roles.all_by_role("tester"),
            return_exceptions=True,
        )
        if isinstance(owner_id, BaseException):
            owner_id = None
        if isinstance(admins, BaseException):
            admins = []
        if isinstance(developers, BaseException):
            developers = [] if isinstance(developers, BaseException) else developers
        if isinstance(testers, BaseException):
            testers = [] if isinstance(testers, BaseException) else testers

        all_user_ids = []
        owner_idx = None
        owner_id_int = 0
        if owner_id:
            owner_id_int = cast("int", owner_id)
            owner_idx = 0
            all_user_ids.append(owner_id_int)
        all_user_ids.extend(a.get("user_id", 0) for a in admins)
        all_user_ids.extend(d.get("user_id", 0) for d in developers)
        all_user_ids.extend(t.get("user_id", 0) for t in testers)

        mention_data_map = await db.users_cache.get_mention_data_batch(all_user_ids)

        lines = [
            t(
                "stats.roster.title",
                locale,
                community=Safe(esc(cfg.community_name)),
            )
            + "\n"
        ]

        if owner_idx is not None:
            lines.append(t("stats.roster.founder", locale))
            owner_fname, owner_uname = mention_data_map[owner_id_int]
            lines.append(
                t(
                    "stats.roster.member",
                    locale,
                    user=Safe(user_ref(owner_id_int, owner_fname, owner_uname)),
                )
                + "\n"
            )

        def _section(label: str, docs: list) -> None:
            lines.append(
                t(
                    "stats.roster.section",
                    locale,
                    label=Safe(bold(f"{label} ({len(docs)})")),
                )
            )
            if docs:
                for doc in docs:
                    uid = doc.get("user_id", 0)
                    fname, uname = mention_data_map[uid]
                    lines.append(
                        t(
                            "stats.roster.member",
                            locale,
                            user=Safe(user_ref(uid, fname, uname)),
                        )
                    )
            else:
                lines.append(t("stats.roster.empty", locale))
            lines.append("")

        _section("Admins", admins)
        _section("Developers", developers)
        _section("Testers", testers)

        return "\n".join(lines).rstrip(), back_kb(locale)
