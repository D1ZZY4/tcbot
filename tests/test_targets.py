# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.extraction - ResolvedTarget, _best_name, _safe_get_chat, extract_target."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from tcbot.modules.helper import extraction
from tcbot.modules.helper.extraction import ResolvedTarget, _best_name, _safe_get_chat, extract_target


def test_resolved_target_sets_first_name_to_str_id_when_none() -> None:
    rt = ResolvedTarget(id=42, first_name=None, username=None)
    assert rt.first_name == "42"


def test_resolved_target_keeps_provided_first_name() -> None:
    rt = ResolvedTarget(id=7, first_name="Andi", username="andi")
    assert rt.first_name == "Andi"
    assert rt.username == "andi"


def test_resolved_target_raw_field_stored() -> None:
    raw = SimpleNamespace(label="user")
    rt = ResolvedTarget(id=7, first_name="Andi", raw=raw)
    assert rt.raw is raw


def test_resolved_target_default_raw_is_none() -> None:
    rt = ResolvedTarget(id=1, first_name="Bob")
    assert rt.raw is None


def test_resolved_target_zero_id_sets_first_name_to_zero_string() -> None:
    rt = ResolvedTarget(id=0, first_name=None)
    assert rt.first_name == "0"


def test_resolved_target_large_id_preserved() -> None:
    rt = ResolvedTarget(id=9999999999, first_name=None)
    assert rt.id == 9999999999
    assert rt.first_name == "9999999999"


def test_resolved_target_negative_id_preserved() -> None:
    rt = ResolvedTarget(id=-100001234, first_name="Group")
    assert rt.id == -100001234
    assert rt.first_name == "Group"


def test_resolved_target_username_none_by_default() -> None:
    rt = ResolvedTarget(id=5, first_name="Alice")
    assert rt.username is None


def test_resolved_target_empty_string_replaced_with_id() -> None:
    """Empty string is falsy, so __post_init__ replaces it with str(id)."""
    rt = ResolvedTarget(id=5, first_name="")
    assert rt.first_name == "5"


# ─────────────────────── _safe_get_chat ─────────────────────────── #


async def test_safe_get_chat_returns_chat_on_success() -> None:
    chat = SimpleNamespace(id=42, first_name="Target")
    bot = SimpleNamespace(get_chat=AsyncMock(return_value=chat))
    result = await _safe_get_chat(bot, 42)
    assert result is chat


async def test_safe_get_chat_returns_none_on_exception() -> None:
    bot = SimpleNamespace(get_chat=AsyncMock(side_effect=RuntimeError("forbidden")))
    result = await _safe_get_chat(bot, 42)
    assert result is None


# ─────────────────────── _best_name ─────────────────────────────── #


async def test_best_name_returns_first_non_empty_primary(monkeypatch) -> None:
    monkeypatch.setattr(extraction.db.users_cache, "get_first_name", AsyncMock())
    result = await _best_name(10, "Alice", None)
    assert result == "Alice"
    extraction.db.users_cache.get_first_name.assert_not_awaited()


async def test_best_name_skips_numeric_primary_and_uses_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        extraction.db.users_cache, "get_first_name", AsyncMock(return_value="Bob")
    )
    result = await _best_name(10, "999")
    assert result == "Bob"


async def test_best_name_falls_back_to_user_id_when_cache_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        extraction.db.users_cache, "get_first_name", AsyncMock(return_value="")
    )
    result = await _best_name(777)
    assert result == "User 777"


# ─────────────────────── extract_target ─────────────────────────── #


async def test_extract_target_reply_path(monkeypatch) -> None:
    """Priority 1: reply_to_message with from_user."""
    replied_user = SimpleNamespace(id=99, first_name="Replied")
    msg = SimpleNamespace(
        reply_to_message=SimpleNamespace(from_user=replied_user),
        entities=None,
        text=None,
    )
    update = SimpleNamespace(effective_message=msg)
    uid, name = await extract_target(update, [])
    assert uid == 99
    assert name == "Replied"


async def test_extract_target_numeric_arg_with_chat(monkeypatch) -> None:
    """Priority 2a: numeric ID in args with successful get_chat."""
    monkeypatch.setattr(
        extraction, "_safe_get_chat",
        AsyncMock(return_value=SimpleNamespace(first_name="Carol", username="carol"))
    )
    monkeypatch.setattr(
        extraction.db.users_cache, "get_first_name", AsyncMock(return_value="")
    )
    msg = SimpleNamespace(reply_to_message=None, entities=None, text=None)
    update = SimpleNamespace(effective_message=msg)
    bot = SimpleNamespace()

    uid, name = await extract_target(update, ["55"], bot=bot)
    assert uid == 55
    assert name == "Carol"


async def test_extract_target_text_mention_entity(monkeypatch) -> None:
    """Priority 4: text_mention entity in message entities."""
    monkeypatch.setattr(
        extraction.db.users_cache, "get_first_name", AsyncMock(return_value="")
    )
    user_ent = SimpleNamespace(id=200, first_name="Mentioned")
    ent = SimpleNamespace(type="text_mention", user=user_ent)
    msg = SimpleNamespace(
        reply_to_message=None,
        entities=[ent],
        text="some text",
    )
    update = SimpleNamespace(effective_message=msg)
    uid, name = await extract_target(update, [])
    assert uid == 200
    assert name == "Mentioned"


async def test_extract_target_no_match_returns_none_none(monkeypatch) -> None:
    """All priorities exhausted: returns (None, None)."""
    msg = SimpleNamespace(
        reply_to_message=None,
        entities=[],
        text="no mention here",
    )
    update = SimpleNamespace(effective_message=msg)
    uid, name = await extract_target(update, [])
    assert uid is None
    assert name is None
