# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.extraction — ResolvedTarget, _best_name, extract_target."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from telegram import Bot, Update

from tcbot.modules.helper import extraction
from tcbot.modules.helper.extraction import ResolvedTarget, _best_name, extract_target

# ─────────────────────── Update builders ─────────────────────── #


def _make_update(
    *,
    reply_user=None,
    entities=None,
    text: str = "",
) -> Update:
    """Build a minimal Update/Message stub for extract_target tests."""
    reply_msg = (
        SimpleNamespace(from_user=reply_user) if reply_user is not None else None
    )
    msg = SimpleNamespace(
        reply_to_message=reply_msg,
        entities=entities or [],
        text=text,
    )
    return cast(Update, SimpleNamespace(effective_message=msg))


def _user(uid: int, fname: str, username: str | None = None):
    return SimpleNamespace(id=uid, first_name=fname, username=username)


class TestResolvedTarget:
    def test_stores_id_and_name(self):
        t = ResolvedTarget(id=42, first_name="Alice")
        assert t.id == 42
        assert t.first_name == "Alice"

    def test_username_defaults_to_none(self):
        t = ResolvedTarget(id=42, first_name="Alice")
        assert t.username is None

    def test_stores_username(self):
        t = ResolvedTarget(id=42, first_name="Alice", username="alice")
        assert t.username == "alice"

    def test_none_first_name_becomes_str_id(self):
        t = ResolvedTarget(id=42, first_name=None)
        assert t.first_name == "42"

    def test_empty_first_name_becomes_str_id(self):
        t = ResolvedTarget(id=99, first_name="")
        assert t.first_name == "99"

    def test_valid_first_name_kept(self):
        t = ResolvedTarget(id=1, first_name="Bob")
        assert t.first_name == "Bob"

    def test_raw_field_ignored_in_comparison(self):
        t1 = ResolvedTarget(id=1, first_name="A", raw=object())
        t2 = ResolvedTarget(id=1, first_name="A", raw=object())
        assert t1 == t2

    def test_raw_not_shown_in_repr(self):
        t = ResolvedTarget(id=1, first_name="A", raw=object())
        assert "raw" not in repr(t)


def _async_get_first_name(return_value: str):
    async def _impl(uid, default=""):
        return return_value

    return _impl


class TestBestName:
    async def test_returns_first_non_empty_primary(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name(""),
        )
        result = await _best_name(42, "Alice", "Bob")
        assert result == "Alice"

    async def test_skips_none_primaries(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("Cached"),
        )
        result = await _best_name(42, None, None)
        assert result == "Cached"

    async def test_skips_empty_primaries(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("CachedName"),
        )
        result = await _best_name(42, "", "")
        assert result == "CachedName"

    async def test_falls_back_to_user_id_string(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name(""),
        )
        result = await _best_name(42)
        assert result == "User 42"

    async def test_skips_digit_only_primaries(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("RealName"),
        )
        result = await _best_name(42, "123456", None)
        assert result == "RealName"

    async def test_accepts_numeric_id_as_fallback_label(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name(""),
        )
        result = await _best_name(77777)
        assert result == "User 77777"

    async def test_cached_name_with_only_digits_also_skipped(self, monkeypatch):
        monkeypatch.setattr(
            "tcbot.modules.helper.extraction.db.users_cache.get_first_name",
            _async_get_first_name("99999"),
        )
        result = await _best_name(99)
        assert result == "User 99"


# ──────────────────── extract_target: Priority 1 — Reply ─────────────────────── #


class TestExtractTargetReply:
    async def test_reply_with_first_name_resolves_directly(self) -> None:
        """Priority 1: reply-to user with a first_name is returned as-is."""
        update = _make_update(reply_user=_user(42, "Alice"))

        uid, fname = await extract_target(update, [])

        assert uid == 42
        assert fname == "Alice"

    async def test_reply_empty_first_name_falls_back_to_cache(
        self, monkeypatch
    ) -> None:
        """Priority 1: reply-to user with no first_name looks up the cache."""
        update = _make_update(reply_user=_user(99, ""))
        monkeypatch.setattr(
            extraction.db.users_cache,
            "get_first_name",
            AsyncMock(return_value="CachedName"),
        )

        uid, fname = await extract_target(update, [])

        assert uid == 99
        assert fname == "CachedName"

    async def test_reply_no_first_name_no_cache_falls_back_to_user_uid(
        self, monkeypatch
    ) -> None:
        """Priority 1: reply-to user with no cache entry uses 'User <uid>'."""
        update = _make_update(reply_user=_user(77, ""))
        monkeypatch.setattr(
            extraction.db.users_cache,
            "get_first_name",
            AsyncMock(return_value=""),
        )

        uid, fname = await extract_target(update, [])

        assert uid == 77
        assert fname == "User 77"


