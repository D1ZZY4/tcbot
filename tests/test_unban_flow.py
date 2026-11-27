# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""execute_unban fails closed and names missed groups."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules import unban
from tcbot.modules.helper.identity import Identity
from tcbot.modules.helper.pipelines import unban_executor
from tcbot.modules.helper.rich.button import ANONYMOUS_BOT_ID
from tcbot.utils.i18n import Safe, t, user_ref


class _FakeMsg:
    """Message double recording replies."""

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> object:
        self.replies.append(text)
        return object()


class _FakeBot:
    """Bot double with scripted unban outcomes, recording log sends."""

    def __init__(self, fail_ids: set[int] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self.unbanned: list[int] = []
        self.logs: list[str] = []

    async def unban_chat_member(
        self, chat_id: int, user_id: int, **kwargs: Any
    ) -> object:
        self.unbanned.append(chat_id)
        if chat_id in self.fail_ids:
            raise RuntimeError("transient boom")
        return True

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> object:
        self.logs.append(text)
        return object()


def _update(msg: _FakeMsg, admin: Any) -> Any:
    return SimpleNamespace(effective_message=msg, effective_user=admin)


def _ctx(bot: _FakeBot) -> Any:
    return SimpleNamespace(bot=bot)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ban: Any = "default",
    groups: Any = "default",
    deactivate: Any = "default",
) -> dict[str, list[str]]:
    """Stub locale, cfg, the durable run, and DB seams; return call ledger."""
    calls: dict[str, list[str]] = {"deactivate": []}
    selected_groups: list[dict[str, Any]] = (
        [{"chat_id": 1, "title": "Only"}]
        if groups == "default"
        else ([] if isinstance(groups, BaseException) else groups)
    )
    failed_chats: list[int] = []

    async def _locale(update: object) -> str:
        return "en-US"

    async def _get_active_ban(user_id: int) -> Any:
        if isinstance(ban, BaseException):
            raise ban
        if ban == "default":
            return {"ban_id": "ban1234567"}
        return ban

    async def _active_groups() -> Any:
        if isinstance(groups, BaseException):
            raise groups
        return selected_groups

    async def _revoke(
        user_id: int,
        requested_by: int | None,
        chat_ids: list[int],
        **kwargs: Any,
    ) -> Any:
        calls["deactivate"].append("x")
        if isinstance(deactivate, BaseException):
            raise deactivate
        return 1, 77

    async def _allow_enforcement(
        executor_id: int,
        target_id: int,
        *,
        min_role: str,
        action: str,
        locale: str | None,
    ) -> None:
        _ = (executor_id, target_id, min_role, action, locale)

    async def _deliver(bot: _FakeBot, run_id: int) -> bool:
        for group in selected_groups:
            try:
                await bot.unban_chat_member(group["chat_id"], 42)
            except Exception:
                failed_chats.append(int(group["chat_id"]))
        return True

    async def _report(run_id: int) -> dict[str, Any]:
        return {
            "target_count": len(selected_groups),
            "failed_count": len(failed_chats),
            "targets": [
                {
                    "chat_id": group["chat_id"],
                    "title": group["title"],
                    "status": (
                        "failed"
                        if int(group["chat_id"]) in failed_chats
                        else "succeeded"
                    ),
                }
                for group in selected_groups
            ],
        }

    async def _role(_user_id: int, *, fresh: bool = False) -> str | None:
        _ = fresh
        return None

    async def _no_demote(*args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        return SimpleNamespace(may_proceed=True, value="proceed")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(unban_executor, "demote_before_unban", _no_demote)
    monkeypatch.setattr(unban_executor, "locale_for_update", _locale)
    monkeypatch.setattr(
        unban_executor,
        "cfg",
        SimpleNamespace(main_group=-1, exec_group=-2, logs=(-3, None)),
    )
    monkeypatch.setattr(db.bans_db, "get_active_ban", _get_active_ban)
    monkeypatch.setattr(db.bans_db, "revoke_ban_and_queue_unban", _revoke)
    monkeypatch.setattr(db.groups_db, "active_groups", _active_groups)
    monkeypatch.setattr(
        unban_executor.guards, "enforcement_refusal", _allow_enforcement
    )
    monkeypatch.setattr(
        unban_executor.moderation_enforcement, "deliver_queued_run", _deliver
    )
    monkeypatch.setattr(db.enforcement_ledger, "run_report", _report)
    return calls


def _admin() -> Any:
    return SimpleNamespace(id=9, first_name="Admin")


def test_no_record_replies_without_touching_chats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, ban=None)
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.no_record", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_command_replies_with_a_no_record_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role-less user with no active ban still gets a visible reply.

    An empty rich payload is dropped by the transport, so the command entry
    path must use the same no-record notice as the executor.
    """
    msg, bot = _FakeMsg(), _FakeBot()
    msg.text = "/tcunban 42"
    msg.chat = SimpleNamespace(id=-100, type="supergroup")

    async def _locale(update: object) -> str:
        return "en-US"

    async def _origin(*args: Any, **kwargs: Any) -> bool:
        return True

    async def _target(ctx: Any, args: Any, client: Any) -> tuple[int, str]:
        _ = (ctx, args, client)
        return 42, "T"

    async def _identify(*args: Any, **kwargs: Any) -> Identity:
        _ = (args, kwargs)
        return Identity(kind="user", target_id=42, fname="T")

    async def _no_ban(user_id: int) -> None:
        _ = user_id

    async def _allow(*args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    async def _owner_id(*, fresh: bool = False) -> int:
        _ = fresh
        return 999

    async def _role(uid: int, *, fresh: bool = False) -> str | None:
        _ = (uid, fresh)
        return "developer"

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner_id)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(unban, "locale_for_update", _locale)
    monkeypatch.setattr(unban.guards, "require_federation_origin", _origin)
    monkeypatch.setattr(unban.extraction, "extract_target", _target)
    monkeypatch.setattr(unban.identity, "classify", _identify)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _no_ban)
    monkeypatch.setattr(unban, "resolve_and_check", _allow)

    asyncio.run(unban.cmd_unban(_update(msg, _admin()), _ctx(bot)))

    assert msg.replies == [
        t("unbanning.note.no_record", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_a_final_rank_refusal_blocks_the_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demotion during the group load must not still revoke the ban."""
    calls = _install(monkeypatch)

    async def _deny(*args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        return "rank lost"

    monkeypatch.setattr(unban_executor.guards, "enforcement_refusal", _deny)
    msg, bot = _FakeMsg(), _FakeBot()

    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )

    assert calls["deactivate"] == []
    assert msg.replies == ["rank lost"]


