# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression tests for audit-confirmed fixes: proof, duration, unmute."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tcbot import database as db
from tcbot.database import users_cache
from tcbot.modules import netspeed
from tcbot.modules.helper import guards
from tcbot.modules.helper.extraction import refresh as refresh_mod
from tcbot.modules.helper.pipelines import mute_executor, proof_post, stats_panels
from tcbot.utils import logger as logger_mod
from tcbot.utils.circuit_breaker import CircuitBreaker, CircuitState
from tcbot.utils.time_and_date import parse_duration, utc_now


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


def test_proof_gallery_is_one_rich_slideshow(monkeypatch: pytest.MonkeyPatch) -> None:
    msgs = []
    for i in range(11):
        m = MagicMock()
        m.photo = MagicMock(file_id=f"p{i}", file_unique_id=f"u{i}")
        m.video = None
        m.animation = None
        m.document = None
        msgs.append(m)

    rich_calls: list[Any] = []

    async def _send_rich(chat_id: int, rich_message: Any, **kw: Any) -> Any:
        rich_calls.append(rich_message)
        return SimpleNamespace(id=77, message_id=77)

    bot = MagicMock()
    bot.send_rich_message = _send_rich
    bot.send_media_group = AsyncMock(side_effect=AssertionError("no plain gallery"))
    bot.send_photo = AsyncMock(side_effect=AssertionError("no single send"))
    bot.send_video = AsyncMock(side_effect=AssertionError("no single send"))
    bot.send_document = AsyncMock(side_effect=AssertionError("no single send"))

    items, expected = asyncio.run(
        proof_post.upload_proof_items(bot, msgs, "cap", 1, None)  # type: ignore[arg-type]
    )
    assert [item.archive_message_id for item in items] == [77]
    assert expected == 1
    assert len(rich_calls) == 1
    assert len(rich_calls[0].media) == 11


