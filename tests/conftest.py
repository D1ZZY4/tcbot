# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Pytest bootstrap - stub all required env vars before tcbot imports fire."""

from __future__ import annotations

import os

# ─────────────────────────── Environment ────────────────────────── #
# ! WARNING: This MUST run before any `from tcbot import ...` happens.
# * conftest.py is imported by pytest before test files, so env values here
# * win over the load_dotenv() call inside tcbot/__init__.py (default override=False).
# * We hard-set every key that Configs.load() reads so real credentials in
# * config.env do not bleed into the test process.

_TEST_ENV: dict[str, str] = {
    "BOT_TOKEN": "test:token",
    "MONGODB_URI": "mongodb://invalid.test:0",
    # * Opt-in to PTB timedelta API early so RetryAfter.__init__ does not
    # * emit PTBDeprecationWarning about retry_after becoming datetime.timedelta.
    "PTB_TIMEDELTA": "1",
    "DB_NAME": "tcbot_test",
    "COMMUNITY_NAME": "Test Federation",
    "OWNER_ID": "123456",
    "PREFIXES": '["/", "!", "."]',
    "PORT": "5000",
    "MAIN_GROUP": "-1001000000099",
    "MAIN_CHANNEL": "-1001000000098",
    "EXTEND_GROUP": "",
    "PROOFS": "-1001000000002",
    "LOGS": "-1001000000001",
    "LOGS_ERRORS": "",
    "APPEALS": "-1001000000003",
    "APPEAL_LOG_HANDLE": "@TestLogs",
    "APPEAL_DISCUSSION_TOPIC": "0",
    "PROOF_TIMEOUT_SECONDS": "100",
    "APPEAL_TIMEOUT_SECONDS": "600",
    "ALBUM_DEBOUNCE_SECONDS": "2",
    "LOG_LEVEL": "INFO",
    "MODULES_LOAD": "",
    "MODULES_NO_LOAD": "",
}

for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value
