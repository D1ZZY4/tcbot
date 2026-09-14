# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Join enforcement shares one global concurrency bound instead of one per update."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from tcbot import cfg
from tcbot.modules import greeting as greeting_mod


def _update(member_count: int) -> SimpleNamespace:
    members = [
        SimpleNamespace(id=i, first_name=f"M{i}", username=None)
        for i in range(member_count)
    ]
    return SimpleNamespace(
        effective_message=SimpleNamespace(new_chat_members=members),
        effective_chat=SimpleNamespace(id=-100),
        effective_user=SimpleNamespace(id=1),
    )


def test_join_sem_is_module_global_singleton(monkeypatch: Any) -> None:
    made: list[object] = []
    real_sem = asyncio.Semaphore

    class _CountingSemaphore(real_sem):  # type: ignore[misc, valid-type]
        def __init__(self, value: int = 1, *args: Any, **kwargs: Any) -> None:
            made.append(self)
            super().__init__(value, *args, **kwargs)

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "Semaphore", _CountingSemaphore)
    monkeypatch.setattr(greeting_mod, "_handle_member", _noop)
    monkeypatch.setattr(cfg, "is_primary_group", lambda _chat_id: True)

    asyncio.run(
        greeting_mod.on_new_member(
            _update(2),  # type: ignore[arg-type]
            SimpleNamespace(bot=object()),
        )
    )

    assert isinstance(greeting_mod._join_sem, real_sem)
    assert made == []


def test_join_batch_still_bounded(monkeypatch: Any) -> None:
    state: dict[str, int] = {"inflight": 0, "peak": 0}

    async def _slow(*args: Any, **kwargs: Any) -> None:
        state["inflight"] += 1
        state["peak"] = max(state["peak"], state["inflight"])
        try:
            await asyncio.sleep(0.01)
        finally:
            state["inflight"] -= 1

    monkeypatch.setattr(greeting_mod, "_handle_member", _slow)
    monkeypatch.setattr(cfg, "is_primary_group", lambda _chat_id: True)

    asyncio.run(
        greeting_mod.on_new_member(
            _update(12),  # type: ignore[arg-type]
            SimpleNamespace(bot=object()),
        )
    )

    assert state["peak"] <= 10
    assert state["peak"] >= 2