# ──────────────────── extract_target: Priority 2a — Numeric ID arg ─────────────────────── #


class TestExtractTargetNumericArg:
    async def test_numeric_arg_with_bot_resolves_name(self, monkeypatch) -> None:
        """Priority 2a: numeric ID uses _safe_get_chat to fetch the display name."""
        update = _make_update()
        chat = SimpleNamespace(id=100, first_name="Bob", username="bob")
        bot = cast(Bot, SimpleNamespace(id=1))
        monkeypatch.setattr(extraction, "_safe_get_chat", AsyncMock(return_value=chat))

        uid, fname = await extract_target(update, ["100"], bot)

        assert uid == 100
        assert fname == "Bob"

    async def test_numeric_arg_without_bot_uses_cache(self, monkeypatch) -> None:
        """Priority 2a: numeric ID without bot falls back to the member cache."""
        update = _make_update()
        monkeypatch.setattr(
            extraction.db.users_cache,
            "get_first_name",
            AsyncMock(return_value="CachedBob"),
        )

        uid, fname = await extract_target(update, ["200"])

        assert uid == 200
        assert fname == "CachedBob"

    async def test_numeric_arg_no_bot_no_cache_fallback(self, monkeypatch) -> None:
        """Priority 2a: numeric ID with empty cache falls back to 'User <uid>'."""
        update = _make_update()
        monkeypatch.setattr(
            extraction.db.users_cache,
            "get_first_name",
            AsyncMock(return_value=""),
        )

        uid, fname = await extract_target(update, ["333"])

        assert uid == 333
        assert fname == "User 333"

    async def test_numeric_arg_bot_get_chat_fails_uses_cache(self, monkeypatch) -> None:
        """Priority 2a: when _safe_get_chat returns None, fall back to cache name."""
        update = _make_update()
        bot = cast(Bot, SimpleNamespace(id=1))
        monkeypatch.setattr(extraction, "_safe_get_chat", AsyncMock(return_value=None))
        monkeypatch.setattr(
            extraction.db.users_cache,
            "get_first_name",
            AsyncMock(return_value="FallbackName"),
        )

        uid, fname = await extract_target(update, ["404"], bot)

        assert uid == 404
        assert fname == "FallbackName"


# ──────────────────── extract_target: Priority 2b — @username arg ─────────────────────── #


class TestExtractTargetUsernameArg:
    async def test_username_arg_resolved_via_bot(self, monkeypatch) -> None:
        """Priority 2b: @username argument resolved via _safe_get_chat."""
        update = _make_update()
        chat = SimpleNamespace(id=55, first_name="Carol", username="carol")
        bot = cast(Bot, SimpleNamespace(id=1))
        monkeypatch.setattr(extraction, "_safe_get_chat", AsyncMock(return_value=chat))

        uid, fname = await extract_target(update, ["carol"], bot)

        assert uid == 55
        assert fname == "Carol"

    async def test_username_arg_not_found_falls_to_partial_search(
        self, monkeypatch
    ) -> None:
        """Priority 2b → 3: username not found via Telegram, found via partial search."""
        update = _make_update()
        bot = cast(Bot, SimpleNamespace(id=1))
        monkeypatch.setattr(extraction, "_safe_get_chat", AsyncMock(return_value=None))
        monkeypatch.setattr(
            extraction.db.users_cache,
            "all_users",
            AsyncMock(
                return_value=[
                    {"user_id": 77, "first_name": "carol", "username": "carol"}
                ]
            ),
        )

        uid, fname = await extract_target(update, ["carol"], bot)

        assert uid == 77
        assert fname == "carol"


