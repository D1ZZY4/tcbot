# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation stats: overview, staff roster, users, connected chats, bans, search."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from telegram import (
    Bot,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.buttons import (
    stats_back_btn,
    stats_list_nav_btn,
    stats_main_btn,
    stats_search_panel_btn,
    stats_search_results_nav_btn,
    stats_search_row,
)
from tcbot.modules.helper.extraction import sync_user_identity
from tcbot.modules.helper.messages.rich_list import bullet_list
from tcbot.modules.helper.messages.rich_table import table
from tcbot.modules.helper.messages.rich_text import blocks
from tcbot.utils.dispatch import gather_bounded, throw_if_cancelled
from tcbot.utils.i18n import Safe, bold, code, divider, esc, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.pagination import clamp_page, paginate
from tcbot.utils.tasks import TaskTracker
from tcbot.utils.time_and_date import date_or_unknown, time_or_unknown
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)

# ────────────────────────── Title refresh ───────────────────────── #


# * Five rows keep each table well inside Telegram's rich-message limits
# * (32768 UTF-8 characters, 500 blocks) while staying easy to scan.
_PAGE_SIZE = 5
_SEARCH_LIMIT = 30
SEARCH_KEY = "stats_search_active"
RESULTS_KEY = "stats_search_results"
MSG_KEY = "stats_search_msg_id"
CHAT_KEY = "stats_search_chat_id"
# * Owner of the in-flight background group-title refreshes.
title_refresh_tasks = TaskTracker("group title refresh")


async def _refresh_group_title(bot: Bot, chat_id: int) -> None:
    """Verify a group title live and persist renames."""
    try:
        live_chat = await asyncio.wait_for(
            bot.get_chat(chat_id), timeout=TELEGRAM_LOOKUP_TIMEOUT
        )
    except Exception as exc:
        log.debug("background title check failed for %d: %s", chat_id, exc)
        return
    if live_chat is None or not live_chat.title:
        return
    try:
        await db.groups_db.refresh_group_title(chat_id, live_chat.title)
    except Exception as exc:
        log.debug("background title refresh failed for %d: %s", chat_id, exc)


def launch_group_title_refresh(bot: Bot, chat_id: int) -> None:
    """Fire-and-forget group title sync for detail views."""
    title_refresh_tasks.spawn(_refresh_group_title(bot, chat_id))


# ─────────────────────── Overview and roster ────────────────────── #


