# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Federation stats: overview, staff roster, users, connected chats, bans, search."""

from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.formatter import bold, code, esc, mention
from tcbot.utils.pagination import date_or_unknown, nav_row, paginate

_PAGE_SIZE = 6

# * Search panel state lives on ``ctx.user_data`` while the user composes a
# * query. Kept here so the runtime callback handlers and the message-input
# * fallback can share the same key set without circular imports.
SEARCH_KEY = "stats_search_active"
RESULTS_KEY = "stats_search_results"
MSG_KEY = "stats_search_msg_id"
CHAT_KEY = "stats_search_chat_id"


def _back_main() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("« Back", callback_data="stats_main")]


# ─────────────────────── Keyboard builders ──────────────────────── #


def main_kb() -> InlineKeyboardMarkup:
    """Top-level ``/tcstats`` menu: Staff / Users / Chats / Bans drill-downs."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Staff Roster", callback_data="stats_admins"),
                InlineKeyboardButton("Users", callback_data="stats_users:0"),
            ],
            [
                InlineKeyboardButton("Connected Chats", callback_data="stats_chats:0"),
                InlineKeyboardButton("User Bans", callback_data="stats_bans:0"),
            ],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    """Single ``« Back`` returning to the stats main menu."""
    return InlineKeyboardMarkup([_back_main()])


def _list_kb(
    page: int,
    total_pages: int,
    n_items: int,
    cb_prefix: str,
    item_cb_prefix: str,
    *,
    extra_row: list[InlineKeyboardButton] | None = None,
) -> InlineKeyboardMarkup:
    """Compose nav + numbered detail buttons + optional extra row + back."""
    rows: list[list[InlineKeyboardButton]] = []
    nav = nav_row(page, total_pages, cb_prefix)
    if nav:
        rows.append(nav)

    num_btns = [
        InlineKeyboardButton(str(i + 1), callback_data=f"{item_cb_prefix}:{page}:{i}")
        for i in range(n_items)
    ]
    for i in range(0, len(num_btns), 3):
        rows.append(num_btns[i : i + 3])

    if extra_row:
        rows.append(extra_row)
    rows.append(_back_main())
    return InlineKeyboardMarkup(rows)


# ────────────────────────── Stats class ─────────────────────────── #


class Stats:
    """All view builders for ``/tcstats``.

    The class is the single integration point for federation statistics: main
    overview, staff roster, member roster, connected chats, active bans, and
    the search panel. Every method is a classmethod returning ``(text, markup)``
    so callers can ``await q.answer()`` and ``safe_edit_cb`` without further
    work.
    """

    PAGE_SIZE = _PAGE_SIZE

    # ── Main overview ────────────────────────────────────────────────────

    @classmethod
    async def main(cls) -> tuple[str, InlineKeyboardMarkup]:
        """Federation overview: Founder, staff total, user cache, bans, chats."""
        (
            owner_id,
            admin_count,
            developers,
            testers,
            ban_count,
            group_count,
            user_count,
        ) = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.users_roles.admin_count(),
            db.users_roles.all_by_role("developer"),
            db.users_roles.all_by_role("tester"),
            db.bans_db.active_ban_count(),
            db.groups_db.active_group_count(),
            db.users_cache.total_users(),
        )

        # Fetch owner mention data in parallel with building the response
        if owner_id:
            owner_fname, owner_uname = await db.users_cache.get_user_mention_data(
                owner_id
            )
            owner_line = mention(owner_id, owner_fname, owner_uname)
        else:
            owner_line = "Not set"

        staff_total = (
            (1 if owner_id else 0) + admin_count + len(developers) + len(testers)
        )

        text = (
            f"{bold(esc(cfg.community_name))} {bold('Stats')}\n\n"
            f"Founder: {owner_line}\n"
            f"Staff: {bold(str(staff_total))} "
            f"(Admins {admin_count}, Devs {len(developers)}, Testers {len(testers)})\n"
            f"Users tracked: {bold(str(user_count))}\n"
            f"Active bans: {bold(str(ban_count))}\n"
            f"Connected chats: {bold(str(group_count))}"
        )
        return text, main_kb()

    # ── Staff roster ─────────────────────────────────────────────────────

    @classmethod
    async def staff_roster(cls) -> tuple[str, InlineKeyboardMarkup]:
        """Full staff breakdown: Founder, Admins, Developers, Testers."""
        owner_id, admins, developers, testers = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.users_roles.all_admins(),
            db.users_roles.all_by_role("developer"),
            db.users_roles.all_by_role("tester"),
        )

        # * Resolve user mention data in one batch query instead of individual queries
        all_user_ids = []
        owner_idx = None
        if owner_id:
            owner_idx = 0
            all_user_ids.append(owner_id)
        all_user_ids.extend(a["user_id"] for a in admins)
        all_user_ids.extend(d["user_id"] for d in developers)
        all_user_ids.extend(t["user_id"] for t in testers)

        # Single batch query for all users
        mention_data_map = await db.users_cache.get_mention_data_batch(all_user_ids)

        lines = [f"{bold('Staff Roster')} - {esc(cfg.community_name)}\n"]

        if owner_idx is not None:
            lines.append(bold("Founder"))
            owner_fname, owner_uname = mention_data_map[owner_id]
            lines.append(f"- {mention(owner_id, owner_fname, owner_uname)}\n")

        def _section(label: str, docs: list) -> None:
            lines.append(bold(f"{label} ({len(docs)})"))
            if docs:
                for doc in docs:
                    uid = doc["user_id"]
                    fname, uname = mention_data_map[uid]
                    lines.append(f"- {mention(uid, fname, uname)}")
            else:
                lines.append("- None assigned")
            lines.append("")

        _section("Admins", admins)
        _section("Developers", developers)
        _section("Testers", testers)

        return "\n".join(lines).rstrip(), back_kb()

    # ── Users drill-down ─────────────────────────────────────────────────

    @classmethod
    async def users_list(cls, page: int) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every cached user."""
        users = await db.users_cache.all_users()
        chunk, total_pages, page = paginate(users, page, _PAGE_SIZE)

        if not users:
            text = (
                f"{bold('Users')}\n\nNo cached users yet. The bot caches users "
                "as it sees them across connected groups."
            )
            return text, back_kb()

        lines = [
            f"{bold('Users')} - {len(users)} total  ·  page {page + 1}/{total_pages}\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, u in enumerate(chunk, start=1):
            uid = u.get("user_id", 0)
            fname = u.get("first_name") or f"User {uid}"
            uname = u.get("username")
            tail = f" · @{esc(uname)}" if uname else ""
            lines.append(
                f"{base_idx + i}. {mention(uid, fname, uname)} - {code(str(uid))}{tail}"
            )

        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_users",
            item_cb_prefix="stats_user_item",
        )

    @classmethod
    async def user_detail(cls, page: int, idx: int) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a single cached user, with a link back into the list page."""
        users = await db.users_cache.all_users()
        chunk, _total, page = paginate(users, page, _PAGE_SIZE)
        if idx < 0 or idx >= len(chunk):
            text = "User not found in this page."
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back", callback_data=f"stats_users:{page}")]]
            )
            return text, kb

        u = chunk[idx]
        uid = u.get("user_id", 0)
        fname = u.get("first_name") or f"User {uid}"
        uname = u.get("username")
        last_name = u.get("last_name") or "-"
        commit = date_or_unknown(u.get("commit_date"))
        seen = date_or_unknown(u.get("last_updated"))

        text = (
            f"{bold('User Details')}\n\n"
            f"Name: {mention(uid, fname, uname)}\n"
            f"ID: {code(str(uid))}\n"
            f"Username: {('@' + esc(uname)) if uname else '-'}\n"
            f"Last name: {esc(str(last_name))}\n\n"
            f"First seen: {commit}\n"
            f"Last seen: {seen}\n\n"
            f"Use <code>/check {uid}</code> for the full profile."
        )
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("« Back", callback_data=f"stats_users:{page}")]]
        )
        return text, kb

    # ── Connected chats drill-down ───────────────────────────────────────

    @classmethod
    async def chats_list(cls, page: int) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every active connected group."""
        groups = await db.groups_db.active_groups()
        chunk, total_pages, page = paginate(groups, page, _PAGE_SIZE)

        if not groups:
            text = f"{bold('Connected Chats')}\n\nNo connected groups yet."
            return text, back_kb()

        lines = [
            f"{bold('Connected Chats')} - {len(groups)} total  "
            f"·  page {page + 1}/{total_pages}\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, grp in enumerate(chunk, start=1):
            lines.append(
                f"{base_idx + i}. {esc(grp.get('title', 'Unknown'))} "
                f"- {code(str(grp.get('chat_id', 0)))}"
            )

        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_chats",
            item_cb_prefix="stats_chat_item",
        )

    @classmethod
    async def chat_detail(cls, page: int, idx: int) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a connected group."""
        groups = await db.groups_db.active_groups()
        chunk, _total, page = paginate(groups, page, _PAGE_SIZE)
        if idx < 0 or idx >= len(chunk):
            text = "Group not found in this page."
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back", callback_data=f"stats_chats:{page}")]]
            )
            return text, kb

        grp = chunk[idx]
        chat_id = grp.get("chat_id", 0)
        title = grp.get("title", "Unknown")
        added_by = grp.get("added_by", 0)
        adder_fname, adder_uname = await db.users_cache.get_user_mention_data(added_by)
        date_str = date_or_unknown(grp.get("added_date"))

        text = (
            f"{bold('Group Details')}\n\n"
            f"Name: {bold(esc(title))}\n"
            f"Chat ID: {code(str(chat_id))}\n\n"
            f"Connected by: {mention(added_by, adder_fname, adder_uname)}\n"
            f"Date: {date_str}"
        )
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("« Back", callback_data=f"stats_chats:{page}")]]
        )
        return text, kb

    # ── Bans drill-down ──────────────────────────────────────────────────

    @classmethod
    async def bans_list(cls, page: int) -> tuple[str, InlineKeyboardMarkup]:
        """Paginated list of every active federation ban."""

        bans = await db.bans_db.active_bans()
        chunk, total_pages, page = paginate(bans, page, _PAGE_SIZE)

        if not bans:
            text = f"{bold('User Bans')}\n\nNo active federation bans."
            return text, back_kb()

        # * Pre-resolve banned-user names with batch query
        uids = [b.get("banned_user_id", 0) for b in chunk]
        fname_map = await db.users_cache.get_first_names_batch(uids) if uids else {}

        lines = [
            f"{bold('User Bans')} - {len(bans)} total  "
            f"·  page {page + 1}/{total_pages}\n"
        ]
        base_idx = page * _PAGE_SIZE
        for i, ban in enumerate(chunk, start=1):
            uid = ban.get("banned_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            lines.append(f"{base_idx + i}. {esc(fname)} - {code(str(uid))}")

        search_row = [
            InlineKeyboardButton("Search", callback_data="stats_bans_search"),
        ]
        return "\n".join(lines), _list_kb(
            page,
            total_pages,
            len(chunk),
            cb_prefix="stats_bans",
            item_cb_prefix="stats_ban_item",
            extra_row=search_row,
        )

    @classmethod
    async def ban_detail(cls, page: int, idx: int) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a banned user, reusing ``build_ban_detail``."""
        bans = await db.bans_db.active_bans()
        chunk, _total, page = paginate(bans, page, _PAGE_SIZE)
        if idx < 0 or idx >= len(chunk):
            text = "Ban record not found in this page."
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back", callback_data=f"stats_bans:{page}")]]
            )
            return text, kb
        ban = chunk[idx]
        text, proof_link = await build_ban_detail(ban)
        rows: list[list[InlineKeyboardButton]] = []
        if proof_link:
            rows.append([InlineKeyboardButton("View Proof", url=proof_link)])
        rows.append(
            [InlineKeyboardButton("« Back", callback_data=f"stats_bans:{page}")]
        )
        return text, InlineKeyboardMarkup(rows)

    # ── Search panel ─────────────────────────────────────────────────────

    @staticmethod
    def _search_panel_kb() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Cancel", callback_data="stats_search_cancel")]]
        )

    @staticmethod
    def _search_results_kb(n: int) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        num_btns = [
            InlineKeyboardButton(str(i + 1), callback_data=f"stats_search_item:{i}")
            for i in range(n)
        ]
        for i in range(0, len(num_btns), 3):
            rows.append(num_btns[i : i + 3])
        rows.append(
            [InlineKeyboardButton("New Search", callback_data="stats_bans_search")]
        )
        rows.append(
            [InlineKeyboardButton("Cancel", callback_data="stats_search_cancel")]
        )
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _search_detail_kb(proof_link: str | None = None) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if proof_link:
            rows.append([InlineKeyboardButton("View Proof", url=proof_link)])
        rows.append([InlineKeyboardButton("« Back", callback_data="stats_search_back")])
        return InlineKeyboardMarkup(rows)

    @classmethod
    def open_search(
        cls, ctx: ContextTypes.DEFAULT_TYPE, q
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Open the search prompt; remember chat/message so input edits the right card."""
        ctx.user_data[SEARCH_KEY] = True
        ctx.user_data[MSG_KEY] = q.message.message_id
        ctx.user_data[CHAT_KEY] = q.message.chat_id
        text = f"{bold('Search User Bans')}\n\nSend a name or user ID in the chat."
        return text, cls._search_panel_kb()

    @staticmethod
    def clear_search(ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Forget any in-flight search context."""
        for key in (SEARCH_KEY, RESULTS_KEY, MSG_KEY, CHAT_KEY):
            ctx.user_data.pop(key, None)

    @classmethod
    async def search_run(
        cls,
        query: str,
    ) -> list[dict]:
        """Resolve a search query against the active-ban list (ID or name match)."""
        q = query.strip()
        if q.isdigit():
            ban = await db.bans_db.get_active_ban(int(q))
            return [ban] if ban else []

        bans = await db.bans_db.active_bans()
        if not bans:
            return []

        # Batch query for all user names
        uids = [b.get("banned_user_id", 0) for b in bans]
        fname_map = await db.users_cache.get_first_names_batch(uids)
        needle = q.lower()
        return [
            b
            for b in bans
            if needle in fname_map.get(b.get("banned_user_id", 0), "").lower()
        ]

    @classmethod
    async def search_results(
        cls,
        query: str,
        results: list[dict],
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Render search results: empty state or numbered hits."""
        if not results:
            text = f'{bold("Search:")} "{esc(query)}"\n\nNo results found.'
            return text, cls._search_results_kb(0)

        # Batch query for all user names
        uids = [b.get("banned_user_id", 0) for b in results]
        fname_map = await db.users_cache.get_first_names_batch(uids)
        lines = [f'{bold("Search:")} "{esc(query)}" ({len(results)} found)\n']
        for i, ban in enumerate(results, start=1):
            uid = ban.get("banned_user_id", 0)
            fname = fname_map.get(uid, str(uid))
            lines.append(f"{i}. {esc(fname)} - {code(str(uid))}")
        return "\n".join(lines), cls._search_results_kb(len(results))

    @classmethod
    async def search_detail(
        cls, results: list[dict], idx: int
    ) -> tuple[str, InlineKeyboardMarkup]:
        """Detail card for a single search hit."""
        if idx < 0 or idx >= len(results):
            text = "Result no longer available."
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back", callback_data="stats_search_back")]]
            )
            return text, kb
        text, proof_link = await build_ban_detail(results[idx])
        return text, cls._search_detail_kb(proof_link)


ROLE_LABEL = db.users_roles.ROLE_LABEL

__all__ = ("Stats", "ROLE_LABEL", "SEARCH_KEY", "RESULTS_KEY", "MSG_KEY", "CHAT_KEY")
