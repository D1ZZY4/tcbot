# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Table definitions for the TCF Bot PostgreSQL schema.

The schema follows the community model: one community owns many Telegram
groups, and every domain records its own history. The tables are the
contract the application, the workers, and the scheduled jobs share.
"""

from __future__ import annotations

from . import (
    automation,
    broadcast,
    community,
    enforcement,
    identity,
    jobs,
    moderation,
    rbac,
    rules,
    runtime,
    settings,
)
from ._shared import metadata
from .automation import (
    automation_events,
    automation_policies,
    automation_policy_versions,
    automation_run_step_attempts,
    automation_run_steps,
    automation_runs,
)
from .broadcast import broadcast_attempts, broadcast_campaigns, broadcast_targets
from .community import community_settings
from .enforcement import (
    moderation_enforcement_attempts,
    moderation_enforcement_runs,
    moderation_enforcement_targets,
)
from .identity import (
    chat_members,
    connected_chats,
    join_requests,
    telegram_chats,
    telegram_users,
)
from .jobs import (
    retention_policies,
    scheduled_job_runs,
    scheduled_jobs,
    telegram_user_erasures,
)
from .moderation import (
    audit_events,
    moderation_actions,
    moderation_appeals,
    moderation_case_rules,
    moderation_cases,
    moderation_evidence_items,
    moderation_evidence_uploads,
    moderation_messages,
)
from .rbac import (
    permission_definitions,
    promotion_requests,
    role_assignments,
    role_definitions,
    role_permissions,
)
from .rules import (
    rule_acknowledgements,
    rule_items,
    rule_set_versions,
    rule_sets,
)
from .runtime import apscheduler_jobs, mtproto_state
from .settings import chat_settings, user_settings

# * The tables this package owns, in the order the schema declares them.
# * The migration applies exactly this list, so the migrated schema and
# * the declared schema cannot drift.
SCHEMA_TABLES: tuple[str, ...] = (
    "community_settings",
    "telegram_users",
    "telegram_chats",
    "connected_chats",
    "join_requests",
    "role_definitions",
    "permission_definitions",
    "role_permissions",
    "role_assignments",
    "promotion_requests",
    "user_settings",
    "chat_settings",
    "chat_members",
    "rule_sets",
    "rule_set_versions",
    "rule_items",
    "rule_acknowledgements",
    "moderation_cases",
    "moderation_case_rules",
    "moderation_evidence_uploads",
    "moderation_evidence_items",
    "moderation_actions",
    "moderation_appeals",
    "moderation_messages",
    "audit_events",
    "moderation_enforcement_runs",
    "moderation_enforcement_targets",
    "moderation_enforcement_attempts",
    "automation_policies",
    "automation_policy_versions",
    "automation_events",
    "automation_runs",
    "automation_run_steps",
    "automation_run_step_attempts",
    "broadcast_campaigns",
    "broadcast_targets",
    "broadcast_attempts",
    "scheduled_jobs",
    "scheduled_job_runs",
    "telegram_user_erasures",
    "retention_policies",
    "mtproto_state",
    "apscheduler_jobs",
)

__all__ = [
    "SCHEMA_TABLES",
    "apscheduler_jobs",
    "audit_events",
    "automation",
    "automation_events",
    "automation_policies",
    "automation_policy_versions",
    "automation_run_step_attempts",
    "automation_run_steps",
    "automation_runs",
    "broadcast",
    "broadcast_attempts",
    "broadcast_campaigns",
    "broadcast_targets",
    "chat_members",
    "chat_settings",
    "community",
    "community_settings",
    "connected_chats",
    "enforcement",
    "identity",
    "jobs",
    "join_requests",
    "metadata",
    "moderation",
    "moderation_actions",
    "moderation_appeals",
    "moderation_case_rules",
    "moderation_cases",
    "moderation_enforcement_attempts",
    "moderation_enforcement_runs",
    "moderation_enforcement_targets",
    "moderation_evidence_items",
    "moderation_evidence_uploads",
    "moderation_messages",
    "mtproto_state",
    "permission_definitions",
    "promotion_requests",
    "rbac",
    "retention_policies",
    "role_assignments",
    "role_definitions",
    "role_permissions",
    "rule_acknowledgements",
    "rule_items",
    "rule_set_versions",
    "rule_sets",
    "rules",
    "runtime",
    "scheduled_job_runs",
    "scheduled_jobs",
    "settings",
    "telegram_chats",
    "telegram_user_erasures",
    "telegram_users",
    "user_settings",
]
