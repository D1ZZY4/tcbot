# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression tests for verified correctness and reliability fixes."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import __main__ as main_mod
from tcbot import cfg
from tcbot import database as db
from tcbot.database.cache import redis_io
from tcbot.database.cache.twolevel import TwoLevelCache
from tcbot.database.scheduler import jobs as scheduler_jobs
from tcbot.modules.helper.decorators import ratelimit
from tcbot.modules.helper.pipelines.errors import report as error_reporter
from tcbot.modules.helper.pipelines.stats_panels import Stats
from tcbot.modules.helper.rich import media as rich_media
from tcbot.modules.helper.rich import text as rich_text
from tcbot.utils import i18n


def test_sentry_initialises_with_a_valid_integration_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid integration option must reach sentry_sdk.init.

    An unsupported keyword made the constructor raise; the failure was
    swallowed and monitoring stayed off for every deployment with a DSN.
    """
    calls: list[dict[str, Any]] = []
    integration_kwargs: list[dict[str, Any]] = []

    class _Integration:
        def __init__(self, **kwargs: Any) -> None:
            integration_kwargs.append(kwargs)

    class _SDK:
        @staticmethod
        def init(**kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(main_mod, "sentry_sdk", _SDK)
    monkeypatch.setattr(main_mod, "LoguruIntegration", _Integration)
    monkeypatch.setattr(
        main_mod, "cfg", dataclasses.replace(cfg, sentry_dsn="https://k@example/1")
    )

    main_mod._init_sentry()

    assert len(calls) == 1
    assert integration_kwargs == [{"event_level": 40}]
    assert calls[0]["before_send"] is error_reporter.scrub_sentry_event
    assert calls[0]["send_default_pii"] is False


def test_refresh_does_not_publish_a_value_invalidated_during_the_tombstone_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A generation change after the tombstone await must discard the read.

    ``invalidate`` needs no lock and can land while the critical refresh
    awaits Redis. Without a second check the stale value goes back into L1
    and survives for the whole TTL.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    checked: list[bool] = []

    async def _tombstoned(self: TwoLevelCache[Any], rc: Any, key: Any) -> bool:
        _ = (self, rc, key)
        started.set()
        await release.wait()
        checked.append(True)
        return False

    monkeypatch.setattr(TwoLevelCache, "_tombstoned", _tombstoned)
    monkeypatch.setattr(redis_io, "usable_redis_client", lambda: object())

    async def _run() -> None:
        cache: TwoLevelCache[str] = TwoLevelCache(
            memory_ttl=60, redis_ttl=90, redis_prefix="role"
        )

        async def _fetch() -> str:
            return "admin"

        async def _revoked() -> None:
            await started.wait()
            cache._state("k").generation += 1
            release.set()

        result, _ = await asyncio.gather(cache.refresh("k", _fetch), _revoked())
        assert result == "admin"
        assert cache.get("k") != "admin"

    asyncio.run(_run())
    assert checked == [True]


def test_rate_limiter_blocks_an_update_with_no_notification_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A throttled update without a message or callback must not run."""
    called: list[bool] = []

    async def _check(self: Any, uid: int) -> float:
        _ = (self, uid)
        return 12.0

    async def _exempt(uid: int) -> bool:
        _ = uid
        return False

    monkeypatch.setattr(ratelimit._AsyncRateLimiter, "check", _check)
    monkeypatch.setattr(ratelimit, "_is_exempt", _exempt)

    @ratelimit.ratelimiter(ratelimit.THROTTLE_MODERATION)
    async def _handler(ctx: Any) -> str:
        _ = ctx
        called.append(True)
        return "ran"

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        callback_query=None,
        effective_message=None,
    )

    assert asyncio.run(_handler(update)) is None
    assert called == []


def test_media_helpers_render_their_caption() -> None:
    """Photo and video must not silently drop a supplied caption."""
    assert "MY CAPTION" in rich_media.photo("https://x/i.jpg", caption="MY CAPTION")
    assert "<figcaption>MY CAPTION</figcaption>" in rich_media.video(
        "https://x/v.mp4", caption="MY CAPTION"
    )


def test_blocks_do_not_wrap_block_level_elements_in_paragraphs() -> None:
    """Headings and other block tags must stay outside a paragraph."""
    html = rich_text.blocks("<h2>Title</h2>\nSome text")
    assert "<h2>Title</h2>" in html
    assert "<p><h2>" not in html


def test_safe_username_rejects_a_trailing_newline() -> None:
    """A newline after a username must not pass the shape check."""
    assert i18n.safe_username("abcde") == "abcde"
    assert i18n.safe_username("abcde\n") is None


def test_stats_header_is_not_bold_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """A catalog header already renders bold; bolding it again escapes the tag."""

    async def _total() -> int:
        return 959

    async def _page(skip: int, limit: int) -> list[dict[str, object]]:
        _ = (skip, limit)
        return [
            {
                "user_id": 1,
                "first_name": "Ann",
                "username": None,
                "first_seen_at": None,
                "last_seen_at": None,
            }
        ]

    monkeypatch.setattr(db.users_cache, "total_users", _total)
    monkeypatch.setattr(db.users_cache, "all_users_page", _page)

    text, _ = asyncio.run(Stats.users_list(3, "en-US"))

    assert "<b>Users</b>" in text
    assert "&lt;b&gt;" not in text
    assert "page 4/192" in text


def test_the_daily_cleanup_allows_the_erasure_budget() -> None:
    """The combined daily sweep must not cut a valid erasure batch short."""
    assert scheduler_jobs._DAILY_CLEANUP_TIMEOUT_S >= (
        scheduler_jobs._ERASURE_OP_TIMEOUT_S
    )
    assert scheduler_jobs._DAILY_CLEANUP_TIMEOUT_S > scheduler_jobs._EXPIRE_OP_TIMEOUT_S
