# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Security contracts for normalized-schema runtime support migrations."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_ACL_MIGRATION = (
    _ROOT
    / "supabase"
    / "migrations"
    / "20261112170000_harden_runtime_support_table_acl.sql"
)


def test_scheduler_and_mtproto_tables_are_backend_only() -> None:
    """Runtime support tables must not rely on an external event trigger for ACLs."""
    source = _RUNTIME_ACL_MIGRATION.read_text(encoding="utf-8").lower()

    for table in ("apscheduler_jobs", "mtproto_state"):
        assert f"alter table public.{table} enable row level security;" in source
        assert f"revoke all privileges on table public.{table}" in source
        assert f"on table public.{table} to service_role;" in source

    assert "from public, anon, authenticated, service_role;" in source
