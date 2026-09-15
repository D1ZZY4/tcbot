# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression coverage for the verified-audit fix batch."""

from __future__ import annotations

import asyncio

from tcbot import database as db
from tcbot.database.types import GroupId
from tcbot.modules import help as helpmod
from tcbot.modules.help import _help_index_text, _module_text
from tcbot.modules.helper import decorators, keyboards, replies
from tcbot.modules.helper.ban_info import build_ban_detail
from tcbot.modules.helper.workflows import check_flow, stats_flow
from tcbot.modules.helper.workflows.connected_flow import BuildConnection
from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow import BuildReason
from tcbot.utils.formatter import esc
from tcbot.utils.pagination import nav_row


def test_nav_row_labels_follow_locale() -> None:
    row_en = nav_row(1, 3, "cb", "en-US")
    assert [(b.text, b.callback_data) for b in row_en] == [
        ("« Prev", "cb:0"),
        ("Next »", "cb:2"),
    ]
    row_id = nav_row(1, 3, "cb", "id")
    assert [(b.text, b.callback_data) for b in row_id] == [
        ("« Sblm", "cb:0"),
        ("Lanjut »", "cb:2"),
    ]


def test_refusal_texts_match_legacy_english() -> None:
    assert (
        replies.refuse_owner_only("en-US", plain=True)
        == "This command is reserved for the Founder - you're not authorized."
    )
    assert (
        replies.refuse_mod_only("en-US", plain=True)
        == "You need Developer rank or above for this - not your call."
    )
    assert (
        replies.refuse_role_lookup("en-US", plain=True)
        == "I couldn't verify federation roles right now. Please try again in a moment."
    )
    assert "Admin" in replies.refuse_outranked("Admin", "en-US", plain=True)


def test_refusal_texts_localize() -> None:
    assert replies.refuse_owner_only("id", plain=True) != replies.refuse_owner_only(
        "en-US", plain=True
    )
    assert replies.refuse_mod_only("id", plain=True) != replies.refuse_mod_only(
        "en-US", plain=True
    )


def test_flow_keyboards_delegate_to_single_source() -> None:
    assert (
        BuildReason("ban").keyboard("en-US").to_dict()
        == keyboards.reason_step_kb("ban", locale="en-US").to_dict()
    )
    assert (
        BuildProof("mute", skip_allowed=False).keyboard("en-US").to_dict()
        == keyboards.proof_step_kb("mute", skip_allowed=False, locale="en-US").to_dict()
    )
    conn = BuildConnection("TCF")
    assert (
        conn.join_keyboard("en-US").to_dict()
        == keyboards.connect_join_kb(
            conn.join_callback, conn.cancel_callback, locale="en-US"
        ).to_dict()
    )
    assert check_flow._back_to_check(7, "en-US") == keyboards.check_back_row(7, "en-US")
    assert (
        stats_flow.main_kb(show_users=True, locale="en-US").to_dict()
        == keyboards.stats_main_kb(show_users=True, locale="en-US").to_dict()
    )
    assert (
        stats_flow.back_kb("en-US").to_dict()
        == keyboards.stats_back_kb("en-US").to_dict()
    )


def test_reason_step_keyboard_skip_toggle() -> None:
    full = keyboards.reason_step_kb("ban", locale="en-US")
    assert [b.callback_data for b in full.inline_keyboard[0]] == [
        "ban_skip_reason",
        "ban_cancel",
    ]
    noskip = keyboards.reason_step_kb("warn", skip_allowed=False, locale="en-US")
    assert [b.callback_data for b in noskip.inline_keyboard[0]] == ["warn_cancel"]


def test_check_profile_keyboard_callbacks() -> None:
    kb = keyboards.check_profile_kb(
        42,
        ban_total=1,
        appeal_total=2,
        fed_warn_total=3,
        kick_total=4,
        mute_total=5,
        locale="en-US",
    )
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert callbacks == [
        "check_bans:42:0",
        "check_appeals:42:0",
        "check_warns:42",
        "check_kicks:42:0",
        "check_mutes:42:0",
    ]


def test_language_list_back_label_localizes() -> None:
    kb = keyboards.language_list_kb(
        "user",
        [("English (US)", "en-US")],
        back_callback="back_to_start",
        locale="id",
    )
    assert kb.inline_keyboard[-1][0].text == "« Kembali"


def test_ban_detail_escapes_moderator_reason() -> None:
    async def _fake_mention(uid: int) -> tuple[str, str | None]:
        return ("Admin", None)

    async def run() -> tuple[str, str | None]:
        orig = db.users_cache.get_user_mention_data
        db.users_cache.get_user_mention_data = _fake_mention  # type: ignore[assignment]
        try:
            return await build_ban_detail(
                {
                    "banned_user_id": 11,
                    "admin_user_id": 22,
                    "reason": "spam_here *now* [x](y)",
                    "ban_id": "abc",
                },  # type: ignore[typeddict-item]
                target_fname="Target",
                locale="en-US",
            )
        finally:
            db.users_cache.get_user_mention_data = orig  # type: ignore[assignment]

    text, proof_link = asyncio.run(run())
    assert proof_link is None
    assert esc("spam_here *now* [x](y)") in text
    assert "*now*" not in text


