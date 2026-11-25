# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Cancellation propagates through the real moderated delivery gathers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tcbot.modules.helper.pipelines import transfer_owner, warn_actions
from tests.test_role_assignment_rules import _bot, _install_transfer, _transfer_update


def test_transfer_delivery_cancellation_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled log send must abort the transfer, not become a group failure."""
    _install_transfer(monkeypatch)

    async def _cancelled_log(*args: object, **kwargs: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(transfer_owner, "send_log", _cancelled_log)
    ctx = SimpleNamespace(bot=_bot())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            transfer_owner.execute_transfer(_transfer_update(), ctx)  # type: ignore[arg-type]
        )


def test_warn_manage_delivery_cancellation_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled log send must abort unwarn after the warning was removed."""

    async def _locale(*args: object, **kwargs: object) -> str:
        return "en-US"

    async def _count(*args: object, **kwargs: object) -> int:
        return 1

    async def _removed(*args: object, **kwargs: object) -> bool:
        return True

    async def _reply(*args: object, **kwargs: object) -> None:
        return None

    async def _cancelled_log(*args: object, **kwargs: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(warn_actions, "locale_for_update", _locale)
    monkeypatch.setattr(warn_actions.db.warns_db, "warn_count", _count)
    monkeypatch.setattr(warn_actions.db.warns_db, "remove_last_warn", _removed)
    monkeypatch.setattr(warn_actions, "reply_rich", _reply)
    monkeypatch.setattr(warn_actions, "send_log", _cancelled_log)

    ctx = SimpleNamespace(
        bot=_bot(),
        effective_message=SimpleNamespace(text="/tcunwarn 42"),
        effective_chat=SimpleNamespace(id=-100, title="Group"),
        effective_user=SimpleNamespace(id=1, first_name="Admin"),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(warn_actions.execute_unwarn(ctx, 42, "Target"))  # type: ignore[arg-type]
