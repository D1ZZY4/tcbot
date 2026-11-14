# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role assignment against a real PostgreSQL server.

A user holds one active role. The assignment that grants a role revokes
the role it replaces in the same transaction, so the role a user holds
after a promotion is the one the promotion granted. These checks run
against the schema, because the guards that enforce the invariant live
there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.exc import IntegrityError

from tcbot.database import engine as engine_module
from tcbot.database import users_roles
from tcbot.database.base import role_assignments
from tcbot.modules.helper.pipelines import promote_flow
from tests.postgres_support import reset_community, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def roles_db(postgres_db: str) -> AsyncIterator[str]:
    """Start from a community without staff assignments."""
    await reset_community()
    await seed_users(1, 2, 42)
    yield postgres_db
    await reset_community()


class _FakeBot:
    """A bot that accepts the messages the promotion sends."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        _ = kwargs
        self.sent.append((chat_id, text))
        return type("M", (), {"message_id": 1})()


async def test_a_promotion_replaces_the_previous_role(roles_db: str) -> None:
    """A developer promoted to admin holds the admin role afterwards."""
    await users_roles.set_role(42, "developer", 1)

    await users_roles.add_admin(42, 1)

    assert await users_roles.get_effective_role(42, fresh=True) == "admin"
    assert await users_roles.role_count("developer") == 0
    assert await users_roles.role_count("admin") == 1


async def test_the_admin_promotion_keeps_the_granted_role(
    roles_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The promotion path must not revoke the role it just granted.

    The assignment already revoked the role the target held before it,
    in the same transaction. A second revocation afterwards would also
    revoke the admin role it had just written, and the promoted user
    would end up with no role at all while the command reported success.
    """
    await users_roles.set_role(42, "tester", 1)

    async def _send_log(_bot: Any, _text: str, **kwargs: Any) -> Any:
        _ = kwargs
        return None

    monkeypatch.setattr(promote_flow, "send_log", _send_log)

    ok, _text = await promote_flow.assign_admin(
        _FakeBot(),  # type: ignore[arg-type]
        1,
        "Founder",
        42,
        "Target",
        "en-US",
    )

    assert ok is True
    assert await users_roles.get_effective_role(42, fresh=True) == "admin"


async def test_a_demotion_clears_the_role(roles_db: str) -> None:
    """A demote revokes the assignment and leaves no role behind."""
    await users_roles.add_admin(42, 1)

    revoked = await users_roles.remove_role(42)

    assert revoked is True
    assert await users_roles.get_effective_role(42, fresh=True) is None


async def test_a_user_holds_at_most_one_active_role(roles_db: str) -> None:
    """The database refuses a second active role for one user."""
    await users_roles.add_admin(42, 1)

    with pytest.raises(IntegrityError) as excinfo:
        await engine_module.run(
            role_assignments.insert().values(
                user_id=42,
                role_key="developer",
                assigned_by_user_id=1,
                status="active",
            )
        )

    assert "uq_role_assignments_active_user" in (
        engine_module.constraint_name(excinfo.value)
    )
