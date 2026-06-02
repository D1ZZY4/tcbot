# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for promote_flow: Promote class role assignment and request logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from tcbot.modules.helper.workflows import promote_flow
from tcbot.modules.helper.workflows.promote_flow import Promote


def _bot(**extra) -> SimpleNamespace:
    return SimpleNamespace(send_message=AsyncMock(), **extra)


# ─────────────────── Promote.available_roles_for ────────────────── #


def test_available_roles_for_founder() -> None:
    assert Promote.available_roles_for("founder") == ["admin", "developer", "tester"]


def test_available_roles_for_admin() -> None:
    assert Promote.available_roles_for("admin") == ["developer", "tester"]


def test_available_roles_for_other_returns_empty() -> None:
    assert Promote.available_roles_for("developer") == []
    assert Promote.available_roles_for("tester") == []
    assert Promote.available_roles_for("") == []


# ─────────────────────── Promote.execute guards ─────────────────── #


async def test_execute_rejects_founder_target(monkeypatch) -> None:
    ok, msg = await Promote.execute(
        _bot(), 10, "Admin", "founder", 99, "Target", "founder", "admin"
    )
    assert not ok
    assert "Founder" in msg


async def test_execute_rejects_same_or_higher_role(monkeypatch) -> None:
    """Target already holds the same role or higher: reject without DB calls."""
    monkeypatch.setattr(
        promote_flow.db.users_roles,
        "role_rank",
        Mock(
            side_effect=lambda r: {
                "founder": 4,
                "admin": 3,
                "developer": 2,
                "tester": 1,
            }.get(r, 0)
        ),
    )
    ok, msg = await Promote.execute(
        _bot(), 10, "Admin", "founder", 99, "Target", "developer", "developer"
    )
    assert not ok
    assert "already holds" in msg.lower()


async def test_execute_non_staff_cannot_assign_subrole(monkeypatch) -> None:
    monkeypatch.setattr(
        promote_flow.db.users_roles,
        "role_rank",
        Mock(side_effect=lambda r: {"developer": 2, "tester": 1}.get(r, 0)),
    )
    ok, msg = await Promote.execute(
        _bot(), 10, "Dev", "developer", 99, "Target", None, "tester"
    )
    assert not ok
    assert "permission" in msg.lower()


# ─────────────────────── Promote.execute paths ──────────────────── #


async def test_execute_admin_promoting_admin_creates_request(monkeypatch) -> None:
    """Admin cannot directly assign Admin: triggers request_admin flow."""
    monkeypatch.setattr(
        promote_flow.db.users_roles,
        "role_rank",
        Mock(side_effect=lambda r: {"admin": 3, "tester": 1}.get(r, 0)),
    )
    request_admin = AsyncMock(return_value=(True, "Submitted"))
    monkeypatch.setattr(Promote, "request_admin", request_admin)

    ok, msg = await Promote.execute(
        _bot(), 10, "Admin", "admin", 99, "Target", "tester", "admin"
    )

    request_admin.assert_awaited_once()
    assert ok
    assert "Submitted" in msg


async def test_execute_founder_assigns_admin(monkeypatch) -> None:
    monkeypatch.setattr(
        promote_flow.db.users_roles,
        "role_rank",
        Mock(side_effect=lambda r: {"admin": 3, "tester": 1}.get(r, 0)),
    )
    assign_admin = AsyncMock(return_value=(True, "Done."))
    monkeypatch.setattr(Promote, "_assign_admin", assign_admin)

    ok, msg = await Promote.execute(
        _bot(), 10, "Founder", "founder", 99, "Target", "tester", "admin"
    )

    assign_admin.assert_awaited_once()
    assert ok


async def test_execute_assigns_developer_subrole(monkeypatch) -> None:
    monkeypatch.setattr(
        promote_flow.db.users_roles,
        "role_rank",
        Mock(side_effect=lambda r: {"developer": 2, "tester": 1}.get(r, 0)),
    )
    assign_subrole = AsyncMock(return_value=(True, "Done."))
    monkeypatch.setattr(Promote, "_assign_subrole", assign_subrole)

    ok, _ = await Promote.execute(
        _bot(), 10, "Admin", "admin", 99, "Target", None, "developer"
    )

    assign_subrole.assert_awaited_once()
    assert ok


# ──────────────────── Promote._assign_admin ─────────────────────── #


