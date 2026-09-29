# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared tunables for the group connection flow."""

from __future__ import annotations

# * Connect-flow runtime prose lives in connecting.toml [state];
# * only the permission-code tuple stays in code.

_REQUIRED_PERMS: tuple[str, ...] = (
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
)

# * Cap per-list replay rows: enforcing an unbounded backlog would hold the
# * owner prompt for minutes on a huge federation. Truncation marks the run
# * blind so the owner re-syncs instead of trusting a partial replay.
_REPLAY_CAP: int = 500
