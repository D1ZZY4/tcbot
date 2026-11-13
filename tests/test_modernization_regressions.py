# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression tests for audit-confirmed fixes: proof, duration, unmute."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tcbot import database as db
from tcbot.database import users_cache
from tcbot.modules import netspeed
from tcbot.modules.helper import guards
from tcbot.modules.helper.pipelines import mute_flow, proof_flow, stats_flow
from tcbot.utils import logger as logger_mod
from tcbot.utils.circuit_breaker import CircuitBreaker, CircuitState
from tcbot.utils.time_and_date import parse_duration


async def _gather_bounded(coros: list[Any]) -> list[Any]:
    return list(await asyncio.gather(*coros, return_exceptions=True))  # type: ignore[arg-type]


def test_parse_duration_rejects_zero() -> None:
    assert parse_duration("0s") is None
    assert parse_duration("0m") is None
    assert parse_duration("1s") is not None


def test_search_by_name_rejects_nonpositive_limit() -> None:
    async def _run() -> None:
        assert await users_cache.search_by_name("da", limit=0) == []
        assert await users_cache.search_by_name("da", limit=-3) == []

    asyncio.run(_run())


def test_logger_handler_copies_record() -> None:
    captured: list[logging.LogRecord] = []

    def _sink(rec: logging.LogRecord) -> None:
        captured.append(rec)

    # * The logger lives in the utils layer and must not import the error
    # * reporter, so the reporter registers a sink instead. The sink owns
    # * the delivery, so the logger only forwards the record.
    logger_mod.set_record_sink(_sink)
    try:
        handler = logger_mod.TelegramErrorHandler()
        record = logging.LogRecord(
            name="tcbot",
            level=logging.ERROR,
            pathname="x",
            lineno=1,
            msg="boom",
            args=(),
            exc_info=(ValueError, ValueError("boom"), None),
        )
        handler.emit(record)
        record.exc_info = None
    finally:
        logger_mod.set_record_sink(None)

    assert len(captured) == 1
    # * The handler must hand over a copy: the stdlib bridge clears the
    # * live record's exc_info after callHandlers, so forwarding the
    # * original would erase the traceback before the delivery reads it.
    assert captured[0] is not record
    assert captured[0].exc_info is not None


def test_proof_gallery_chunked_at_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    msgs = []
    for i in range(11):
        m = MagicMock()
        m.photo = [MagicMock(file_id=f"p{i}")]
        m.video = None
        m.animation = None
        m.document = None
        msgs.append(m)

    calls: list[int] = []

    async def _send_media_group(chat_id: int, media: list[Any], **kw: Any) -> list[Any]:
        calls.append(len(media))
        out = []
        for _ in media:
            r = MagicMock()
            r.message_id = 1
            out.append(r)
        return out

    bot = MagicMock()
    bot.send_media_group = _send_media_group
    bot.send_photo = AsyncMock(side_effect=AssertionError("no single send"))
    bot.send_video = AsyncMock(side_effect=AssertionError("no single send"))
    bot.send_document = AsyncMock(side_effect=AssertionError("no single send"))

    result = asyncio.run(proof_flow.upload_proof(bot, msgs, "cap", 1, None))  # type: ignore[arg-type]
    assert result == 1
    assert calls == [10, 1]


def test_unmute_partial_keeps_active_record(monkeypatch: pytest.MonkeyPatch) -> None:
    cleared: list[int] = []

    async def _locale(_u: Any) -> str:
        return "en-US"

    async def _active(_uid: int) -> dict[str, Any]:
        return {"user_id": 33}

    async def _groups() -> list[dict[str, Any]]:
        return [{"chat_id": 1, "title": "A"}, {"chat_id": 2, "title": "B"}]

    async def _clear(uid: int) -> None:
        cleared.append(uid)

    replies: list[str] = []

    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.chat = MagicMock(id=1, type="group")

    class _FakeUser:
        id = 1
        first_name = "Mod"

    update = MagicMock()
    update.effective_message = msg
    update.effective_user = _FakeUser()

    ctx = MagicMock()
    ctx.bot.restrict_chat_member = AsyncMock(side_effect=[None, RuntimeError("flood")])
    ctx.bot.send_message = AsyncMock()

    monkeypatch.setattr(mute_flow, "locale_for_update", _locale)
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _active)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.mutes_db, "clear_active_mute", _clear)

    async def _safe_reply(m: Any, text: str, **kw: Any) -> None:
        replies.append(text)

    monkeypatch.setattr(mute_flow, "safe_reply", _safe_reply)

    asyncio.run(mute_flow.execute_unmute(update, ctx, 33, "Target"))  # type: ignore[arg-type]
    assert cleared == []
    assert len(replies) == 1


