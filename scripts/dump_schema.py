#!/usr/bin/env python3
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Export the community schema of a database into the schema files.

The schema of the community lives in ``tcbot/database/schema`` as SQL:
the views, the functions, the triggers, the access policies, and the
reference data. This tool writes those files from a live catalog, so
the repository can be refreshed whenever the database changes.

The tool reads the catalog through ``pg_dump``, because the dump is the
canonical description of a PostgreSQL schema: it emits the views, the
functions, the triggers, the policies, and the grants exactly as the
server stores them. The dump is split by the object kind it announces,
and the schema of the database is replaced by the ``%SCHEMA%``
placeholder, so the same files apply to the deployment and to the schema
an integration test owns.

Usage::

    uv run python scripts/dump_schema.py
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

import psycopg
from dotenv import find_dotenv, load_dotenv
from psycopg import sql

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tcbot import DB_SCHEMAS  # noqa: E402
from tcbot.database.schema.loader import split_statements  # noqa: E402

# * The directory the schema files live in.
SCHEMA_DIR: Path = Path(__file__).resolve().parents[1] / "tcbot" / "database" / "schema"

# * The marker ``pg_dump`` writes before every object.
_OBJECT_MARKER = re.compile(r"^-- Name: (?P<name>.+?); Type: (?P<kind>[A-Z ]+);")

# * The object kinds that belong to the schema files, and the file each
# * kind is written to. The access policies are not in the list: they
# * are a decision of the project rather than a snapshot of the
# * catalog, so ``policies.sql`` is maintained by hand.
_FILES: dict[str, str] = {
    "VIEW": "views.sql",
    "FUNCTION": "functions.sql",
    "TRIGGER": "triggers.sql",
}


def _pg_dump_binary() -> str:
    """Return the ``pg_dump`` binary to use.

    The dump refuses to run against a newer server, so the newest
    ``pg_dump`` the machine carries is preferred. The candidates are
    ordered by their version number, not by their name, because the
    store paths carry the version in the middle of the name.
    """
    candidates = list(Path("/nix/store").glob("*postgresql-1*/bin/pg_dump"))
    ordered = sorted(candidates, key=_store_version, reverse=True)
    for candidate in ordered:
        if os.access(candidate, os.X_OK):
            return str(candidate)
    found = shutil.which("pg_dump")
    if found is None:
        raise SystemExit("pg_dump is not available on this machine")
    return found


def _store_version(path: Path) -> tuple[int, ...]:
    """Return the PostgreSQL version a store path carries."""
    match = re.search(r"postgresql-(\d+(?:\.\d+)*)", str(path))
    if match is None:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def _database_url() -> str:
    """Return the database URL from the environment or the local config."""
    load_dotenv(find_dotenv("config.env") or find_dotenv(".env"))
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is required in the environment or config.env")
    return url


