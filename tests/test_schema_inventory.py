# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The schema inventory is generated from the declared metadata."""

from __future__ import annotations

from tcbot.database.base import SCHEMA_TABLES, metadata


def test_the_inventory_matches_the_declared_metadata() -> None:
    declared = set(metadata.tables)
    assert set(SCHEMA_TABLES) == declared


def test_the_inventory_has_no_duplicates() -> None:
    assert len(SCHEMA_TABLES) == len(set(SCHEMA_TABLES))