def test_unmute_partial_queues_a_durable_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial unmute revokes the record and keeps the failed groups."""
    revoked: list[tuple[int, int, list[int]]] = []

    async def _locale(_u: Any) -> str:
        return "en-US"

    async def _active(_uid: int) -> dict[str, Any]:
        return {"user_id": 33}

    async def _groups() -> list[dict[str, Any]]:
        return [{"chat_id": 1, "title": "A"}, {"chat_id": 2, "title": "B"}]

    async def _revoke(
        uid: int, requested_by: int, chat_ids: list[int]
    ) -> tuple[int, int]:
        revoked.append((uid, requested_by, chat_ids))
        return 1, 55

    async def _report(_run_id: int) -> dict[str, Any]:
        return {
            "target_count": 2,
            "failed_count": 1,
            "succeeded_count": 1,
            "skipped_count": 0,
            "targets": [
                {"chat_id": 1, "status": "succeeded", "title": "A"},
                {"chat_id": 2, "status": "failed", "title": "B"},
            ],
        }

    async def _deliver(_bot: Any, _run_id: int) -> bool:
        return True

    msg = MagicMock()
    msg.reply_text = AsyncMock()

    async def _reply(payload: Any, **kw: Any) -> Any:
        return await msg.reply_text(getattr(payload, "html", ""), **kw)

    msg.reply_rich = AsyncMock(side_effect=_reply)
    msg.chat = MagicMock(id=1, type="group")

    class _FakeUser:
        id = 1
        first_name = "Mod"

    update = MagicMock()
    update.effective_message = msg
    update.effective_user = _FakeUser()

    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_rich_message = AsyncMock()

    async def _role(uid: int, *, fresh: bool = False) -> str | None:
        return "moderator" if uid == 1 else None

    # * The unmute executor re-checks the pair before revoking the mute; a
    # * fresh role keeps this test on the partial-delivery path it asserts.
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(mute_executor, "locale_for_update", _locale)
    monkeypatch.setattr(
        mute_executor, "cfg", SimpleNamespace(main_group=-1, logs=(-3, None))
    )
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _active)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.mutes_db, "revoke_mute_and_queue_unmute", _revoke)
    monkeypatch.setattr(db.enforcement_ledger, "run_report", _report)
    monkeypatch.setattr(
        mute_executor.moderation_enforcement, "deliver_queued_run", _deliver
    )

    asyncio.run(
        mute_executor.execute_unmute(update, ctx, 33, "Target")  # type: ignore[arg-type]
    )
    assert revoked == [(33, 1, [1, 2, -1])]
    msg.reply_text.assert_awaited_once()


def test_classify_failure_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _classify(*a: Any, **k: Any) -> Any:
        raise RuntimeError("classify down")

    async def _resolve(*a: Any, **k: Any) -> tuple[str, str]:
        return ("developer", "moderator")

    async def _locale(*a: Any, **k: Any) -> str:
        return "en-US"

    replies: list[str] = []

    async def _safe_reply(m: Any, text: str, **k: Any) -> None:
        replies.append(text)

    monkeypatch.setattr(guards.identity, "classify", _classify)
    monkeypatch.setattr(guards, "resolve_and_check", _resolve)
    monkeypatch.setattr(guards, "effective_locale", _locale)
    monkeypatch.setattr(guards, "reply_rich", _safe_reply)

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
    # * The label belongs to the keyboard owner, so greeting delegates the
    # * whole join-ban keyboard instead of naming a button itself.
    assert "buttons.join_ban_btn" in text


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

    class _Bot:
        async def get_users(self, ids: list[int]) -> list[Any]:
            return [
                SimpleNamespace(id=1, first_name="Owner", username=None),
                SimpleNamespace(
                    id=8679231509, first_name="Sang Kucing", username="sangkucing"
                ),
            ]

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_roles, "all_admins", _admins)
    monkeypatch.setattr(db.users_roles, "all_by_role", _by_role)
    monkeypatch.setattr(db.users_cache, "get_mention_data_batch", _mention)

    text, _ = asyncio.run(
        stats_panels.Stats.staff_roster("en-US", bot=_Bot())  # type: ignore[arg-type]
    )
    assert "Sang Kucing" in text
    assert "https://t.me/sangkucing" in text
    admins_section = text.split("Admins")[1].split("Developers")[0]
    assert "- 8679231509" not in admins_section
    # * A stale role key used to render as a raw "[stats.roster.founder]"
    # * marker and log an error; the renamed catalog key is "owner".
    assert "Owner" in text
    assert "stats.roster.founder" not in text.replace("\\", "")


def test_staff_roster_renders_separate_rich_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The roster must not collapse into one raw newline-separated run.

    A divider is a rich block tag, so a generic block converter returns the
    whole fragment verbatim. Telegram then folds the newlines and the '- '
    prefixes into a single line, which is what the staff panel used to show.
    """

    async def _owner() -> int:
        return 1

    async def _admins() -> list[dict[str, int]]:
        return [{"user_id": 2}, {"user_id": 3}]

    async def _by_role(role: str) -> list[dict[str, int]]:
        return [{"user_id": 4}] if role == "developer" else []

    async def _mention(ids: list[int]) -> dict[int, tuple[str, str | None]]:
        return {
            1: ("Owner", None),
            2: ("Alpha", None),
            3: ("Beta", None),
            4: ("Gamma", None),
        }

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_roles, "all_admins", _admins)
    monkeypatch.setattr(db.users_roles, "all_by_role", _by_role)
    monkeypatch.setattr(db.users_cache, "get_mention_data_batch", _mention)

    text, _ = asyncio.run(stats_panels.Stats.staff_roster("en-US"))

    assert "<hr/>" in text
    assert "<p><b>Admins (2)</b></p>" in text
    assert "<ul><li>" in text
    assert text.count("<ul>") >= 3
    assert "\n- " not in text


