# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Pytest configuration: stub required environment variables before import.

The :mod:`tgbot_tcf` package reads ``BOT_TOKEN`` and ``MONGODB_URI`` at
import time (and instantiates a Motor client). Tests run offline and never
talk to a real bot or database, so we provide harmless placeholder values
before any test module triggers the import.
"""
from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "tcf_bot_test")
