# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group connection flow: in-group join prompt, permission check, pending monitoring."""

from __future__ import annotations

from tcbot import cfg
from tcbot.modules.helper.workflows.connected_flow.bot_added import (
    ConnectionAddedMixin,
)
from tcbot.modules.helper.workflows.connected_flow.connection import BuildConnection
from tcbot.modules.helper.workflows.connected_flow.harvest import (
    _harvest_admin_identities,
    _harvest_tasks,
    drain_harvest_tasks,
)
from tcbot.modules.helper.workflows.connected_flow.join_decision import (
    ConnectionDecisionMixin,
)
from tcbot.modules.helper.workflows.connected_flow.shared import (
    _REPLAY_CAP,
    _REQUIRED_PERMS,
)

__all__ = [
    "_REPLAY_CAP",
    "_REQUIRED_PERMS",
    "BuildConnection",
    "ConnectionAddedMixin",
    "ConnectionDecisionMixin",
    "_harvest_admin_identities",
    "_harvest_tasks",
    "connection",
    "drain_harvest_tasks",
]


# ────────────────────── Module-level instance ───────────────────── #

connection = BuildConnection(cfg.community_name)
