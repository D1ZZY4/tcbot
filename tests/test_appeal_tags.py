# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal tag matching and log-message reference checks."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telegram import Update

from tcbot import cfg
from tcbot.modules import appeals
from tcbot.modules.helper.pipelines import appeal_submit
from tcbot.modules.helper.pipelines.appeal_submit import (
    WAITING_APPEAL,
    handle_group_appeal,
    starts_with_appeal_tag,
    text_references_log_message,
)


def test_appeal_tag_case_insensitive_and_padded() -> None:
    assert starts_with_appeal_tag("#appeal text") is True
    assert starts_with_appeal_tag("#APPEAL text") is True
    assert starts_with_appeal_tag("#Appeal text") is True
    assert starts_with_appeal_tag("   #appeal text  ") is True


def test_appeal_tag_rejects_other_text() -> None:
    assert starts_with_appeal_tag("appeal text") is False
    assert starts_with_appeal_tag("") is False


def test_appeal_tag_is_prefix_not_token() -> None:
    # * The check is a plain prefix match, so "#appeals" also opens the flow.
    assert starts_with_appeal_tag("#appeals text") is True


def test_log_reference_matches_standalone_id() -> None:
    assert text_references_log_message("https://t.me/c/123/67?thread=1", 67) is True
    assert text_references_log_message("log 67 here", 67) is True


def test_log_reference_rejects_partial_numbers() -> None:
    assert text_references_log_message("670", 67) is False
    assert text_references_log_message("6", 67) is False
    assert text_references_log_message("no numbers", 67) is False


def test_a_long_ordinary_word_does_not_reject_a_group_appeal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the sender's active ban matters, not long words in the text."""
    called: list[int] = []

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _active(_user_id: int) -> dict[str, Any]:
        return {"ban_id": "goodban001", "log_message_id": 0}

    async def _on_message(_update: Any, _ctx: Any) -> int:
        called.append(1)
        return WAITING_APPEAL

    monkeypatch.setattr(appeal_submit, "locale_for_update", _locale)
    monkeypatch.setattr(appeal_submit.db.bans_db, "get_active_ban", _active)
    monkeypatch.setattr(
        appeal_submit,
        "cfg",
        dataclasses.replace(cfg, main_group=-1001),
    )

    msg = SimpleNamespace(
        text="#appeal the moderation was unfair",
        chat=SimpleNamespace(id=-1001),
    )
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=-1001),
    )
    asyncio.run(
        handle_group_appeal(  # type: ignore[arg-type]
            update,  # type: ignore[arg-type]
            SimpleNamespace(user_data={}),  # type: ignore[arg-type]
            _on_message,
        )
    )

    assert called == [1]


def _appeal_update(ban_id: str) -> SimpleNamespace:
    message = SimpleNamespace(
        text=f"/start appeal_{ban_id}",
        chat=SimpleNamespace(type="private"),
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(type="private"),
        effective_message=message,
        channel_post=None,
        message=message,
        edited_channel_post=None,
        edited_message=None,
        business_message=None,
        edited_business_message=None,
        guest_message=None,
    )


def test_appeal_deep_link_accepts_every_valid_reference() -> None:
    # * The parser accepts 10 to 32 characters; the handler filter has to
    # * accept the same range or a legacy reference produces a dead link.
    assert appeals._APPEAL_START_CMDS.check_update(
        cast("Update", _appeal_update("a" * 10))
    )
    assert appeals._APPEAL_START_CMDS.check_update(
        cast("Update", _appeal_update("a" * 32))
    )


def test_appeal_deep_link_rejects_an_invalid_reference() -> None:
    assert not appeals._APPEAL_START_CMDS.check_update(
        cast("Update", _appeal_update("a" * 9))
    )
    assert not appeals._APPEAL_START_CMDS.check_update(
        cast("Update", _appeal_update("a" * 33))
    )
