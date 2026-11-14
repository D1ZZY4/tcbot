# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Webhook lifecycle cleanup on boot and start failures."""

from __future__ import annotations

import pytest

from tcbot import __main__ as main_module


class _FakeBot:
    """Record the webhook deletion without touching Telegram."""

    def __init__(self) -> None:
        self.deleted = 0

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        self.deleted += 1


class _FakeApp:
    """Minimal async context manager for the webhook runner."""

    def __init__(self, *, start_error: bool = False) -> None:
        self.bot = _FakeBot()
        self.running = False
        self.start_error = start_error

    async def __aenter__(self) -> _FakeApp:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def start(self) -> None:
        if self.start_error:
            raise RuntimeError("start failed")
        self.running = True

    async def stop(self) -> None:
        self.running = False


@pytest.mark.asyncio
async def test_post_init_failure_still_runs_post_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed boot must release the subsystems connected before it."""
    app = _FakeApp()
    shut_down: list[int] = []

    async def _post_init(_app: object) -> None:
        raise RuntimeError("boot failed")

    async def _post_shutdown(_app: object) -> None:
        shut_down.append(1)

    monkeypatch.setattr(main_module, "_post_init", _post_init)
    monkeypatch.setattr(main_module, "_post_shutdown", _post_shutdown)

    with pytest.raises(RuntimeError, match="boot failed"):
        await main_module._run_webhook_mode(app)  # type: ignore[arg-type]

    assert app.bot.deleted == 1
    assert shut_down == [1]


@pytest.mark.asyncio
async def test_start_failure_still_runs_post_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed application start follows the same cleanup contract."""
    app = _FakeApp(start_error=True)
    shut_down: list[int] = []

    async def _post_init(_app: object) -> None:
        return None

    async def _post_shutdown(_app: object) -> None:
        shut_down.append(1)

    monkeypatch.setattr(main_module, "_post_init", _post_init)
    monkeypatch.setattr(main_module, "_post_shutdown", _post_shutdown)

    with pytest.raises(RuntimeError, match="start failed"):
        await main_module._run_webhook_mode(app)  # type: ignore[arg-type]

    assert app.bot.deleted == 1
    assert shut_down == [1]
