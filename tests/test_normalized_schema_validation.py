# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Preflight contracts for the read-only normalized database runtime."""

from __future__ import annotations

from typing import Any

import pytest

from tcbot.database import migrations


class _FakeResult:
    """Small result object for the SQLAlchemy calls made by the validator."""

    def __init__(
        self,
        *,
        rows: list[tuple[Any, ...]] | None = None,
        scalar_values: list[str] | None = None,
        mapping: dict[str, int] | None = None,
        scalar: str | None = None,
    ) -> None:
        self._rows = rows or []
        self._scalar_values = scalar_values or []
        self._mapping = mapping or {}
        self._scalar = scalar

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[str]:
        return self._scalar_values

    def mappings(self) -> _FakeResult:
        return self

    def one(self) -> dict[str, int]:
        return self._mapping

    def scalar_one_or_none(self) -> str | None:
        return self._scalar


class _FakeInspector:
    """Inspector exposing the expected normalized runtime relation contract."""

    def __init__(self, *, omit_table: str | None = None) -> None:
        self._tables = set(migrations._NORMALIZED_REQUIRED_TABLES)
        if omit_table is not None:
            self._tables.discard(omit_table)

    def get_table_names(self, *, schema: str) -> list[str]:
        assert schema == "public"
        return sorted(self._tables)

    def get_view_names(self, *, schema: str) -> list[str]:
        assert schema == "public"
        return sorted(migrations._NORMALIZED_REQUIRED_VIEWS)

    def get_columns(self, table_name: str, *, schema: str) -> list[dict[str, str]]:
        assert schema == "public"
        columns = {
            "federations": {"id", "slug"},
            "telegram_users": {"user_id", "is_bot"},
            "role_definitions": {"role_key", "priority"},
            "role_assignments": {
                "federation_id",
                "user_id",
                "role_key",
                "assigned_by_user_id",
                "assigned_at",
                "status",
                "expires_at",
                "revoked_at",
                "revoked_by_user_id",
            },
            "permission_definitions": {"permission_key", "resource"},
            "role_permissions": {"role_key", "permission_key"},
            "apscheduler_jobs": {"id", "next_run_time", "job_state"},
            "mtproto_state": {"id", "value", "owner", "expires_at"},
        }
        return [{"name": name} for name in columns[table_name]]


class _FakeConnection:
    """Return controlled rows for the normalized startup preflight queries."""

    def __init__(
        self,
        *,
        federation_rows: list[tuple[int]] | None = None,
        roles: list[str] | None = None,
        security: dict[str, int] | None = None,
        event_trigger: str | None = "O",
    ) -> None:
        self.federation_rows = federation_rows if federation_rows is not None else [(1,)]
        self.roles = roles if roles is not None else sorted(
            migrations._NORMALIZED_REQUIRED_ROLES
        )
        self.security = security or {
            "rls_disabled": 0,
            "client_grants": 0,
            "missing_backend_grants": 0,
            "missing_view_grants": 0,
            "insecure_views": 0,
            "insecure_sequences": 0,
            "exposed_functions": 0,
        }
        self.event_trigger = event_trigger

    def execute(self, statement: Any, _params: dict[str, Any] | None = None) -> _FakeResult:
        query = str(statement)
        if "SELECT id FROM public.federations" in query:
            return _FakeResult(rows=self.federation_rows)
        if "SELECT role_key FROM public.role_definitions" in query:
            return _FakeResult(scalar_values=self.roles)
        if "AS rls_disabled" in query:
            return _FakeResult(mapping=self.security)
        if "SELECT evtenabled FROM pg_event_trigger" in query:
            return _FakeResult(scalar=self.event_trigger)
        raise AssertionError(f"Unexpected validator query: {query}")


@pytest.fixture(autouse=True)
def _normalized_inspector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace PostgreSQL inspection with a predictable schema snapshot."""
    inspector = _FakeInspector()
    monkeypatch.setattr(migrations, "inspect", lambda _connection: inspector)


def test_normalized_preflight_accepts_a_complete_secure_schema() -> None:
    """A complete schema with one active federation and secure grants passes."""
    migrations.validate_normalized_schema(_FakeConnection(), "tcf")


def test_normalized_preflight_rejects_missing_domain_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial schema fails before any runtime query can run."""
    inspector = _FakeInspector(omit_table="moderation_actions")
    monkeypatch.setattr(migrations, "inspect", lambda _connection: inspector)

    with pytest.raises(RuntimeError, match="table:moderation_actions"):
        migrations.validate_normalized_schema(_FakeConnection(), "tcf")


def test_normalized_preflight_rejects_missing_federation() -> None:
    """The configured federation slug must resolve exactly once and be active."""
    connection = _FakeConnection(federation_rows=[])

    with pytest.raises(RuntimeError, match="exactly one active federation"):
        migrations.validate_normalized_schema(connection, "missing")


def test_normalized_preflight_rejects_missing_system_roles() -> None:
    """Every mapped legacy tier must exist before the bot can start."""
    connection = _FakeConnection(roles=["owner", "admin", "moderator"])

    with pytest.raises(RuntimeError, match="developer"):
        migrations.validate_normalized_schema(connection, "tcf")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("rls_disabled", 1),
        ("client_grants", 1),
        ("missing_backend_grants", 1),
        ("missing_view_grants", 1),
        ("insecure_views", 1),
        ("insecure_sequences", 1),
        ("exposed_functions", 1),
    ],
)
def test_normalized_preflight_rejects_insecure_schema(
    key: str,
    value: int,
) -> None:
    """Client access, missing backend access, and insecure objects fail closed."""
    security = {
        "rls_disabled": 0,
        "client_grants": 0,
        "missing_backend_grants": 0,
        "missing_view_grants": 0,
        "insecure_views": 0,
        "insecure_sequences": 0,
        "exposed_functions": 0,
    }
    security[key] = value

    with pytest.raises(RuntimeError, match="security validation failed"):
        migrations.validate_normalized_schema(
            _FakeConnection(security=security),
            "tcf",
        )


def test_normalized_preflight_requires_enabled_ddl_security_trigger() -> None:
    """Future public DDL must retain the event trigger that enables RLS."""
    connection = _FakeConnection(event_trigger="D")

    with pytest.raises(RuntimeError, match="enabled ensure_rls event trigger"):
        migrations.validate_normalized_schema(connection, "tcf")
