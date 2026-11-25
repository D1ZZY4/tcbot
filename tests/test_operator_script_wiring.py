# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Operator scripts keep their scratch work out of the deployment schema."""

from __future__ import annotations

from scripts.check_migration import CHECK_SCHEMA, _alembic_config


def test_migration_check_pins_the_alembic_schema() -> None:
    """Alembic must receive the scratch schema, not fall back to public."""
    config = _alembic_config("postgresql://user:pass@localhost/db")
    assert config.get_main_option("db_schema") == CHECK_SCHEMA
