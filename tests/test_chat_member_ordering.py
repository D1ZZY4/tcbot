# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Chat-member handlers must not consume each other's updates."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram import ContinuePropagation
from pyrogram.enums import ChatMemberStatus

from tcbot.modules import greeting


class _Bot:
    """Bot double with a cached identity."""

    me = SimpleNamespace(id=555, first_name="Bot", username="testbot")


def _ctx(subject_id: int, *, bot: bool) -> Any:
    return SimpleNamespace(
        bot=_Bot(),
        effective_user=None,
        effective_chat=None,
        effective_message=None,
        chat_member=SimpleNamespace(
            via_join_request=False,
            new_chat_member=SimpleNamespace(
                status=ChatMemberStatus.MEMBER,
                user=SimpleNamespace(id=subject_id, is_bot=bot),
            ),
            chat=SimpleNamespace(id=-100, type="supergroup"),
        ),
    )


def test_a_bot_subject_update_is_passed_to_the_connect_handler() -> None:
    """Kurigram routes both member events to one handler class.

    The greeting handler must propagate updates about the bot itself so
    approved-join enforcement does not depend on module registration order.
    """
    with pytest.raises(ContinuePropagation):
        asyncio.run(greeting.on_join_request_approved(_ctx(555, bot=True)))


def test_a_human_subject_update_is_consumed() -> None:
    """A human update without a join request is not passed on."""
    assert asyncio.run(greeting.on_join_request_approved(_ctx(42, bot=False))) is None