class OverviewViews:
    """Federation overview and staff roster builders."""

    @classmethod
    async def main(
        cls, *, viewer_id: int | None = None, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Federation overview card."""
        _reads: list[Any] = [
            db.users_roles.get_owner_id(),
            db.users_roles.admin_count(),
            db.users_roles.role_count("developer"),
            db.users_roles.role_count("moderator"),
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
            moderator_count,
            ban_count,
            group_count,
            user_count,
            *viewer_reads,
        ) = await asyncio.gather(*_reads, return_exceptions=True)
        throw_if_cancelled(
            (
                owner_id,
                admin_count,
                developer_count,
                moderator_count,
                ban_count,
                group_count,
                user_count,
                *viewer_reads,
            )
        )
        degraded = any(
            isinstance(r, BaseException)
            for r in (
                owner_id,
                admin_count,
                developer_count,
                moderator_count,
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
        moderator_count = (
            0
            if isinstance(moderator_count, BaseException)
            else cast("int", moderator_count)
        )
        if isinstance(ban_count, BaseException):
            ban_count = 0
        if isinstance(group_count, BaseException):
            group_count = 0
        if isinstance(user_count, BaseException):
            user_count = 0
        show_users = False
        show_staff = False
        if viewer_reads:
            owner_check, role_check = viewer_reads
            throw_if_cancelled((owner_check, role_check))
            if isinstance(role_check, BaseException):
                role_check = None
            show_users = (owner_check is True) or (role_check == "owner")
            # * The drill-down panes list federation-wide records, so they
            # * render for TC Staff only. The callbacks re-check the rank
            # * fresh, so the button is a convenience and not the gate.
            show_staff = show_users or db.users_roles.role_rank(
                role_check
            ) >= db.users_roles.role_rank("moderator")
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
            (1 if owner_id else 0) + admin_count + developer_count + moderator_count
        )
        rows = [
            [t("stats.main.table.owner", locale), owner_line],
            [
                t("stats.main.table.staff", locale),
                t(
                    "stats.main.table.staff_value",
                    locale,
                    n=Safe(bold(str(staff_total))),
                    admins=admin_count,
                    devs=developer_count,
                    moderators=moderator_count,
                ),
            ],
            [
                t("stats.main.table.users", locale),
                Safe(bold(str(user_count))),
            ],
            [
                t("stats.main.table.bans", locale),
                Safe(bold(str(ban_count))),
            ],
            [
                t("stats.main.table.chats", locale),
                Safe(bold(str(group_count))),
            ],
        ]
        text = (
            f"{t('stats.main.title', locale, community=Safe(bold(cfg.community_name)))}\n"
            f"{table([t('stats.main.table.metric', locale), t('stats.main.table.value', locale)], rows, raw_cells=True, compact=True, striped=True)}"
        )
        if degraded:
            text += f"\n{t('stats.main.degraded', locale)}"
        return blocks(text), stats_main_btn(
            show_users=show_users, show_staff=show_staff, locale=locale
        )

    @classmethod
    async def staff_roster(
        cls, locale: str | None = None, *, bot: Bot | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Full staff breakdown: Owner, Admins, Developers, Moderators."""
        owner_id, admins, developers, moderators = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.users_roles.all_admins(),
            db.users_roles.all_by_role("developer"),
            db.users_roles.all_by_role("moderator"),
            return_exceptions=True,
        )
        throw_if_cancelled((owner_id, admins, developers, moderators))
        if isinstance(owner_id, BaseException):
            owner_id = None
        if isinstance(admins, BaseException):
            admins = []
        if isinstance(developers, BaseException):
            developers = [] if isinstance(developers, BaseException) else developers
        if isinstance(moderators, BaseException):
            moderators = [] if isinstance(moderators, BaseException) else moderators
        all_user_ids = []
        owner_idx = None
        owner_id_int = 0
        if owner_id:
            owner_id_int = cast("int", owner_id)
            owner_idx = 0
            all_user_ids.append(owner_id_int)
        all_user_ids.extend(a.get("user_id", 0) for a in admins)
        all_user_ids.extend(d.get("user_id", 0) for d in developers)
        all_user_ids.extend(t.get("user_id", 0) for t in moderators)
        mention_data_map = await db.users_cache.get_mention_data_batch(all_user_ids)
        # * Staff without an identity row render as raw numeric IDs.
        # * Resolve those names live (bounded, failures keep the ID) so a
        # * legacy staff row never displays as an ID in the roster.
        if bot is not None:
            missing = [
                uid
                for uid in all_user_ids
                if uid and mention_data_map.get(uid, ("", None))[0] == str(uid)
            ]
            if missing:
                resolved = await gather_bounded(
                    [
                        asyncio.wait_for(
                            sync_user_identity(bot, uid),
                            timeout=TELEGRAM_LOOKUP_TIMEOUT,
                        )
                        for uid in missing
                    ]
                )
                throw_if_cancelled(resolved)
                for uid, result in zip(missing, resolved, strict=True):
                    if isinstance(result, BaseException):
                        log.debug(
                            "staff roster live identity failed for %d: %s",
                            uid,
                            result,
                        )
                        continue
                    live_fname, live_uname, _ = result
                    if not db.users_cache.is_placeholder_name(live_fname):
                        mention_data_map[uid] = (live_fname, live_uname)
        # * Build real rich blocks here instead of passing a newline fragment
        # * to blocks(): the divider is itself a block tag, which makes blocks()
        # * return the whole string verbatim and Telegram then collapses the
        # * bullet lines and newlines into one unreadable run.
        blocks_out = [
            f"<p>{t('stats.roster.title', locale, community=Safe(esc(cfg.community_name)))}</p>",
            divider(),
        ]
        if owner_idx is not None:
            blocks_out.append(f"<p>{t('stats.roster.owner', locale)}</p>")
            owner_fname, owner_uname = mention_data_map[owner_id_int]
            blocks_out.append(
                bullet_list(
                    [
                        t(
                            "stats.roster.member",
                            locale,
                            user=Safe(user_ref(owner_id_int, owner_fname, owner_uname)),
                        )
                    ]
                )
            )

        def _section(label: str, docs: list) -> None:
            blocks_out.append(
                f"<p>{t('stats.roster.section', locale, label=Safe(bold(f'{label} ({len(docs)})')))}</p>"
            )
            if docs:
                members: list[str] = []
                for doc in docs:
                    uid = doc.get("user_id", 0)
                    fname, uname = mention_data_map[uid]
                    members.append(
                        t(
                            "stats.roster.member",
                            locale,
                            user=Safe(user_ref(uid, fname, uname)),
                        )
                    )
                blocks_out.append(bullet_list(members))
            else:
                blocks_out.append(bullet_list([t("stats.roster.empty", locale)]))

        _section(t("stats.roster.admins", locale, plain=True), admins)
        _section(t("stats.roster.developers", locale, plain=True), developers)
        _section(t("stats.roster.moderators", locale, plain=True), moderators)
        return "".join(blocks_out), stats_back_btn(locale)