def _dump(url: str, schema: str) -> str:
    """Return the schema-only dump of *schema* in *url*.

    The password is passed through ``PGPASSWORD`` rather than the argument
    vector, so it never appears in the process listing. It is also scrubbed
    from any error text the dump produces.
    """
    parsed = urlsplit(url)
    password = unquote(parsed.password) if parsed.password else None
    user = f"{parsed.username}@" if parsed.username else ""
    safe_netloc = user + parsed.netloc.rsplit("@", 1)[-1]
    safe_url = urlunsplit(
        (parsed.scheme, safe_netloc, parsed.path, parsed.query, parsed.fragment)
    )
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    command = [
        _pg_dump_binary(),
        "--schema-only",
        f"--schema={schema}",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        safe_url,
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, env=env
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        if password:
            detail = detail.replace(password, "***")
        raise SystemExit(f"pg_dump failed: {detail}")
    return result.stdout


def _split(dump: str) -> dict[str, list[str]]:
    """Return the statements of the dump, grouped by the file they belong to."""
    grouped: dict[str, list[str]] = {name: [] for name in set(_FILES.values())}
    kind: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if kind is None:
            return
        name = _FILES.get(kind.strip())
        if name is None:
            return
        statement = "\n".join(buffer).strip()
        if statement:
            grouped[name].append(statement)

    for line in dump.splitlines():
        marker = _OBJECT_MARKER.match(line)
        if marker:
            flush()
            kind = marker.group("kind")
            buffer = []
            continue
        if kind is None:
            continue
        if line.startswith("--") and not line.startswith("-- Name:"):
            continue
        buffer.append(line)
    flush()
    return grouped


def _validate_schema(schema: str) -> str:
    """Return *schema* when it is one of the three schemas the project owns.

    The dump reads one schema and rewrites the committed files from it. A
    free-form name can point at an unrelated schema whose dump contains none
    of this project's objects, which would silently empty the files.
    """
    if schema not in DB_SCHEMAS:
        raise SystemExit(
            f"Refusing to export schema {schema!r}; expected one of "
            f"{', '.join(sorted(DB_SCHEMAS))}."
        )
    return schema


def _committed_minimums() -> dict[str, int]:
    """Count statements in the committed files the exporter would overwrite."""

    def _count(relative: str) -> int:
        return len(
            split_statements((SCHEMA_DIR / relative).read_text(encoding="utf-8"))
        )

    functions = sum(
        _count(str(path.relative_to(SCHEMA_DIR)))
        for path in sorted((SCHEMA_DIR / "functions").glob("*.sql"))
    )
    return {
        "views.sql": _count("views.sql"),
        "functions.sql": functions,
        "triggers.sql": _count("triggers.sql"),
        "seed.sql": _count("seed.sql"),
    }


def _require_export(
    grouped: dict[str, list[str]],
    seed: list[str],
    minimums: dict[str, int] | None = None,
) -> None:
    """Refuse a dump smaller than the committed schema.

    A non-empty dump of a partial schema must not replace complete files with
    a subset: the missing objects would disappear from every deployment that
    applies these files.
    """
    if minimums is None:
        minimums = _committed_minimums()
    short = [
        f"{name}: {len(statements)} of {minimums.get(name, 1)}"
        for name, statements in (
            ("views.sql", grouped["views.sql"]),
            ("functions.sql", grouped["functions.sql"]),
            ("triggers.sql", grouped["triggers.sql"]),
            ("seed.sql", seed),
        )
        if len(statements) < minimums.get(name, 1)
    ]
    if short:
        raise SystemExit(
            "The dump is smaller than the committed schema (" + ", ".join(short) + "). "
            "The committed schema files were not changed."
        )


def _portable(statement: str, schema: str) -> str:
    """Return *statement* with the schema of the database replaced.

    The dumped statements name the schema of the database. The files
    must apply to any schema, so the name becomes the placeholder, and
    the schema list of a function names it too.

    The objects are created with the replace form, so applying the
    files twice does not fail on an object that already exists.
    """
    statement = statement.replace(f"'{schema}'", "'%SCHEMA%'")
    statement = re.sub(rf"\b{re.escape(schema)}\.", "%SCHEMA%.", statement)
    statement = re.sub(
        r"^CREATE VIEW ",
        "CREATE OR REPLACE VIEW ",
        statement,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"^CREATE FUNCTION ",
        "CREATE OR REPLACE FUNCTION ",
        statement,
        flags=re.IGNORECASE,
    )


_FUNCTION_NAME = re.compile(r"FUNCTION\s+%SCHEMA%\.([A-Za-z0-9_]+)")

# * The schema function files, split by domain so no file exceeds the budget.
_MODERATION_PREFIXES = (
    "moderation_",
    "assign_moderation",
    "enforce_moderation",
    "validate_moderation",
    "guard_moderation",
    "prepare_moderation",
    "refresh_moderation",
    "queue_revoke",
    "reconcile_stuck",
    "expire_due_moderation",
    "enqueue_reconcile",
)
_AUTOMATION_PREFIXES = (
    "automation_",
    "guard_automation",
    "validate_automation",
    "refresh_automation",
    "guard_broadcast",
    "prepare_broadcast",
    "queue_broadcast",
    "refresh_broadcast",
    "validate_broadcast",
)
_SCHEDULER_PREFIXES = (
    "scheduled_",
    "scheduler_",
    "run_scheduled",
    "guard_scheduled",
    "audit_scheduler",
    "safe_duration",
)
_MAINTENANCE_PREFIXES = (
    "apply_retention",
    "retention_window",
    "sweep_retention",
    "request_user_erasure",
    "process_user_erasure",
    "sweep_pending",
    "rls_auto_enable",
    "assert_least_privilege",
)
_RBAC_PREFIXES = (
    "actor_has_permission",
    "expire_due_role",
    "guard_promotion",
    "guard_role",
    "guard_system_role",
    "prepare_role",
    "promotion_requests",
)
_IDENTITY_PREFIXES = (
    "ensure_connected",
    "guard_community",
    "guard_join",
    "repoint_chat",
    "guard_telegram",
    "validate_connected",
    "prevent_historical",
    "set_updated_at",
)
_AUDIT_PREFIXES = ("guard_appeal_ban_target", "validate_audit_event_entity")
_MTPROTO_PREFIXES = ("mtproto_state_", "prune_expired_mtproto_state")


def _function_domain(name: str) -> str:
    domains = (
        (_MTPROTO_PREFIXES, "mtproto"),
        (_AUDIT_PREFIXES, "moderation_audit"),
        (_MODERATION_PREFIXES, "moderation"),
        (_AUTOMATION_PREFIXES, "automation"),
        (_SCHEDULER_PREFIXES, "scheduler"),
        (_MAINTENANCE_PREFIXES, "maintenance"),
        (_RBAC_PREFIXES, "rbac"),
        (_IDENTITY_PREFIXES, "identity"),
    )
    for prefixes, domain in domains:
        if name.startswith(prefixes):
            return domain
    return "core"


def _function_groups(statements: list[str]) -> dict[str, list[str]]:
    """Route each function to its domain file."""
    grouped: dict[str, list[str]] = {}
    for statement in statements:
        match = _FUNCTION_NAME.search(statement)
        name = match.group(1) if match else ""
        grouped.setdefault(_function_domain(name), []).append(statement)
    return grouped


def _write(name: str, statements: list[str], schema: str, header: str) -> None:
    """Write one schema file."""
    body = "\n\n".join(_portable(statement, schema) for statement in statements)
    path = SCHEMA_DIR / name
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    print(f"wrote {path} ({len(statements)} objects)")


# * The reference tables of the community, and the columns of each that
# * are part of the contract. The runtime columns of a table, such as
# * the counters of the job registry, are not part of the seed.
_SEED_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "community_settings",
        # * Mutable operator configuration, not reference data: regenerating
        # * the seed must not reset values configured at runtime.
        "INSERT INTO %SCHEMA%.community_settings "
        "(singleton_key, community, description, default_locale, timezone, settings) "
        "VALUES {values} ON CONFLICT (singleton_key) DO NOTHING",
        (
            "singleton_key",
            "community",
            "description",
            "default_locale",
            "timezone",
            "settings",
        ),
    ),
    (
        "role_definitions",
        "INSERT INTO %SCHEMA%.role_definitions "
        "(role_key, display_name, priority, is_system, description) "
        "VALUES {values} ON CONFLICT (role_key) DO UPDATE SET "
        "display_name = EXCLUDED.display_name, priority = EXCLUDED.priority, "
        "is_system = EXCLUDED.is_system, description = EXCLUDED.description",
        ("role_key", "display_name", "priority", "is_system", "description"),
    ),
    (
        "permission_definitions",
        "INSERT INTO %SCHEMA%.permission_definitions "
        "(permission_key, resource, description) "
        "VALUES {values} ON CONFLICT (permission_key) DO UPDATE SET "
        "resource = EXCLUDED.resource, description = EXCLUDED.description",
        ("permission_key", "resource", "description"),
    ),
    (
        "role_permissions",
        "INSERT INTO %SCHEMA%.role_permissions (role_key, permission_key) "
        "VALUES {values} ON CONFLICT (role_key, permission_key) DO NOTHING",
        ("role_key", "permission_key"),
    ),
    (
        "retention_policies",
        "INSERT INTO %SCHEMA%.retention_policies "
        "(target_table, data_class, retention_days, time_column, is_enabled, rationale) "
        "VALUES {values} ON CONFLICT (target_table) DO UPDATE SET "
        "data_class = EXCLUDED.data_class, retention_days = EXCLUDED.retention_days, "
        "time_column = EXCLUDED.time_column, is_enabled = EXCLUDED.is_enabled, "
        "rationale = EXCLUDED.rationale",
        (
            "target_table",
            "data_class",
            "retention_days",
            "time_column",
            "is_enabled",
            "rationale",
        ),
    ),
    (
        "scheduled_jobs",
        "INSERT INTO %SCHEMA%.scheduled_jobs "
        "(job_key, job_kind, description, schedule_spec, timeout_seconds, "
        "is_enabled, idempotency_scope, job_owner) "
        "VALUES {values} ON CONFLICT (job_key) DO UPDATE SET "
        "job_kind = EXCLUDED.job_kind, description = EXCLUDED.description, "
        "schedule_spec = EXCLUDED.schedule_spec, "
        "timeout_seconds = EXCLUDED.timeout_seconds, "
        "is_enabled = EXCLUDED.is_enabled, "
        "idempotency_scope = EXCLUDED.idempotency_scope, "
        "job_owner = EXCLUDED.job_owner",
        (
            "job_key",
            "job_kind",
            "description",
            "schedule_spec",
            "timeout_seconds",
            "is_enabled",
            "idempotency_scope",
            "job_owner",
        ),
    ),
)


