# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Wave regression coverage: harvest budget, flood handling, scrub, config, sync order, cron."""

from __future__ import annotations

import asyncio
import itertools
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

import api.cron as cron_mod
from tcbot import _env_list, cfg
from tcbot.database import mtproto
from tcbot.modules import syncing as sy
from tcbot.utils import error_reporter


def _run(coro: Any) -> Any:
    """Drive one coroutine to completion without relying on any async plugin."""
    return asyncio.run(coro)


class _FloodWait(Exception):
    """Telegram FloodWait double: the wait delay rides on .value."""

    def __init__(self) -> None:
        super().__init__("flood")
        self.value = 5


class _FloodingClient:
    """MTProto client double whose user lookup always hits FloodWait."""

    is_connected = True

    async def get_users(self, _user_id: int) -> Any:
        raise _FloodWait()


class _EndlessHarvestClient:
    """MTProto client double yielding an unbounded member stream, never touching the network."""

    def __init__(self) -> None:
        self.is_connected = True

    async def get_chat_members(self, _chat_id: int, limit: int = 0) -> Any:
        for uid in itertools.count(1):
            yield SimpleNamespace(
                user=SimpleNamespace(
                    id=uid,
                    first_name=f"N{uid}",
                    username=None,
                    last_name=None,
                    is_bot=False,
                )
            )


def test_harvest_stops_at_timeslice_budget(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    calls = {"n": 0}
    budget = mtproto._HARVEST_BUDGET_S

    def _fake_monotonic() -> float:
        calls["n"] += 1
        if calls["n"] <= 3:
            return 1000.0
        return 1000.0 + budget + 1.0

    # * monotonic is imported into mtproto's namespace, so patch it there, not time globally.
    monkeypatch.setattr(mtproto, "monotonic", _fake_monotonic)
    monkeypatch.setattr(mtproto, "_auth_dead", False)
    monkeypatch.setattr(mtproto, "_client", _EndlessHarvestClient())
    harvested: list[int] = []

    async def _harvest(
        uid: int, _uname: str | None, _fname: str, _lname: str | None = None
    ) -> bool:
        harvested.append(uid)
        return True

    monkeypatch.setattr("tcbot.database.users_cache.harvest_user_identity", _harvest)
    with caplog.at_level(logging.WARNING, logger="tcbot.database.mtproto"):
        count = _run(mtproto.harvest_group_members(-1001, limit=1000))

    assert count == 2
    assert harvested == [1, 2]
    assert "timeslice" in caplog.text


def test_fetch_user_flood_wait_warns_and_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    # * is_bot_user shares _fetch_user with resolve_user, so one path suffices here.
    monkeypatch.setattr(mtproto, "_auth_dead", False)
    monkeypatch.setattr(mtproto, "_client", _FloodingClient())
    with caplog.at_level(logging.WARNING, logger="tcbot.database.mtproto"):
        assert _run(mtproto.resolve_user(42)) is None
    assert "FloodWait" in caplog.text


def test_scrub_secrets_redacts_exact_configured_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        error_reporter,
        "cfg",
        SimpleNamespace(
            bot_token="SENTINEL-BOT-TOKEN-xyz",
            mongodb_uri="SENTINEL-MONGO-xyz",
            api_hash="SENTINEL-APIHASH-xyz",
            webhook_secret="SENTINEL-WEBHOOK-xyz",
            cron_secret="SENTINEL-CRON-xyz",
            redis_url="SENTINEL-REDIS-xyz",
        ),
    )
    for value in (
        "SENTINEL-BOT-TOKEN-xyz",
        "SENTINEL-MONGO-xyz",
        "SENTINEL-APIHASH-xyz",
        "SENTINEL-WEBHOOK-xyz",
        "SENTINEL-CRON-xyz",
        "SENTINEL-REDIS-xyz",
    ):
        text = error_reporter._scrub_secrets(f"leak>>{value}<<done")
        assert value not in text
        assert "[REDACTED]" in text
        assert text.startswith("leak>>") and text.endswith("<<done")
    token_shaped = error_reporter._scrub_secrets(
        "oops 999888:ABCDEFghij1234567890XY end"
    )
    assert "999888:ABCDEFghij1234567890XY" not in token_shaped
    mongo_shaped = error_reporter._scrub_secrets(
        "oops mongodb://user:hunter2@host/db end"
    )
    assert "hunter2" not in mongo_shaped
    assert "://[REDACTED]@" in mongo_shaped


def test_env_list_accepts_csv_and_literal_list_identically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TC_WAVE_LIST", "alpha, beta ,gamma")
    from_csv = _env_list("TC_WAVE_LIST")
    monkeypatch.setenv("TC_WAVE_LIST", '["alpha", "beta", "gamma"]')
    from_literal = _env_list("TC_WAVE_LIST")
    assert from_csv == ["alpha", "beta", "gamma"]
    assert from_literal == from_csv


def test_cfg_prefixes_returns_copy() -> None:
    first = cfg.prefixes
    first.append("__mutant__")
    assert "__mutant__" not in cfg.prefixes


def test_sync_sweep_sorts_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _groups() -> list[dict[str, Any]]:
        return [
            {"chat_id": 30, "title": "C"},
            {"chat_id": 10, "title": "A"},
            {"chat_id": 20, "title": "B"},
        ]

    async def _bans() -> list[int]:
        return [3, 1, 2]

    monkeypatch.setattr(sy.db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(sy.db.bans_db, "active_ban_user_ids", _bans)
    seen: dict[str, Any] = {}
    orig_take = sy.take_pairs

    def _spy(
        user_ids: list[int], chat_ids: list[int], max_checks: int
    ) -> tuple[list[tuple[int, int]], bool]:
        seen["uids"] = list(user_ids)
        seen["cids"] = list(chat_ids)
        pairs, truncated = orig_take(user_ids, chat_ids, max_checks)
        seen["pairs"] = list(pairs)
        return pairs, truncated

    monkeypatch.setattr(sy, "take_pairs", _spy)

    async def _ok(_bot: Any, _chat_id: int, _user_id: int) -> str:
        return "ok"

    monkeypatch.setattr(sy, "_sync_ban_pair", _ok)
    counts = _run(sy.run_ban_sync(cast("Any", SimpleNamespace())))

    assert seen["uids"] == [1, 2, 3]
    assert seen["cids"] == [10, 20, 30]
    assert seen["pairs"] == sorted(seen["pairs"])
    assert counts.checked == 9


def test_cron_do_post_answers_405() -> None:
    # * BaseHTTPRequestHandler init needs a live socket, so build the handler
    # * without it and stub the reply sink; do_POST only logs plus replies.
    inst = object.__new__(cron_mod.handler)
    captured: dict[str, Any] = {}
    inst._reply = lambda status, body: captured.update(status=status, body=body)  # type: ignore[attr-defined]
    inst.do_POST()
    assert captured == {"status": 405, "body": "Method not allowed"}
