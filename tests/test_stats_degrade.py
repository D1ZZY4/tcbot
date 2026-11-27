# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A failed stats render must show an error card, not leave a dead panel."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.modules.helper.rich.edit_msg import ack_and_render


class _Query:
    """Minimal callback query that records answers and rich edits."""

    def __init__(self) -> None:
        self.answers: list[Any] = []
        self.edits: list[dict[str, Any]] = []

    async def answer(self, *args: Any, **kwargs: Any) -> None:
        self.answers.append((args, kwargs))

    async def edit_message_text(self, *args: Any, **kwargs: Any) -> None:
        self.edits.append({"args": args, "kwargs": kwargs})


@pytest.mark.asyncio
async def test_a_failed_render_shows_the_fallback_card() -> None:
    q = _Query()

    async def _fail() -> None:
        raise RuntimeError("database unavailable")

    await ack_and_render(q, _fail(), fallback=("Could not load this view.", None))  # type: ignore[arg-type]

    assert len(q.answers) == 1
    assert len(q.edits) == 1
    edit = q.edits[0]
    payload = edit["kwargs"].get("rich_message")
    rendered = payload.html if payload is not None else str(edit["args"])
    assert "Could not load this view." in rendered


@pytest.mark.asyncio
async def test_cancellation_is_never_rendered_as_an_error_card() -> None:
    q = _Query()

    async def _cancel() -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await ack_and_render(q, _cancel(), fallback=("Could not load this view.", None))  # type: ignore[arg-type]

    assert len(q.answers) == 1
    assert q.edits == []