def test_invalid_stored_role_grants_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def _not_owner(uid: int) -> bool:
        return False

    async def _not_admin(uid: int) -> bool:
        return False

    async def _bad_role(uid: int) -> str | None:
        return "admin"

    monkeypatch.setattr(db.users_roles, "is_owner", _not_owner)
    monkeypatch.setattr(db.users_roles, "is_admin", _not_admin)
    monkeypatch.setattr(db.users_roles, "get_role", _bad_role)

    uid = 42424241
    db.users_roles.effective_role_cache.invalidate(uid)
    try:
        assert asyncio.run(db.users_roles.get_effective_role(uid)) is None
    finally:
        db.users_roles.effective_role_cache.invalidate(uid)


def test_help_topics_rebuild_per_locale() -> None:
    menu_en = helpmod._topics_for_locale("en-US", menu=True)
    menu_id = helpmod._topics_for_locale("id", menu=True)
    cmd_en = helpmod._topics_for_locale("en-US", menu=False)
    assert menu_en and menu_id and cmd_en
    assert all(cb.startswith("help_") for _, cb in menu_en)
    assert all(cb.startswith("helpc_") for _, cb in cmd_en)
    # * Module display names stay English identifiers; the per-locale
    # * rebuild covers overviews and sections instead.
    content_en = helpmod._builder_help("en-US")
    content_id = helpmod._builder_help("id")
    assert content_en.keys() == content_id.keys()
    assert content_en["help_banning"][1] != content_id["help_banning"][1]
    assert helpmod._module_map_for_locale("id")


def test_stats_search_buttons_resolve_in_catalog() -> None:
    for locale in ("en-US", "id"):
        row = keyboards.stats_search_row(locale)
        assert row[0].text and not row[0].text.startswith("[")
        kb = keyboards.stats_search_results_kb(2, locale)
        labels = [b.text for r in kb.inline_keyboard for b in r]
        assert labels and all(not label.startswith("[") for label in labels)


def test_stats_search_results_carry_stable_ids() -> None:
    kb = keyboards.stats_search_results_kb(2, "en-US", item_ids=["banA", "banB"])
    assert kb.inline_keyboard[0][0].callback_data == "stats_search_item:0:banA"
    assert kb.inline_keyboard[0][1].callback_data == "stats_search_item:1:banB"
    legacy = keyboards.stats_search_results_kb(1, "en-US")
    assert legacy.inline_keyboard[0][0].callback_data == "stats_search_item:0"


def test_with_primary_groups_merges_missing_only() -> None:
    groups = db.groups_db.with_primary_groups(
        [
            {"chat_id": GroupId(1), "title": "A"},
            {"chat_id": GroupId(-100), "title": "P"},
        ],
        (-100, -200, 0),
        7,
    )
    assert [(g["chat_id"], g["title"]) for g in groups] == [
        (1, "A"),
        (-100, "P"),
        (-200, ""),
        (7, ""),
    ]


def test_help_titles_localize() -> None:
    assert "Bantuan" in _help_index_text("TCF", "id")
    assert "Help for" in _module_text("Ban", "Body.", "en-US")
    assert "Bantuan untuk" in _module_text("Ban", "Body.", "id")


def test_recheck_executor_rank() -> None:
    class _Chat:
        id = 11
        type = "supergroup"

    class _Msg:
        chat = _Chat()

        def __init__(self) -> None:
            self.replies: list[str] = []

        async def reply_text(self, text: str, **kwargs: object) -> object:
            self.replies.append(text)
            return object()

    async def _tester(uid: int) -> str | None:
        return "tester"

    async def _founder(uid: int) -> str | None:
        return "founder"

    async def run() -> tuple[bool, bool, int]:
        orig = db.users_roles.get_effective_role
        db.users_roles.get_effective_role = _tester  # type: ignore[assignment]
        try:
            denied = await decorators.recheck_executor_rank(
                _Msg(),  # type: ignore[arg-type]
                9,
                min_role="developer",
            )
        finally:
            db.users_roles.get_effective_role = orig  # type: ignore[assignment]
        msg = _Msg()
        db.users_roles.get_effective_role = _founder  # type: ignore[assignment]
        try:
            allowed = await decorators.recheck_executor_rank(
                msg,  # type: ignore[arg-type]
                9,
                min_role="developer",
            )
        finally:
            db.users_roles.get_effective_role = orig  # type: ignore[assignment]
        return denied, allowed, len(msg.replies)

    denied, allowed, _ = asyncio.run(run())
    assert denied is False
    assert allowed is True
