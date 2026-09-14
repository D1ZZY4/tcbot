# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal submit stays retryable when the review card post fails."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from telegram.ext import ConversationHandler

from tcbot import database as db
from tcbot.modules.helper.workflows import appeal_submit_flow
from tcbot.modules.helper.workflows.appeal_submit_flow import (
    WAITING_APPEAL,
    AppealSubmitMixin,
)
from tcbot.utils.i18n import t


class _FakeMsg:
    """User message double recording replies and the forward."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> object:
        self.replies.append(text)
        return object()

    async def forward(self, *args: Any, **kwargs: Any) -> object:
        return SimpleNamespace(message_id=111)


class _FakeBot:
    """Fails the review-card post, succeeds the log post, records edits."""

    def __init__(self, main_group: int) -> None:
        self._main_group = main_group
        self.edits: list[str] = []

    async def send_message(self, chat_id: int, *args: Any, **kwargs: Any) -> object:
        if chat_id == self._main_group:
            raise RuntimeError("review post blew up")
        return SimpleNamespace(message_id=222)

    async def edit_message_text(
        self, text: str, chat_id: int | None = None, message_id: int | None = None
    ) -> object:
        self.edits.append(text)
        return object()


def _update(msg: _FakeMsg, bot: _FakeBot) -> Any:
    user = SimpleNamespace(id=42, username="u", first_name="U", last_name="L")
    chat = SimpleNamespace(id=7, type="private")
    return SimpleNamespace(
        effective_message=msg, effective_user=user, effective_chat=chat
    )


def test_review_post_failure_stays_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _locale(update: object) -> str:
        return "en-US"

    async def _get_ban(ban_id: str) -> dict[str, Any]:
        return {"is_active": True}

    async def _upsert(*args: Any, **kwargs: Any) -> None:
        return None

    async def _set_appeal_log(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(appeal_submit_flow, "locale_for_update", _locale)
    monkeypatch.setattr(db.bans_db, "get_ban", _get_ban)
    monkeypatch.setattr(db.bans_db, "set_appeal_log_msg", _set_appeal_log)
    monkeypatch.setattr(db.users_cache, "upsert_user", _upsert)
    monkeypatch.setattr(
        appeal_submit_flow,
        "cfg",
        SimpleNamespace(
            appeals=(-1001, None),
            main_group=-1002,
            logs=(-1003, None),
            appeal_discussion_topic=None,
        ),
    )

    bot = _FakeBot(main_group=-1002)
    msg = _FakeMsg("#appeal please review my case")
    ctx = SimpleNamespace(
        bot=bot,
        user_data={
            "appeal_ban_id": "abc123def4",
            "appeal_log_msg_id": 0,
            "appeal_instruction_msg_id": 777,
        },
    )

    result = asyncio.run(
        AppealSubmitMixin()._on_message(_update(msg, bot), ctx)  # type: ignore[arg-type]
    )

    assert result == WAITING_APPEAL
    assert result != ConversationHandler.END
    # * State intact for an in-place retry; card shows the retry prompt.
    assert ctx.user_data.get("appeal_ban_id") == "abc123def4"
    assert bot.edits[-1] == t("appeals.submit.delivery_failed", "en-US", plain=True)
