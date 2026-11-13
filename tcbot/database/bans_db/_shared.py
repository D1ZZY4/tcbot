# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared definitions of the community ban helpers."""

from __future__ import annotations

from tcbot.database.base import moderation_actions

# * The surrogate primary key stays out of the returned documents: the
# * helpers expose the community fields, not the storage identity.
ACTION_COLUMNS = (
    moderation_actions.c.id,
    moderation_actions.c.external_ref,
    moderation_actions.c.target_user_id,
    moderation_actions.c.actor_user_id,
    moderation_actions.c.reason,
    moderation_actions.c.duration_seconds,
    moderation_actions.c.created_at,
    moderation_actions.c.expires_at,
    moderation_actions.c.status,
    moderation_actions.c.revoked_at,
    moderation_actions.c.revoked_by_user_id,
    moderation_actions.c.case_id,
    moderation_actions.c.evidence_upload_id,
    moderation_actions.c.supersedes_action_id,
    moderation_actions.c.action_origin,
    moderation_actions.c.scope_type,
    moderation_actions.c.chat_id,
    moderation_actions.c.origin_chat_id,
    moderation_actions.c.metadata,
)

# * Names of the two unique constraints that can reject an insert.
CONSTRAINT_EXTERNAL_REF: str = "uq_moderation_actions_external_ref"
CONSTRAINT_ACTIVE_USER: str = "uq_moderation_actions_active_ban"

# * The metadata keys the helpers read back from the decision.
META_DURATION = "duration_str"
META_UPDATE_COUNT = "update_count"
META_REVIEW_MESSAGE = "review_message_id"
META_REVIEW_TIMESTAMP = "review_timestamp"
META_PREVIOUS_PROOF = "previous_proof_message_id"
META_PREVIOUS_LOG = "previous_log_message_id"
META_APPEAL_LINK = "appeal_link"
