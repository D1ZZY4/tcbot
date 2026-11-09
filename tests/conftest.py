# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared pytest fixtures: mirror production logging startup for every test session."""

from __future__ import annotations

import os

# * Dummy import-time env: tcbot/__init__ loads Configs at import, so the
# * suite must not depend on CI-only env to collect. setdefault keeps real
# * CI/local values when already present.
os.environ.setdefault("BOT_TOKEN", "000000:dummy-token-for-lint000000000000000")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("OWNER_ID", "1")

import pytest

from tcbot.utils.logger import setup as setup_logging


@pytest.fixture(scope="session", autouse=True)
def _production_logging() -> None:
    """Install the production logging setup once, like main() does at startup.

    Modules log through structlog (stdlib-backed), which only reaches
    caplog and the Telegram error handler after configure() runs.
    Without this, records would fall back to structlog's default
    print-to-stdout facility and tests asserting on log output fail.
    """
    setup_logging()