async def test_assign_admin_clears_subrole_first(monkeypatch) -> None:
    """When target holds developer/tester, remove_role is called before add_admin."""
    add_admin = AsyncMock()
    remove_role = AsyncMock()
    upsert_user = AsyncMock()
    monkeypatch.setattr(promote_flow.db.users_roles, "add_admin", add_admin)
    monkeypatch.setattr(promote_flow.db.users_roles, "remove_role", remove_role)
    monkeypatch.setattr(promote_flow.db.users_cache, "upsert_user", upsert_user)
    monkeypatch.setattr(promote_flow.parse_logmsg, "promoted", Mock(return_value="log"))

    bot = _bot()
    ok, msg = await Promote._assign_admin(bot, 10, "Admin", 99, "Target", "developer")

    remove_role.assert_awaited_once_with(99)
    add_admin.assert_awaited_once()
    assert ok
    assert "Admin" in msg


async def test_assign_admin_without_prior_subrole(monkeypatch) -> None:
    """When target has no subrole, remove_role is NOT called."""
    add_admin = AsyncMock()
    remove_role = AsyncMock()
    upsert_user = AsyncMock()
    monkeypatch.setattr(promote_flow.db.users_roles, "add_admin", add_admin)
    monkeypatch.setattr(promote_flow.db.users_roles, "remove_role", remove_role)
    monkeypatch.setattr(promote_flow.db.users_cache, "upsert_user", upsert_user)
    monkeypatch.setattr(promote_flow.parse_logmsg, "promoted", Mock(return_value="log"))

    bot = _bot()
    ok, _ = await Promote._assign_admin(bot, 10, "Admin", 99, "Target", None)

    remove_role.assert_not_awaited()
    assert ok


# ──────────────────── Promote._assign_subrole ───────────────────── #


async def test_assign_subrole_rejects_existing_admin(monkeypatch) -> None:
    """Assigning developer to an existing admin is rejected."""
    ok, msg = await Promote._assign_subrole(
        _bot(), 10, "Admin", 99, "Target", "admin", "developer"
    )
    assert not ok
    assert "Demote" in msg


async def test_assign_subrole_sets_role_and_notifies(monkeypatch) -> None:
    set_role = AsyncMock()
    remove_role = AsyncMock()
    upsert_user = AsyncMock()
    monkeypatch.setattr(promote_flow.db.users_roles, "set_role", set_role)
    monkeypatch.setattr(promote_flow.db.users_roles, "remove_role", remove_role)
    monkeypatch.setattr(promote_flow.db.users_cache, "upsert_user", upsert_user)
    monkeypatch.setattr(promote_flow.parse_logmsg, "promoted", Mock(return_value="log"))

    bot = _bot()
    ok, msg = await Promote._assign_subrole(
        bot, 10, "Admin", 99, "Target", None, "tester"
    )

    set_role.assert_awaited_once_with(99, "tester", 10)
    assert ok
    # User notified via send_message (target_id + log channel)
    assert bot.send_message.await_count >= 1


# ──────────────────── Promote.request_admin ─────────────────────── #


async def test_request_admin_rejects_duplicate(monkeypatch) -> None:
    monkeypatch.setattr(
        promote_flow.db.queues_db,
        "get_request",
        AsyncMock(return_value={"request_id": "r1"}),
    )

    ok, msg = await Promote.request_admin(_bot(), 10, 99, "Target")

    assert not ok
    assert "pending" in msg.lower()


async def test_request_admin_notifies_owner_via_dm(monkeypatch) -> None:
    """Happy path: request enqueued and owner notified by DM."""
    monkeypatch.setattr(
        promote_flow.db.queues_db, "get_request", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        promote_flow.db.queues_db,
        "enqueue",
        AsyncMock(return_value="req-001"),
    )
    monkeypatch.setattr(
        promote_flow.db.users_roles, "get_owner_id", AsyncMock(return_value=777)
    )
    monkeypatch.setattr(
        promote_flow.parse_logmsg, "promote_request_log", Mock(return_value="req log")
    )
    monkeypatch.setattr(
        promote_flow.keyboards, "promo_decision_kb", Mock(return_value=None)
    )

    bot = _bot()
    ok, msg = await Promote.request_admin(bot, 10, 99, "Target")

    assert ok
    assert "Submitted" in msg
    # Owner DM sent (first send_message call is to owner_id=777)
    first_call = bot.send_message.await_args_list[0]
    assert first_call.args[0] == 777