def test_read_failure_replies_retry_and_skips_deactivate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, ban=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )
    assert calls["deactivate"] == []
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.read_fail", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_groups_failure_keeps_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, groups=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )
    assert calls["deactivate"] == []
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.groups_fail", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_deactivate_failure_aborts_before_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, deactivate=RuntimeError("db down"))
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.db_fail", "en-US", user=Safe(user_ref(42, "T")))
    ]


def test_partial_fanout_names_missed_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        groups=[{"chat_id": 1, "title": "Gone"}, {"chat_id": -1, "title": ""}],
    )
    msg, bot = _FakeMsg(), _FakeBot(fail_ids={1})
    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )
    assert "Gone" in msg.replies[-1]


def test_a_run_another_worker_owns_is_reported_as_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, groups=[{"chat_id": 1, "title": "Only"}])

    async def _not_claimed(bot: Any, run_id: int) -> bool:
        return False

    async def _pending(run_id: int) -> dict[str, Any]:
        return {
            "target_count": 1,
            "failed_count": 0,
            "targets": [{"chat_id": 1, "title": "Only", "status": "in_progress"}],
        }

    monkeypatch.setattr(
        unban_executor.moderation_enforcement, "deliver_queued_run", _not_claimed
    )
    monkeypatch.setattr(db.enforcement_ledger, "run_report", _pending)

    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )

    assert "queued" in msg.replies[-1]
    assert bot.unbanned == []