# ──────────────────── extract_target: Priority 3 — Partial name search ─────────────────────── #


class TestExtractTargetPartialName:
    async def test_partial_name_match_first_result_returned(self, monkeypatch) -> None:
        """Priority 3: partial name search returns the first cache match."""
        update = _make_update()
        users = [
            {"user_id": 10, "first_name": "Dave", "username": None},
            {"user_id": 11, "first_name": "Dave King", "username": None},
        ]
        monkeypatch.setattr(
            extraction.db.users_cache, "all_users", AsyncMock(return_value=users)
        )

        uid, fname = await extract_target(update, ["dave"])

        assert uid == 10
        assert fname == "Dave"

    async def test_partial_username_match(self, monkeypatch) -> None:
        """Priority 3: partial search also matches on username field."""
        update = _make_update()
        users = [{"user_id": 20, "first_name": "Elena", "username": "elenadev"}]
        monkeypatch.setattr(
            extraction.db.users_cache, "all_users", AsyncMock(return_value=users)
        )

        uid, fname = await extract_target(update, ["elenadev"])

        assert uid == 20
        assert fname == "Elena"

    async def test_partial_no_match_returns_none(self, monkeypatch) -> None:
        """Priority 3: no cache match continues to entities; with none present returns None."""
        update = _make_update()
        monkeypatch.setattr(
            extraction.db.users_cache, "all_users", AsyncMock(return_value=[])
        )

        uid, fname = await extract_target(update, ["zzznobody"])

        assert uid is None
        assert fname is None


# ──────────────────── extract_target: Priority 4 — text_mention entity ─────────────────────── #


class TestExtractTargetTextMention:
    async def test_text_mention_entity_resolved(self) -> None:
        """Priority 4: text_mention entity with a User object resolves directly."""
        user = _user(500, "Eve")
        entity = SimpleNamespace(type="text_mention", user=user)
        update = _make_update(entities=[entity])

        uid, fname = await extract_target(update, [])

        assert uid == 500
        assert fname == "Eve"

    async def test_text_mention_empty_first_name_uses_best_name(
        self, monkeypatch
    ) -> None:
        """Priority 4: text_mention user with no first_name falls back to cache."""
        user = _user(501, "")
        entity = SimpleNamespace(type="text_mention", user=user)
        update = _make_update(entities=[entity])
        monkeypatch.setattr(
            extraction.db.users_cache,
            "get_first_name",
            AsyncMock(return_value="MentionedUser"),
        )

        uid, fname = await extract_target(update, [])

        assert uid == 501
        assert fname == "MentionedUser"


# ──────────────────── extract_target: Priority 5 — @mention entity ─────────────────────── #


class TestExtractTargetMentionEntity:
    async def test_mention_entity_resolved_via_bot(self, monkeypatch) -> None:
        """Priority 5: @mention entity uses _safe_get_chat to resolve the username."""
        entity = SimpleNamespace(type="mention", user=None, offset=0, length=5)
        update = _make_update(entities=[entity], text="@fitz")
        chat = SimpleNamespace(id=800, first_name="Fitz", username="fitz")
        bot = cast(Bot, SimpleNamespace(id=1))
        monkeypatch.setattr(extraction, "_safe_get_chat", AsyncMock(return_value=chat))

        uid, fname = await extract_target(update, [], bot)

        assert uid == 800
        assert fname == "Fitz"

    async def test_mention_entity_not_found_returns_none(self, monkeypatch) -> None:
        """Priority 5: mention entity with unresolvable username yields (None, None)."""
        entity = SimpleNamespace(type="mention", user=None, offset=0, length=8)
        update = _make_update(entities=[entity], text="@unknown")
        bot = cast(Bot, SimpleNamespace(id=1))
        monkeypatch.setattr(extraction, "_safe_get_chat", AsyncMock(return_value=None))

        uid, fname = await extract_target(update, [], bot)

        assert uid is None
        assert fname is None


# ──────────────────── extract_target: No target ─────────────────────── #


class TestExtractTargetNoSignal:
    async def test_no_reply_no_args_no_entities_returns_none(self) -> None:
        """When no signal is present, extract_target returns (None, None)."""
        update = _make_update()

        uid, fname = await extract_target(update, [])

        assert uid is None
        assert fname is None
