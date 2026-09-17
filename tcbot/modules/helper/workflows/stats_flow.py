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
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.extraction import (
    identity_needs_refresh,
    launch_identity_refresh,
)
from tcbot.modules.helper.keyboards import (
    back_to_module_kb,
    detail_kb,
    stats_back_kb,
    stats_back_row,
    stats_list_kb,
    stats_main_kb,
    stats_search_panel_kb,
    stats_search_results_kb,
    stats_search_row,
)
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import bold, code, esc, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.pagination import date_or_unknown, paginate
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

log = get_logger(__name__)

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

    from tcbot.database.documents import BanDoc

_PAGE_SIZE = 6

# * Cap for stats name search: bounds the $in fetch and the per-user
# * search-result state kept in user_data.
_SEARCH_LIMIT = 30

# * Search panel state lives on ``ctx.user_data`` while the user composes a
# * query. Kept here so the runtime callback handlers and the message-input
# * fallback can share the same key set without circular imports.
SEARCH_KEY = "stats_search_active"
RESULTS_KEY = "stats_search_results"
MSG_KEY = "stats_search_msg_id"
CHAT_KEY = "stats_search_chat_id"

# * Stats runtime prose lives in stats.toml [error]/[button]/[main]/
# * [roster]/[users]/[user_detail]/[chats]/[chat_detail]/[bans_view]/
# * [search]; only tunables stay in code.


# * Strong references to in-flight background-refresh tasks; prevents GC
# * before the coroutine completes (same pattern as harvest task sets).
_refresh_tasks: set[asyncio.Task[None]] = set()


async def _refresh_group_title(bot: Bot, chat_id: int) -> None:
    """Verify a group title live and persist renames (background, best-effort)."""
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
    """Fire-and-forget group title sync for detail views (zero added latency)."""
    try:
        task = asyncio.get_running_loop().create_task(
            _refresh_group_title(bot, chat_id)
        )
    except RuntimeError:
        log.debug("group title refresh skipped: no running event loop.")
        return
    _refresh_tasks.add(task)
    task.add_done_callback(_refresh_tasks.discard)


def _back_main(locale: str | None = None) -> list[InlineKeyboardButton]:
    """Back row to the stats main menu (single source: keyboards)."""
    return stats_back_row(locale)


# ─────────────────────── Keyboard builders ──────────────────────── #
# * Thin aliases over keyboards.py so existing imports keep working
# * while the markup itself lives in the single keyboard module.


