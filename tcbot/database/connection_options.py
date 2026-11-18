# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""libpq connection options shared by every application connection."""

from __future__ import annotations

# * The application stores and reads timestamps in UTC end to end; the
# * session zone decides how a timestamp without one is read back.
TIMEZONE_OPTION: str = "-c timezone=UTC"


def normalize_database_url(url: str) -> str:
    """Return *url* with the async psycopg driver SQLAlchemy can load.

    Heroku-style providers still hand out ``postgres://``, and a plain
    ``postgresql://`` selects the generic dialect. The application always
    runs psycopg 3, so both forms are rewritten once at the boundary
    instead of every engine guessing which driver is installed.
    """
    url = url.strip()
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def schema_options(schema: str) -> str:
    """Return the libpq options that scope a connection to *schema*.

    The schema is named explicitly because a pooler in transaction mode
    does not carry the search path of the client into the session it
    hands out. Every engine that belongs to the application uses this
    helper, so the async engine, the migration connection, and the
    scheduler job store cannot drift onto different schemas.
    """
    return f"-c search_path={schema} {TIMEZONE_OPTION}"