def test_a_settled_run_with_a_missing_group_is_reported_as_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A group that left the federation must not read as a completed unban.

    The queue only records an active connected chat, so the report can be
    terminal while it covers fewer groups than the command requested. The
    shortfall is a pending delivery, and the reply must not claim the
    whole scope was reached.
    """
    _install(monkeypatch, groups=[{"chat_id": 1, "title": "A"}])

    async def _short_report(run_id: int) -> dict[str, Any]:
        return {
            "status": "partial",
            "target_count": 1,
            "failed_count": 0,
            "succeeded_count": 1,
            "skipped_count": 0,
            "targets": [{"chat_id": 1, "title": "A", "status": "succeeded"}],
        }

    monkeypatch.setattr(db.enforcement_ledger, "run_report", _short_report)

    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )

    assert "queued" in msg.replies[-1]


def test_anonymous_admin_cannot_reach_the_unban_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An anonymous admin has no accountable executor for the rank gate."""
    _install(monkeypatch, groups=[])
    msg, bot = _FakeMsg(), _FakeBot()
    asyncio.run(unban_executor.execute_unban(_update(msg, None), _ctx(bot), 42, "T"))
    assert bot.logs == []
    assert msg.replies and "personal account" in msg.replies[-1]


def test_the_anonymous_admin_placeholder_cannot_reach_the_unban_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A placeholder sender has no accountable executor either."""
    _install(monkeypatch, groups=[])
    msg, bot = _FakeMsg(), _FakeBot()
    placeholder = SimpleNamespace(id=ANONYMOUS_BOT_ID)
    asyncio.run(
        unban_executor.execute_unban(_update(msg, placeholder), _ctx(bot), 42, "T")
    )
    assert bot.logs == []
    assert msg.replies and "personal account" in msg.replies[-1]


def test_staff_cleanup_uses_whichever_read_saw_the_role() -> None:
    """A promotion between the two fresh reads still forces the demote.

    The classification and the rank check each read the role. When one
    sees staff and the other does not, the unban must clean up the rank
    rather than skip the gate because the rank check won the race.
    """
    assert unban._cleanup_role(None, Identity("admin", 42, "Target")) == "admin"
    assert (
        unban._cleanup_role("moderator", Identity("user", 42, "Target")) == "moderator"
    )
    assert unban._cleanup_role(None, Identity("user", 42, "Target")) is None


def test_a_promotion_during_the_group_load_forces_the_demote_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target promoted after the entry checks must not keep rank after unban."""
    calls = _install(monkeypatch)
    gates: list[tuple[str, str]] = []

    async def _staff_role(_user_id: int, *, fresh: bool = False) -> str:
        _ = fresh
        return "moderator"

    async def _blocking_gate(
        bot: Any,
        target_id: int,
        target_fname: str,
        target_role: str,
        executor_id: int,
        executor_fname: str,
        *,
        trigger: str = "unban",
    ) -> Any:
        _ = (bot, target_id, target_fname, executor_id, executor_fname)
        gates.append((target_role, trigger))
        return SimpleNamespace(may_proceed=False, value="role_survived")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _staff_role)
    monkeypatch.setattr(unban_executor, "demote_before_unban", _blocking_gate)
    msg, bot = _FakeMsg(), _FakeBot()

    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )

    assert gates == [("moderator", "unban")]
    assert calls["deactivate"] == []
    assert bot.unbanned == []


def test_a_failed_staff_role_read_blocks_the_unban(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolved role is not proof that the target is safe to unban."""
    calls = _install(monkeypatch)

    async def _boom(_user_id: int, *, fresh: bool = False) -> str:
        _ = fresh
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    msg, bot = _FakeMsg(), _FakeBot()

    asyncio.run(
        unban_executor.execute_unban(_update(msg, _admin()), _ctx(bot), 42, "T")
    )

    assert calls["deactivate"] == []
    assert bot.unbanned == []
    assert msg.replies == [
        t("unbanning.note.read_fail", "en-US", user=Safe(user_ref(42, "T")))
    ]