def main_kb(
    *, show_users: bool = False, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Top-level ``/tcstats`` menu: Staff / Bans / Chats drill-downs.

    The ``Users`` list carries every cached user ID, so its button is shown
    only to the Owner/Founder (row 3); everyone else gets rows 1-2 only.
    The ``stats_users`` callbacks enforce the same gate, so a stale or
    crafted tap without the button still cannot open the list.
    """
    return stats_main_kb(show_users=show_users, locale=locale)


def back_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button returning to the stats main menu."""
    return stats_back_kb(locale)


def _list_kb(
    page: int,
    total_pages: int,
    n_items: int,
    cb_prefix: str,
    item_cb_prefix: str,
    *,
    extra_row: list[InlineKeyboardButton] | None = None,
    item_ids: list[str] | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Compose nav + numbered detail buttons + optional extra row + back.

    ``item_ids`` carries one stable entity ID per button (user ID, chat ID,
    or ban ID). Detail handlers verify the resolved record still carries
    that ID so a list mutation between render and tap cannot silently show
    a different record. Older buttons without the segment keep working.
    """
    return stats_list_kb(
        page,
        total_pages,
        n_items,
        cb_prefix,
        item_cb_prefix,
        extra_row=extra_row,
        item_ids=item_ids,
        locale=locale,
    )


# ────────────────────────── Stats class ─────────────────────────── #


class Stats:
    """All view builders for ``/tcstats``.

    The class is the single integration point for federation statistics: main
    overview, staff roster, member roster, connected chats, active bans, and
    the search panel. Every method is a classmethod returning ``(text, markup)``
    so callers can ``await q.answer()`` and ``safe_edit_cb`` without further
    work.
    """

    # ── Main overview ────────────────────────────────────────────────────

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
        # * An outage must never read as clean zeroes: flag it so the
        # * overview below carries the degraded note.
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

        # * Owner/Founder-only Users button. Cancellation propagates; any
        # * other viewer-lookup failure hides the button (fail closed) while
        # * the overview itself still renders.
        show_users = False
        if viewer_reads:
            owner_check, role_check = viewer_reads
            throw_if_cancelled((owner_check, role_check))
            show_users = (owner_check is True) or (role_check == "founder")

        # Fetch owner mention data in parallel with building the response
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

    # ── Staff roster ─────────────────────────────────────────────────────

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

        # * Resolve user mention data in one batch query instead of individual queries
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

        # Single batch query for all users
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

    # ── Users drill-down ─────────────────────────────────────────────────

    @classmethod
    async def users_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every cached user."""
        # * Server-side count + page fetch: the 200-doc cap in all_users()
        # * made deeper pages unreachable; page from the full collection.
        # * A read outage renders a retry card, never an empty clean list.
        try:
            total = await db.users_cache.total_users()
            total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
            page = max(0, min(page, total_pages - 1))
            chunk = await db.users_cache.all_users_page(
                skip=page * _PAGE_SIZE, limit=_PAGE_SIZE
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats users_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), back_kb(locale)

        if total == 0:
            text = t("stats.users.empty", locale)
            return text, back_kb(locale)

        lines = [
            t(
                "stats.users.header",
                locale,
                n=total,
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, u in enumerate(chunk, start=1):
            uid = u.get("user_id", 0)
            fname = u.get("first_name") or str(uid)
            uname = u.get("username")
            lines.append(
                t(
                    "stats.users.item",
                    locale,
                    i=base_idx + i,
                    user=Safe(user_ref(uid, fname, uname)),
                )
            )

        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_users",
            item_cb_prefix="stats_user_item",
            item_ids=[str(u.get("user_id", 0)) for u in chunk],
            locale=locale,
        )

    @classmethod
    async def user_detail(
        cls,
        bot: Bot,
        page: int,
        idx: int,
        stable: str | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a single cached user, with a link back into the list page."""
        chunk = await db.users_cache.all_users_page(
            skip=page * _PAGE_SIZE, limit=_PAGE_SIZE
        )
        if idx < 0 or idx >= len(chunk):
            text = t("stats.error.user_not_found", locale)
            kb = back_to_module_kb(f"stats_users:{page}", locale)
            return text, kb

        u = chunk[idx]
        uid = u.get("user_id", 0)
        if stable is not None and str(uid) != stable:
            text = t("stats.error.user_not_found", locale)
            kb = back_to_module_kb(f"stats_users:{page}", locale)
            return text, kb
        fname = u.get("first_name") or str(uid)
        uname = u.get("username")
        last_name = u.get("last_name") or "-"
        # * Stale-while-revalidate: render instantly from cache; refresh in
        # * background so the next view is current. Zero added latency.
        if identity_needs_refresh(u):
            launch_identity_refresh(bot, uid)
        commit = date_or_unknown(u.get("commit_date"), locale)
        seen = date_or_unknown(u.get("last_updated"), locale)

        if uname:
            username_line = t("stats.user_detail.username", locale, name=uname)
        else:
            username_line = t("stats.user_detail.username_none", locale)
        text = (
            f"{t('stats.user_detail.title', locale)}\n\n"
            f"{t('stats.user_detail.name', locale, user=Safe(user_ref(uid, fname, uname)))}\n"
            f"{t('stats.user_detail.id', locale, id=Safe(code(str(uid))))}\n"
            f"{username_line}\n"
            f"{t('stats.user_detail.last_name', locale, name=str(last_name))}\n\n"
            f"{t('stats.user_detail.first_seen', locale, date=Safe(commit))}\n"
            f"{t('stats.user_detail.last_seen', locale, date=Safe(seen))}\n\n"
            f"{t('stats.user_detail.check_hint', locale, command=Safe(code(f'/check {uid}')))}"
        )
        kb = back_to_module_kb(f"stats_users:{page}", locale)
        return text, kb

    # ── Connected chats drill-down ───────────────────────────────────────

    @classmethod
    async def chats_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every active connected group."""
        try:
            groups = await db.groups_db.active_groups()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats chats_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), back_kb(locale)
        chunk, total_pages, page = paginate(groups, page, _PAGE_SIZE)

        if not groups:
            text = t("stats.chats.empty", locale)
            return text, back_kb(locale)

        lines = [
            t(
                "stats.chats.header",
                locale,
                n=len(groups),
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, grp in enumerate(chunk, start=1):
            lines.append(
                t(
                    "stats.chats.item",
                    locale,
                    i=base_idx + i,
                    title=grp.get("title", "Unknown"),
                    id=Safe(code(str(grp.get("chat_id", 0)))),
                )
            )

        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_chats",
            item_cb_prefix="stats_chat_item",
            item_ids=[str(grp.get("chat_id", 0)) for grp in chunk],
            locale=locale,
        )

    @classmethod
    async def chat_detail(
        cls,
        bot: Bot,
        page: int,
        idx: int,
        stable: str | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a connected group."""
        groups = await db.groups_db.active_groups()
        chunk, _total, page = paginate(groups, page, _PAGE_SIZE)
        if idx < 0 or idx >= len(chunk):
            text = t("stats.error.group_not_found", locale)
            kb = back_to_module_kb(f"stats_chats:{page}", locale)
            return text, kb

        grp = chunk[idx]
        chat_id = grp.get("chat_id", 0)
        if stable is not None and str(chat_id) != stable:
            text = t("stats.error.group_not_found", locale)
            kb = back_to_module_kb(f"stats_chats:{page}", locale)
            return text, kb
        title = grp.get("title", "Unknown")
        # * Stale-while-revalidate: render instantly; renames persist in
        # * background for the next view. Zero added latency.
        launch_group_title_refresh(bot, chat_id)
        added_by = grp.get("added_by", 0)
        adder_fname, adder_uname = await db.users_cache.get_user_mention_data(added_by)
        date_str = date_or_unknown(grp.get("added_date"), locale)

        text = (
            f"{t('stats.chat_detail.title', locale)}\n\n"
            f"{t('stats.chat_detail.name', locale, name=Safe(bold(title)))}\n"
            f"{t('stats.chat_detail.chat_id', locale, id=Safe(code(str(chat_id))))}\n\n"
            f"{t('stats.chat_detail.connected_by', locale, user=Safe(user_ref(added_by, adder_fname, adder_uname)))}\n"
            f"{t('stats.chat_detail.date', locale, date=Safe(date_str))}"
        )
        kb = back_to_module_kb(f"stats_chats:{page}", locale)
        return text, kb

    # ── Bans drill-down ──────────────────────────────────────────────────

    @classmethod
    async def bans_list(
        cls, page: int, locale: str | None = None
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every active federation ban."""
        # * Server-side count + page fetch: only the visible slice travels
        # * over the wire regardless of federation size (no full-list load).
        # * A read outage renders a retry card, never an empty clean list.
        try:
            total = await db.bans_db.active_ban_count()
            total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
            page = max(0, min(page, total_pages - 1))
            chunk = await db.bans_db.active_bans_page(page * _PAGE_SIZE, _PAGE_SIZE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stats bans_list read failed: %s", exc)
            return t("stats.error.db_fail", locale), back_kb(locale)

        if total == 0:
            text = t("stats.bans_view.empty", locale)
            return text, back_kb(locale)

        # * Pre-resolve banned-user names with batch query
        uids = [b.get("banned_user_id", 0) for b in chunk]
        fname_map = await db.users_cache.get_first_names_batch(uids) if uids else {}

        lines = [
            t(
                "stats.bans_view.header",
                locale,
                n=total,
                page=page + 1,
                pages=total_pages,
            )
            + "\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, ban in enumerate(chunk, start=1):
            uid = ban.get("banned_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            lines.append(
                t(
                    "stats.bans_view.item",
                    locale,
                    i=base_idx + i,
                    name=fname,
                    id=Safe(code(str(uid))),
                )
            )

        search_row = stats_search_row(locale)
        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_bans",
            item_cb_prefix="stats_ban_item",
            extra_row=search_row,
            item_ids=[str(ban.get("ban_id", "")) for ban in chunk],
            locale=locale,
        )

    @classmethod
    async def ban_detail(
        cls,
        page: int,
        idx: int,
        stable: str | None = None,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a banned user, reusing ``build_ban_detail``.

        The record is fetched directly by stable ban ID (one indexed read)
        instead of re-reading the whole active-ban list: faster and immune
        to list shifts between render and tap. Inactive or missing records
        still report not-found.
        """
        if stable is not None:
            ban = await db.bans_db.get_ban(stable)
            if not ban or not ban.get("is_active"):
                text = t("stats.error.ban_not_found", locale)
                kb = back_to_module_kb(f"stats_bans:{page}", locale)
                return text, kb
            text, proof_link = await build_ban_detail(ban, locale=locale)
            return text, detail_kb(
                back_callback=f"stats_bans:{page}",
                proof_link=proof_link,
                locale=locale,
            )
        # Unreachable: _list_kb always provides a stable ban ID.
        return (
            t("stats.error.ban_not_found", locale),
            back_to_module_kb(f"stats_bans:{page}", locale),
        )

    # ── Search panel ─────────────────────────────────────────────────────

    @staticmethod
    def _search_panel_kb(locale: str | None = None) -> InlineKeyboardMarkup:
        """Search panel keyboard (single source: keyboards)."""
        return stats_search_panel_kb(locale)

    @staticmethod
    def _search_results_kb(
        n: int, locale: str | None = None, *, item_ids: list[str] | None = None
    ) -> InlineKeyboardMarkup:
        """Numbered search results (single source: keyboards)."""
        return stats_search_results_kb(n, locale, item_ids=item_ids)

    @classmethod
    def open_search(
        cls,
        ctx: ContextTypes.DEFAULT_TYPE,
        q: CallbackQuery,
        locale: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Open the search prompt; remember chat/message so input edits the right card.

        When the callback carries no accessible message (inline-message edge),
        the prompt still renders but no card IDs are stored, so a later search
        input degrades to a no-op edit instead of crashing on ``None``.
        """
        text = t("stats.search.title", locale)
        msg = q.message
        if not isinstance(msg, Message):
            return text, cls._search_panel_kb(locale)
        ud = cast("dict[str, object]", ctx.user_data)
        ud[SEARCH_KEY] = True
        ud[MSG_KEY] = msg.message_id
        ud[CHAT_KEY] = msg.chat_id
        return text, cls._search_panel_kb(locale)

    @staticmethod
    def clear_search(ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Forget any in-flight search context."""
        ud = cast("dict[str, object]", ctx.user_data)
        for key in (SEARCH_KEY, RESULTS_KEY, MSG_KEY, CHAT_KEY, "stats_last_query"):
            ud.pop(key, None)

    @classmethod
    async def search_run(
        cls,
        query: str,
    ) -> list[BanDoc]:
        """Resolve a search query against active bans (ID or name match).

        Name matching is server-side: an anchored prefix lookup in the
        member cache (same semantics as target resolution), capped at
        ``_SEARCH_LIMIT`` hits, then a single ``$in`` fetch of their
        active bans. Never loads the whole ban list.
        """
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
        """Render search results: empty state or numbered hits."""
        if not results:
            text = t("stats.search.empty", locale, query=query)
            return text, cls._search_results_kb(0, locale)
        # Batch query for all user names
        uids = [b.get("banned_user_id", 0) for b in results]
        fname_map = await db.users_cache.get_first_names_batch(uids)
        lines = [t("stats.search.header", locale, query=query, n=len(results)) + "\n"]
        for i, ban in enumerate(results, start=1):
            uid = ban.get("banned_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            lines.append(
                t(
                    "stats.search.item",
                    locale,
                    i=i,
                    name=fname,
                    id=Safe(code(str(uid))),
                )
            )
        return "\n".join(lines), cls._search_results_kb(
            len(results),
            locale,
            item_ids=[str(ban.get("ban_id", "")) for ban in results],
        )

    @classmethod
    async def search_detail(
        cls,
        results: list[BanDoc],
        idx: int,
        locale: str | None = None,
        stable: str | None = None,
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a single search hit.

        When ``stable`` carries the ban ID embedded in the tapped button,
        the record at ``idx`` must still carry it; a list mutation between
        render and tap otherwise shows the wrong ban.
        """
        if idx < 0 or idx >= len(results):
            text = t("stats.error.result_unavailable", locale)
            kb = back_to_module_kb("stats_search_back")
            return text, kb
        ban = results[idx]
        if stable is not None and str(ban.get("ban_id", "")) != stable:
            text = t("stats.error.result_unavailable", locale)
            kb = back_to_module_kb("stats_search_back")
            return text, kb
        text, proof_link = await build_ban_detail(ban, locale=locale)
        return text, detail_kb(
            back_callback="stats_search_back",
            proof_link=proof_link,
            locale=locale,
        )


__all__ = ("CHAT_KEY", "MSG_KEY", "RESULTS_KEY", "SEARCH_KEY", "Stats")