# ────────────────────────── Member lists ────────────────────────── #


class PeopleViews:
    """Paginated user table; every row carries the full cached profile."""

    @classmethod
    async def users_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated table of every cached user, with details in each row."""
        try:
            total = await db.users_cache.total_users()
            total_pages, page = clamp_page(total, page, _PAGE_SIZE)
            chunk = await db.users_cache.all_users_page(
                skip=page * _PAGE_SIZE, limit=_PAGE_SIZE
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats users_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), stats_back_btn(locale)
        if total == 0:
            return t("stats.users.empty", locale), stats_back_btn(locale)
        header = t(
            "stats.users.header", locale, n=total, page=page + 1, pages=total_pages
        )
        rows: list[list[str]] = []
        for u in chunk:
            uid = u.get("user_id", 0)
            fname = u.get("first_name") or str(uid)
            uname = u.get("username")
            rows.append(
                [
                    Safe(user_ref(uid, fname, uname)),
                    Safe(code(str(uid))),
                    esc(uname or "-"),
                    esc(date_or_unknown(u.get("first_seen_at"), locale)),
                    esc(time_or_unknown(u.get("first_seen_at"), locale)),
                    esc(date_or_unknown(u.get("last_seen_at"), locale)),
                    esc(time_or_unknown(u.get("last_seen_at"), locale)),
                ]
            )
        text = (
            f"{header}\n"
            f"{table([t('stats.table.user', locale, plain=True), t('stats.table.id', locale, plain=True), t('stats.table.username', locale, plain=True), t('stats.table.first_seen', locale, plain=True), t('stats.table.time', locale, plain=True), t('stats.table.last_seen', locale, plain=True), t('stats.table.time', locale, plain=True)], rows, raw_cells=True, compact=True, striped=True)}"
        )
        return blocks(text), stats_list_nav_btn(
            page, total_pages, "stats_users", locale=locale
        )


# ─────────────────────────── Group lists ────────────────────────── #


class ChatViews:
    """Paginated connected-group table; each row carries the group details."""

    @classmethod
    async def chats_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated table of every active connected group."""
        try:
            groups = await db.groups_db.active_groups()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats chats_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), stats_back_btn(locale)
        chunk, total_pages, page = paginate(groups, page, _PAGE_SIZE)
        if not groups:
            return t("stats.chats.empty", locale), stats_back_btn(locale)
        header = t(
            "stats.chats.header",
            locale,
            n=len(groups),
            page=page + 1,
            pages=total_pages,
        )
        mention_map = await db.users_cache.get_mention_data_batch(
            [grp.get("added_by", 0) for grp in chunk]
        )
        rows: list[list[str]] = []
        for grp in chunk:
            chat_id = grp.get("chat_id", 0)
            title = grp.get("title") or t(
                "common.action.unknown_title", locale, plain=True
            )
            added_by = grp.get("added_by", 0)
            fname, uname = mention_map.get(added_by, (str(added_by), None))
            rows.append(
                [
                    esc(title),
                    Safe(code(str(chat_id))),
                    Safe(user_ref(added_by, fname, uname)),
                    esc(date_or_unknown(grp.get("added_date"), locale)),
                    esc(time_or_unknown(grp.get("added_date"), locale)),
                ]
            )
        text = (
            f"{header}\n"
            f"{table([t('stats.table.group', locale, plain=True), t('stats.table.id', locale, plain=True), t('stats.table.connected_by', locale, plain=True), t('stats.table.date', locale, plain=True), t('stats.table.time', locale, plain=True)], rows, raw_cells=True, compact=True, striped=True)}"
        )
        return blocks(text), stats_list_nav_btn(
            page, total_pages, "stats_chats", locale=locale
        )


# ──────────────────────────── Ban lists ─────────────────────────── #


