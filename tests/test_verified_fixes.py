# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression coverage for the verified-audit fix batch."""

from __future__ import annotations

import asyncio

from tcbot import database as db
from tcbot.modules import help as helpmod
from tcbot.modules.helper import keyboards, replies
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
