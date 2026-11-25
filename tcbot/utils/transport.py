# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Application-level Telegram deadlines used by callers of the client."""

from __future__ import annotations

# * Budget for a single Telegram lookup (get_chat, get_chat_member).
# * It belongs with the other transport constants: a lookup is a
# * transport call, not a clock concern.
TELEGRAM_LOOKUP_TIMEOUT: float = 3.0

# * Bound on one Telegram state-changing call (ban, mute, edit). It keeps a
# * stalled call from holding a worker slot until the transport write timeout.
TELEGRAM_ACTION_TIMEOUT: float = 20.0