def test_staff_roster_links_only_users_mtproto_can_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deleted staff account must not produce a rejected profile button."""

    async def _owner() -> int:
        return 1

    async def _admins() -> list[dict[str, int]]:
        return [{"user_id": 2}, {"user_id": 3}]

    async def _by_role(_role: str) -> list[dict[str, int]]:
        return []

    async def _mention(ids: list[int]) -> dict[int, tuple[str, str | None]]:
        return {uid: (str(uid), None) for uid in ids}

    class _Bot:
        async def get_users(self, ids: list[int]) -> list[Any]:
            return [
                SimpleNamespace(id=1, first_name="Owner", username="live_owner"),
                SimpleNamespace(id=2, first_name="Alpha", username=None),
            ]

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner)
    monkeypatch.setattr(db.users_roles, "all_admins", _admins)
    monkeypatch.setattr(db.users_roles, "all_by_role", _by_role)
    monkeypatch.setattr(db.users_cache, "get_mention_data_batch", _mention)

    text, _ = asyncio.run(
        stats_panels.Stats.staff_roster("en-US", bot=_Bot())  # type: ignore[arg-type]
    )

    assert "https://t.me/live_owner" in text
    assert "Alpha" in text
    assert "tg://user" not in text
    assert "3</tg-button>" not in text


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
    lock = threading.Lock()
    active = 0
    peak = 0

    def _slow_ping(base: str, cancel: Any = None) -> float:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        threading.Event().wait(0.05)
        with lock:
            active -= 1
        return 10.0

    monkeypatch.setattr(netspeed, "_ping_server", _slow_ping)
    servers = [{"url": f"https://s{i}/x", "id": str(i)} for i in range(5)]
    _server, ping, _base = netspeed._pick_best(servers)  # type: ignore[arg-type]
    assert ping == 10.0
    assert peak > 1


def test_identity_needs_refresh_reads_the_stored_updated_at() -> None:
    """The freshness check reads the column the profile row actually carries.

    The helper used to read ``last_updated``, a name the community schema
    does not have, so every complete profile counted as stale and every
    user card launched a live identity refresh.
    """
    fresh = {
        "first_name": "Ada",
        "username": "ada",
        "updated_at": utc_now(),
    }
    assert refresh_mod.identity_needs_refresh(fresh) is False

    stale = {
        "first_name": "Ada",
        "username": "ada",
        "updated_at": utc_now() - timedelta(days=30),
    }
    assert refresh_mod.identity_needs_refresh(stale) is True


def test_sync_user_identity_trusts_a_fresh_complete_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh complete profile must not pay for a live Telegram lookup."""
    cached = {
        "first_name": "Ada",
        "username": "ada",
        "last_name": None,
        "updated_at": utc_now(),
    }
    live = AsyncMock(side_effect=AssertionError("live lookup must not run"))
    monkeypatch.setattr(db.users_cache, "get_user", AsyncMock(return_value=cached))
    monkeypatch.setattr(refresh_mod, "_fetch_live_identity", live)

    result = asyncio.run(refresh_mod.sync_user_identity(MagicMock(), 42))  # type: ignore[arg-type]

    assert result == ("Ada", "ada", None)
    live.assert_not_awaited()


def test_user_table_renders_the_stored_profile_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The table reads ``first_seen_at`` and ``last_seen_at``, not old field names.

    A user row carries both dates directly, so no separate detail card is
    needed and the older field names must not render as unknown fallbacks.
    """
    first_seen = utc_now() - timedelta(days=30)
    last_seen = utc_now()
    page = [
        {
            "user_id": 42,
            "first_name": "Ada",
            "username": "ada",
            "last_name": None,
            "first_seen_at": first_seen,
            "last_seen_at": last_seen,
        }
    ]
    rendered: list[object] = []

    def _date(value: object, _locale: str | None = None) -> str:
        rendered.append(value)
        return "RENDERED"

    monkeypatch.setattr(db.users_cache, "total_users", AsyncMock(return_value=1))
    monkeypatch.setattr(db.users_cache, "all_users_page", AsyncMock(return_value=page))
    monkeypatch.setattr(stats_panels, "date_or_unknown", _date)

    text, markup = asyncio.run(stats_panels.Stats.users_list(0, "en-US"))

    assert rendered == [first_seen, last_seen]
    assert "<table" in text
    callbacks = {
        b.callback_data
        for row in markup.inline_keyboard
        for b in row
        if isinstance(b.callback_data, str)
    }
    assert "stats_main" in callbacks
    assert not any(cb.startswith("stats_user_item") for cb in callbacks)


def test_identity_refresh_deduplicates_per_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated detail views of one user schedule one live refresh."""
    spawned: list[Any] = []

    class _Tracker:
        pending = 0

        def spawn(self, coro: Any) -> bool:
            spawned.append(coro)
            return True

    async def _refresh(bot: Any, target_id: int) -> None:
        return None

    monkeypatch.setattr(refresh_mod, "identity_refresh_tasks", _Tracker())
    monkeypatch.setattr(refresh_mod, "_identity_refresh_inflight", set())
    monkeypatch.setattr(refresh_mod, "_identity_refresh_drops", 0)
    monkeypatch.setattr(refresh_mod, "_refresh_identity", _refresh)

    async def _run() -> None:
        refresh_mod.launch_identity_refresh(None, 42)
        refresh_mod.launch_identity_refresh(None, 42)
        assert len(spawned) == 1
        for coro in spawned:
            await coro
        assert refresh_mod._identity_refresh_inflight == set()

    asyncio.run(_run())


def test_identity_refresh_caps_concurrent_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saturated refresh tracker drops new work instead of piling on."""
    spawned: list[Any] = []

    class _Tracker:
        pending = refresh_mod._IDENTITY_REFRESH_MAX_CONCURRENT

        def spawn(self, coro: Any) -> bool:
            spawned.append(coro)
            return True

    monkeypatch.setattr(refresh_mod, "identity_refresh_tasks", _Tracker())
    monkeypatch.setattr(refresh_mod, "_identity_refresh_inflight", set())
    monkeypatch.setattr(refresh_mod, "_identity_refresh_drops", 0)

    refresh_mod.launch_identity_refresh(None, 7)
    assert spawned == []
