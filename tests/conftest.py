# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Pytest bootstrap - stub all required env vars before tcbot imports fire.
"""

from __future__ import annotations

import os
import pytest


## ── Environment ───────────────────────────────────────────────────────────

os.environ.setdefault("BOT_TOKEN",       "test:token")
os.environ.setdefault("MONGODB_URI",     "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME",         "tcbot_test")
os.environ.setdefault("COMMUNITY_NAME",  "𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯")
os.environ.setdefault("OWNER_ID",        "123456")
os.environ.setdefault("LOGS",            "-1001000000001")
os.environ.setdefault("PROOFS",          "-1001000000002")
os.environ.setdefault("APPEALS",         "-1001000000003")


## ── Pytest ────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.asyncio
