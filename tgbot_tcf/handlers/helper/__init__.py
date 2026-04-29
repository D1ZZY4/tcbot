# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Per-request helpers shared by the thin Telegram handlers.

* :mod:`.enforce` — cross-group ban / unban enforcement.
* :mod:`.auth` — guard helpers that reply ``"You are not authorized."``
  on rejection so the call site can early-return on a single line.
* :mod:`.targets` — convenience wrapper around ``resolve_target`` that
  replies with the spec-locked ``"Cannot resolve user."`` on failure.
* :mod:`.messaging` — small swallowing wrappers around ``edit_message_text``
  and ``send_message`` that survive Telegram errors gracefully.
"""
from . import auth, enforce, messaging, targets
from .enforce import enforce_ban_across_groups, enforce_unban_across_groups

__all__ = [
    "auth",
    "enforce",
    "messaging",
    "targets",
    "enforce_ban_across_groups",
    "enforce_unban_across_groups",
]
