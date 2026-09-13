# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Target resolution priority matrix, exercised with fakes (no I/O)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from tcbot import database as db
from tcbot.modules.helper import extraction as ex


def _user(uid: int, first_name: str = "Name") -> Any:
    """Duck-typed stand-in for ``telegram.User``."""
    return SimpleNamespace(id=uid, first_name=first_name)


def _msg(**kwargs: Any) -> Any:
    """Duck-typed stand-in for ``telegram.Message`` with safe defaults."""
    base: dict[str, Any] = {
        "reply_to_message": None,
        "entities": [],
        "text": "/tcb",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _update(msg: Any) -> Any:
    """Duck-typed stand-in for ``telegram.Update`` (``Any`` keeps fakes quiet)."""
    return SimpleNamespace(effective_message=msg)


def _run(coro: Any) -> Any:
    """Drive one coroutine to completion without a pytest async plugin."""
    return asyncio.run(coro)


class _FakeBot:
    """Counts live lookups; resolves only explicitly registered names/IDs."""

    def __init__(self) -> None:
        self.calls: list[str | int] = []
        self.chats: dict[str | int, Any] = {}

    async def get_chat(self, ident: str | int) -> Any:
        self.calls.append(ident)
        if ident in self.chats:
            return self.chats[ident]
        raise ValueError(f"unknown {ident}")


def _alive_user(uid: int, name: str) -> Any:
    """Duck-typed ``get_chat`` hit shaped like a private user chat."""
    return SimpleNamespace(id=uid, first_name=name, username=None, type="private")


def _stub_cache(
    monkeypatch, first: str = "", found: list | None = None, names: dict | None = None
) -> None:  # type: ignore[no-untyped-def]
    """Stub member-cache reads so no MongoDB round trip can happen."""

    async def _first_name(uid: int, fallback: str = "") -> str:
        if names is not None:
            return names.get(uid, fallback)
        return first or fallback

    async def _search(needle: str, limit: int = 5) -> list:
        items = found if found is not None else []
        return [
            m for m in items if needle.lower() in str(m.get("first_name", "")).lower()
        ]

    monkeypatch.setattr(db.users_cache, "get_first_name", _first_name)
    monkeypatch.setattr(db.users_cache, "search_by_name", _search)


def _reply_from(uid: int, name: str = "Reply") -> Any:
    """Message quoting a user message (reply target ``uid``)."""
    reply = _msg()
    reply.reply_to_message = SimpleNamespace(
        from_user=_user(uid, name), sender_chat=None
    )
    return reply


def test_reply_user_wins_without_io(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    reply = _msg()
    reply.reply_to_message = SimpleNamespace(
        from_user=_user(11, "Reply"), sender_chat=None
    )
    assert _run(ex.extract_target(_update(reply), [], cast("Any", bot))) == (
        11,
        "Reply",
    )
    assert bot.calls == []


def test_anonymous_reply_falls_through_to_args(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    bot.chats[22] = _alive_user(22, "Live")
    reply = _msg()
    reply.reply_to_message = SimpleNamespace(
        from_user=_user(1087968824, "Group"), sender_chat=None
    )
    assert _run(ex.extract_target(_update(reply), ["22"], cast("Any", bot))) == (
        22,
        "Live",
    )


def test_telegram_account_reply_falls_through(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    reply = _msg()
    reply.reply_to_message = SimpleNamespace(
        from_user=_user(777000, "Telegram"), sender_chat=None
    )
    assert _run(ex.extract_target(_update(reply), [], None)) == (None, None)


def test_numeric_id_uses_cache_without_live_lookup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch, first="Cached")
    bot = _FakeBot()
    assert _run(ex.extract_target(_update(_msg()), ["42"], cast("Any", bot))) == (
        42,
        "Cached",
    )
    assert bot.calls == []


def test_numeric_id_falls_back_to_live_lookup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    bot.chats[42] = _alive_user(42, "Live")
    assert _run(ex.extract_target(_update(_msg()), ["42"], cast("Any", bot))) == (
        42,
        "Live",
    )
    assert bot.calls == [42]


def test_username_resolves_live(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    bot.chats["@someone"] = _alive_user(77, "Some")
    assert _run(ex.extract_target(_update(_msg()), ["@someone"], cast("Any", bot))) == (
        77,
        "Some",
    )


def test_partial_name_needs_prefer_explicit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Fuzzy matching is read-only only: moderation paths never guess."""
    _stub_cache(monkeypatch, found=[{"user_id": 55, "first_name": "Daniel"}])
    assert _run(ex.extract_target(_update(_msg()), ["dan"], None)) == (None, None)
    assert _run(
        ex.extract_target(_update(_msg()), ["dan"], None, prefer_explicit=True)
    ) == (55, "Daniel")


def test_text_mention_entity_wins(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    ent = SimpleNamespace(type="text_mention", user=_user(66, "Mentioned"))
    msg = _msg(entities=[ent])
    assert _run(ex.extract_target(_update(msg), [], None)) == (66, "Mentioned")


def test_at_mention_entity_resolves_live(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    bot.chats["@dude"] = _alive_user(99, "Dude")
    ent = SimpleNamespace(type="mention", offset=0, length=5)
    msg = _msg(text="@dude hi", entities=[ent])
    assert _run(ex.extract_target(_update(msg), [], cast("Any", bot))) == (99, "Dude")


def test_no_match_returns_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    assert _run(ex.extract_target(_update(_msg()), [], None)) == (None, None)
    assert _run(ex.extract_target(_update(None), [], None)) == (None, None)


def test_reply_plus_verified_numeric_overrides(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A typed ID naming a known user beats the quoted sender."""
    _stub_cache(monkeypatch, names={22: "Twentytwo"})
    bot = _FakeBot()
    assert _run(
        ex.extract_target(_update(_reply_from(11)), ["22"], cast("Any", bot))
    ) == (22, "Twentytwo")
    assert bot.calls == []


def test_reply_plus_unverified_numeric_keeps_reply(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An unknown ID (reason text starting with a number) keeps the reply."""
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    assert _run(
        ex.extract_target(_update(_reply_from(11)), ["22"], cast("Any", bot))
    ) == (11, "Reply")
    assert bot.calls == [22]


def test_reply_plus_restated_id_keeps_reply(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Restating the quoted user's ID changes nothing."""
    _stub_cache(monkeypatch, names={11: "Eleven"})
    bot = _FakeBot()
    assert _run(
        ex.extract_target(_update(_reply_from(11)), ["11"], cast("Any", bot))
    ) == (11, "Reply")


def test_reply_plus_verified_username_overrides(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    bot.chats["@dude"] = _alive_user(99, "Dude")
    assert _run(
        ex.extract_target(_update(_reply_from(11)), ["@dude"], cast("Any", bot))
    ) == (99, "Dude")


def test_reply_plus_group_chat_never_overrides(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A numeric ID resolving to a group (title, no first_name) keeps reply."""
    _stub_cache(monkeypatch)
    bot = _FakeBot()
    bot.chats[22] = SimpleNamespace(id=22, first_name=None, username=None, type="group")
    assert _run(
        ex.extract_target(_update(_reply_from(11)), ["22"], cast("Any", bot))
    ) == (11, "Reply")


def test_reply_plus_partial_name_keeps_reply_by_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Fuzzy names never override a quote on moderation paths."""
    _stub_cache(monkeypatch, found=[{"user_id": 55, "first_name": "Daniel"}])
    assert _run(ex.extract_target(_update(_reply_from(11)), ["dan"], None)) == (
        11,
        "Reply",
    )


def test_prefer_explicit_wins_for_read_only_views(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """/check shows who was typed, even fuzzy; falls back to reply on miss."""
    _stub_cache(monkeypatch, found=[{"user_id": 55, "first_name": "Daniel"}])
    assert _run(
        ex.extract_target(_update(_reply_from(11)), ["dan"], None, prefer_explicit=True)
    ) == (55, "Daniel")
    assert _run(
        ex.extract_target(
            _update(_reply_from(11)), ["nobody"], None, prefer_explicit=True
        )
    ) == (11, "Reply")


def test_mod_target_consumed_matrix(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """extract_mod_target reports whether args[0] named the target."""
    _stub_cache(monkeypatch, names={22: "Twentytwo", 42: "Cached"})
    bot = _FakeBot()
    assert _run(ex.extract_mod_target(_update(_msg()), ["42"], cast("Any", bot))) == (
        (42, "Cached"),
        True,
    )
    assert _run(
        ex.extract_mod_target(_update(_reply_from(11)), ["22"], cast("Any", bot))
    ) == ((22, "Twentytwo"), True)
    assert _run(
        ex.extract_mod_target(_update(_reply_from(11)), ["11"], cast("Any", bot))
    ) == ((11, "Reply"), False)
    assert _run(ex.extract_mod_target(_update(_reply_from(11)), [], None)) == (
        (11, "Reply"),
        False,
    )
    assert _run(ex.extract_mod_target(_update(None), [], None)) == (
        (None, None),
        False,
    )