class BanViews:
    """Paginated active-ban table; each row carries the ban details."""

    @classmethod
    async def bans_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated table of every active federation ban."""
        try:
            total = await db.bans_db.active_ban_count()
            total_pages, page = clamp_page(total, page, _PAGE_SIZE)
            chunk = await db.bans_db.active_bans_page(page * _PAGE_SIZE, _PAGE_SIZE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats bans_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), stats_back_btn(locale)
        if total == 0:
            return t("stats.bans_view.empty", locale), stats_back_btn(locale)
        uids = [b.get("target_user_id", 0) for b in chunk]
        fname_map = await db.users_cache.get_first_names_batch(uids) if uids else {}
        header = t(
            "stats.bans_view.header",
            locale,
            n=total,
            page=page + 1,
            pages=total_pages,
        )
        rows: list[list[str]] = []
        for ban in chunk:
            uid = ban.get("target_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            rows.append(
                [
                    Safe(user_ref(uid, fname)),
                    Safe(code(str(uid))),
                    esc(str(ban.get("reason") or "-")),
                    Safe(code(str(ban.get("ban_id") or "-"))),
                    esc(date_or_unknown(ban.get("timestamp"), locale)),
                    esc(time_or_unknown(ban.get("timestamp"), locale)),
                ]
            )
        text = (
            f"{header}\n"
            f"{table([t('stats.table.user', locale, plain=True), t('stats.table.id', locale, plain=True), t('stats.table.reason', locale, plain=True), t('stats.table.ban', locale, plain=True), t('stats.table.date', locale, plain=True), t('stats.table.time', locale, plain=True)], rows, raw_cells=True, compact=True, striped=True)}"
        )
        return blocks(text), stats_list_nav_btn(
            page,
            total_pages,
            "stats_bans",
            extra_row=stats_search_row(locale),
            locale=locale,
        )


# ───────────────────────────── Search ───────────────────────────── #


class SearchViews:
    """Search prompt lifecycle and result rendering for active bans."""

    @staticmethod
    def _search_panel_btn(locale: str | None = None) -> InlineKeyboardMarkup:
        """Search panel keyboard."""
        return stats_search_panel_btn(locale)

    @classmethod
    def open_search(
        cls,
        ctx: ContextTypes.DEFAULT_TYPE,
        q: CallbackQuery,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Open the search prompt; remember chat/message for input edits."""
        text = t("stats.search.title", locale)
        msg = q.message
        if not isinstance(msg, Message):
            return blocks(text), cls._search_panel_btn(locale)
        ud = cast("dict[str, object]", ctx.user_data)
        ud[SEARCH_KEY] = True
        ud[MSG_KEY] = msg.message_id
        ud[CHAT_KEY] = msg.chat_id
        return blocks(text), cls._search_panel_btn(locale)

    @staticmethod
    def clear_search(ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Forget any in-flight search context."""
        ud = cast("dict[str, object]", ctx.user_data)
        for key in (SEARCH_KEY, RESULTS_KEY, MSG_KEY, CHAT_KEY, "stats_last_query"):
            ud.pop(key, None)

    @classmethod
    async def search_run(cls, query: str) -> list[BanDoc]:
        """Resolve a search query against active bans (ID or name match)."""
        q = query.strip()
        if q.isdigit():
            ban = await db.bans_db.get_active_ban(int(q))
            return [ban] if ban else []
        matches = await db.users_cache.search_by_name(q, limit=_SEARCH_LIMIT)
        if not matches:
            return []
        uids = [u.get("user_id", 0) for u in matches if u.get("user_id")]
        return await db.bans_db.active_bans_for_users(uids)

    @classmethod
    async def search_results(
        cls,
        query: str,
        results: list[BanDoc],
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Render search results as a table: empty state or full hits."""
        if not results:
            text = t("stats.search.empty", locale, query=query)
            return blocks(text), stats_search_results_nav_btn(locale)
        uids = [b.get("target_user_id", 0) for b in results]
        fname_map = await db.users_cache.get_first_names_batch(uids)
        header = t("stats.search.header", locale, query=query, n=len(results))
        rows: list[list[str]] = []
        for ban in results:
            uid = ban.get("target_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            rows.append(
                [
                    Safe(user_ref(uid, fname)),
                    Safe(code(str(uid))),
                    esc(str(ban.get("reason") or "-")),
                    Safe(code(str(ban.get("ban_id") or "-"))),
                ]
            )
        text = (
            f"{header}\n"
            f"{table([t('stats.table.user', locale, plain=True), t('stats.table.id', locale, plain=True), t('stats.table.reason', locale, plain=True), t('stats.table.ban', locale, plain=True)], rows, raw_cells=True, compact=True, striped=True)}"
        )
        return blocks(text), stats_search_results_nav_btn(locale)


class Stats(OverviewViews, PeopleViews, ChatViews, BanViews, SearchViews):
    """All view builders for /tcstats."""
