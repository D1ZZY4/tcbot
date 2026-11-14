# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""libpq connection options shared by every application connection."""

from __future__ import annotations

# * The application stores and reads timestamps in UTC end to end; the
# * session zone decides how a timestamp without one is read back.
TIMEZONE_OPTION: str = "-c timezone=UTC"


def schema_options(schema: str) -> str:
    """Return the libpq options that scope a connection to *schema*.

    The schema is named explicitly because a pooler in transaction mode
    does not carry the search path of the client into the session it
    hands out. Every engine that belongs to the application uses this
    helper, so the async engine, the migration connection, and the
    scheduler job store cannot drift onto different schemas.
    """
    return f"-c search_path={schema} {TIMEZONE_OPTION}"