def _literal(value: object) -> str:
    """Return *value* as a quoted SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text_value = str(value)
    return "'" + text_value.replace("'", "''") + "'"


def _seed_statements(url: str, schema: str) -> list[str]:
    """Return the reference data of the community as upsert statements."""
    statements: list[str] = []
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for table, template, columns in _SEED_TABLES:
            # * The identifiers come from the catalog of this project, but
            # * quoting them keeps the statement correct for a schema name
            # * that needs it.
            query = sql.SQL("SELECT {} FROM {}").format(
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                sql.Identifier(schema, table),
            )
            cur.execute(query)
            rows = cur.fetchall()
            if not rows:
                continue
            values = ",\n    ".join(
                "(" + ", ".join(_literal(value) for value in row) + ")" for row in rows
            )
            statements.append(template.format(values=values))
    return statements


def main() -> int:
    """Write the schema files from the configured database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="public", help="the schema to export")
    args = parser.parse_args()

    schema = _validate_schema(args.schema)
    url = _database_url()
    dump = _dump(url, schema)
    grouped = _split(dump)
    function_files = _function_groups(grouped["functions.sql"])
    seed = _seed_statements(url, schema)
    _require_export(grouped, seed)

    _write(
        "views.sql",
        grouped["views.sql"],
        schema,
        "-- The read-only views of the community.",
    )
    for domain, statements in sorted(function_files.items()):
        _write(
            f"functions/{domain}.sql",
            statements,
            schema,
            f"-- Database functions: {domain}.",
        )
    _write(
        "triggers.sql",
        grouped["triggers.sql"],
        schema,
        "-- The triggers that protect the invariants the schema cannot express.",
    )
    _write(
        "seed.sql",
        seed,
        schema,
        "-- The reference data of the community: the role catalog, the "
        "permission catalog,\n-- the retention contract, and the job registry.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
