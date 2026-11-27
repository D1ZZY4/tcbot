# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Community menu links: username, invite fallback, omission, and caching."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pyrogram import Client

from tcbot.modules.helper.rich import link as community_links


@pytest.fixture(autouse=True)
def _clear_link_cache() -> Any:
    community_links.clear()
    yield
    community_links.clear()


def _bot(chat: Any, *, fail: bool = False, invite: str | None = None) -> Client:
    calls: list[int] = []
    exports: list[int] = []

    async def _get_chat(chat_id: int) -> Any:
        calls.append(chat_id)
        if fail:
            raise RuntimeError("lookup down")
        return chat

    async def _export(chat_id: int) -> str:
        exports.append(chat_id)
        if invite is None:
            raise RuntimeError("export refused")
        return invite

    result = SimpleNamespace(get_chat=_get_chat, export_chat_invite_link=_export)
    result.calls = calls  # type: ignore[attr-defined]
    result.exports = exports  # type: ignore[attr-defined]
    return cast("Client", result)


def test_username_becomes_the_public_link() -> None:
    bot = _bot(SimpleNamespace(username="tcf_chat", invite_link=None))

    assert asyncio.run(community_links.resolve(cast("Any", bot), -100)) == (
        "https://t.me/tcf_chat"
    )


def test_invite_link_is_the_fallback_for_private_chats() -> None:
    bot = _bot(SimpleNamespace(username=None, invite_link="https://t.me/+abc"))

    assert asyncio.run(community_links.resolve(cast("Any", bot), -200)) == (
        "https://t.me/+abc"
    )


def test_a_chat_without_a_public_link_is_omitted() -> None:
    bot = _bot(SimpleNamespace(username=None, invite_link=None))

    assert asyncio.run(community_links.resolve(cast("Any", bot), -300)) is None


def test_a_failed_lookup_omits_the_button_without_raising() -> None:
    bot = _bot(None, fail=True)

    assert asyncio.run(community_links.resolve(cast("Any", bot), -400)) is None


def test_a_private_chat_gets_the_bots_own_invite_link() -> None:
    """A bot cannot use another admin's link, so it generates its own."""
    bot = _bot(
        SimpleNamespace(username=None, invite_link=None),
        invite="https://t.me/+generated",
    )

    assert asyncio.run(community_links.resolve(cast("Any", bot), -800)) == (
        "https://t.me/+generated"
    )
    assert bot.exports == [-800]  # type: ignore[attr-defined]


def test_an_exported_invite_link_is_cached_without_repeat_export() -> None:
    bot = _bot(
        SimpleNamespace(username=None, invite_link=None),
        invite="https://t.me/+generated",
    )

    asyncio.run(community_links.resolve(cast("Any", bot), -900))
    asyncio.run(community_links.resolve(cast("Any", bot), -900))

    assert bot.exports == [-900]  # type: ignore[attr-defined]


def test_a_refused_invite_export_still_omits_the_button() -> None:
    bot = _bot(SimpleNamespace(username=None, invite_link=None))

    assert asyncio.run(community_links.resolve(cast("Any", bot), -1000)) is None
    assert bot.exports == [-1000]  # type: ignore[attr-defined]


def test_a_cached_link_skips_the_second_telegram_lookup() -> None:
    bot = _bot(SimpleNamespace(username="tcf", invite_link=None))

    assert asyncio.run(community_links.resolve(cast("Any", bot), -500)) is not None
    assert asyncio.run(community_links.resolve(cast("Any", bot), -500)) is not None
    assert bot.calls == [-500]  # type: ignore[attr-defined]


def test_forget_drops_one_cached_link() -> None:
    bot = _bot(SimpleNamespace(username="tcf", invite_link=None))

    asyncio.run(community_links.resolve(cast("Any", bot), -600))
    community_links.forget(-600)
    asyncio.run(community_links.resolve(cast("Any", bot), -600))

    assert bot.calls == [-600, -600]  # type: ignore[attr-defined]


def test_zero_chat_id_never_calls_telegram() -> None:
    bot = _bot(SimpleNamespace(username="tcf", invite_link=None))

    assert asyncio.run(community_links.resolve(cast("Any", bot), 0)) is None
    assert bot.calls == []  # type: ignore[attr-defined]


def test_display_falls_back_to_the_numeric_id() -> None:
    bot = _bot(SimpleNamespace(username=None, invite_link=None))

    assert asyncio.run(community_links.display(cast("Any", bot), -700)) == "-700"
