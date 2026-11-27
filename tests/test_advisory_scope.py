# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Advisory lock scopes must isolate deployments that share a database."""

from __future__ import annotations

from tcbot.database.connection_options import advisory_scope


def test_the_schema_is_part_of_every_lock_scope() -> None:
    """Two project schemas must never contend on the same advisory lock."""
    public = advisory_scope("public", "tcbot:expiry")
    development = advisory_scope("development", "tcbot:expiry")

    assert public == "public:tcbot:expiry"
    assert development == "development:tcbot:expiry"
    assert public != development