def test_classify_failure_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _classify(*a: Any, **k: Any) -> Any:
        raise RuntimeError("classify down")

    async def _resolve(*a: Any, **k: Any) -> tuple[str, str]:
        return ("developer", "tester")

    async def _locale(*a: Any, **k: Any) -> str:
        return "en-US"

    replies: list[str] = []

    async def _safe_reply(m: Any, text: str, **k: Any) -> None:
        replies.append(text)

    monkeypatch.setattr(guards.identity, "classify", _classify)
    monkeypatch.setattr(guards, "resolve_and_check", _resolve)
    monkeypatch.setattr(guards, "effective_locale", _locale)
    monkeypatch.setattr(guards, "safe_reply", _safe_reply)

    msg = MagicMock()
    msg.chat = MagicMock(type="group", id=1)
    bot = MagicMock()

    result = asyncio.run(
        guards.classify_and_check(
            bot, 1, 2, None, msg, action="ban", min_role="developer"
        )  # type: ignore[arg-type]
    )
    assert result is None
    assert len(replies) == 1


def test_greeting_has_no_hardcoded_submit_appeal() -> None:
    text = Path("tcbot/modules/greeting.py").read_text(encoding="utf-8")
    assert '"Submit Appeal"' not in text
    assert "button.submit_appeal" in text


def test_staff_roster_resolves_live_on_numeric_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _owner() -> int:
        return 1

    async def _admins() -> list[dict[str, int]]:
        return [{"user_id": 8679231509}]

    async def _by_role(role: str) -> list[dict[str, int]]:
        return []

    async def _mention(ids: list[int]) -> dict[int, tuple[str, str | None]]:
        return {1: ("Founder", None), 8679231509: ("8679231509", None)}

    async def _sync(bot: Any, uid: int) -> tuple[str, str | None, str | None]:
        return ("Sang Kucing", "sangkucing", None)

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_roles, "all_admins", _admins)
    monkeypatch.setattr(db.users_roles, "all_by_role", _by_role)
    monkeypatch.setattr(db.users_cache, "get_mention_data_batch", _mention)
    monkeypatch.setattr(stats_flow, "sync_user_identity", _sync)

    text, _ = asyncio.run(stats_flow.Stats.staff_roster("en-US", bot=MagicMock()))
    assert "Sang Kucing" in text
    admins_section = text.split("Admins")[1].split("Developers")[0]
    assert "- 8679231509" not in admins_section


def test_circuit_decay_resets_lifetime_count() -> None:
    cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout=60.0)
    cb._record_failure()
    assert cb._failure_count == 1
    for _ in range(10):
        cb._record_success()
    assert cb._failure_count == 0
    assert cb.state == CircuitState.CLOSED


def test_circuit_partial_outage_still_trips() -> None:
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60.0)
    for _ in range(3):
        cb._record_failure()
        cb._record_success()
        cb._record_success()
    assert cb.state == CircuitState.OPEN


def test_pick_best_probes_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    def _slow_ping(base: str, cancel: Any = None) -> float:
        time.sleep(0.05)
        return 10.0

    monkeypatch.setattr(netspeed, "_ping_server", _slow_ping)
    servers = [{"url": f"https://s{i}/x", "id": str(i)} for i in range(5)]
    start = time.monotonic()
    _server, ping, _base = netspeed._pick_best(servers)  # type: ignore[arg-type]
    elapsed = time.monotonic() - start
    assert ping == 10.0
    assert elapsed < 0.4  # parallel ~0.05s, sequential would be ~0.25s+overhead
