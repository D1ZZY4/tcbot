# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Conversation fallbacks must not swallow commands that have their own handler."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from pyrogram.handlers import MessageHandler

from tcbot.modules.helper.pipelines.appeal_submit import build_handler
from tcbot.modules.helper.pipelines.ban_conversation import ban_conversation
from tcbot.modules.helper.pipelines.mod_action_steps import (
    BuildReason,
    build_modaction_conv,
)
from tcbot.modules.helper.pipelines.proof_steps import BuildProof
from tcbot.utils.prefixes import build_prefixed_filters


def _update(text: str) -> Any:
    """Duck-typed message carrying one command, as Kurigram filters read it."""
    return SimpleNamespace(text=text)


def _command_fallback(conv: Any) -> Any:
    return next(h for h in conv.fallbacks if isinstance(h, MessageHandler))


_CLIENT = SimpleNamespace(executor=None, me=None)


def _matches(handler: Any, text: str) -> bool:
    """Evaluate the handler's Kurigram filter against one command message."""
    return asyncio.run(handler.check(_CLIENT, _update(text)))


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def _kick_conv() -> Any:
    return build_modaction_conv(
        BuildReason("kick"),
        BuildProof("kick"),
        _noop,
        _noop,
        build_prefixed_filters("tckick"),
        min_role="moderator",
    )


def _appeal_conv() -> Any:
    return build_handler(
        entry_filter=build_prefixed_filters("start"),
        on_entry=_noop,
        on_cancel=_noop,
        on_message=_noop,
        on_unexpected=_noop,
        on_end=_noop,
        cancel_callback="cancel_appeal",
    )


def test_ban_fallback_lets_other_commands_through() -> None:
    filters_ = _command_fallback(
        ban_conversation(_noop, build_prefixed_filters("tcban"))
    )
    assert _matches(filters_, "/help") is False
    assert _matches(filters_, ".help rules") is False
    assert _matches(filters_, "/tcunban 42") is False
    assert _matches(filters_, "/tckick 42") is False


def test_ban_fallback_still_ends_on_reentry() -> None:
    filters_ = _command_fallback(
        ban_conversation(_noop, build_prefixed_filters("tcban"))
    )
    assert _matches(filters_, "/tcban 42") is True
    assert _matches(filters_, "/tcb 42") is True


def test_kick_fallback_lets_other_commands_through() -> None:
    filters_ = _command_fallback(_kick_conv())
    assert _matches(filters_, "/help") is False
    assert _matches(filters_, "/tcban 42") is False
    assert _matches(filters_, "/tcmute 42") is False
    assert _matches(filters_, "/tckick 42") is True


def test_appeal_fallback_lets_help_through() -> None:
    filters_ = _command_fallback(_appeal_conv())
    assert _matches(filters_, "/help") is False
    assert _matches(filters_, "/tcunban 42") is False
