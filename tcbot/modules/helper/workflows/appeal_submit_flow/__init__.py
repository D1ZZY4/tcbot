# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal submission: DM deep-link entry, validation gates, and review posting."""

from __future__ import annotations

from tcbot import cfg
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.workflows.appeal_submit_flow.gates import (
    _APPEAL_STATE_KEYS,
    _ID_RE,
    _MAX_APPEAL_LEN,
    _REJECTION_COOLDOWN,
    _REJECTION_COOLDOWN_HOURS,
    _SECONDS_PER_HOUR,
    _STALE_REVIEW_HOURS,
    _STALE_REVIEW_WINDOW,
    WAITING_APPEAL,
    _clear_appeal_state,
    _cooldown_remaining_h,
    _is_stale_review,
    starts_with_appeal_tag,
    text_references_log_message,
)
from tcbot.modules.helper.workflows.appeal_submit_flow.mixin import AppealSubmitMixin
from tcbot.modules.helper.workflows.appeal_submit_flow.submit import SubmitMessageMixin

__all__ = [
    "WAITING_APPEAL",
    "_APPEAL_STATE_KEYS",
    "_ID_RE",
    "_MAX_APPEAL_LEN",
    "_REJECTION_COOLDOWN",
    "_REJECTION_COOLDOWN_HOURS",
    "_SECONDS_PER_HOUR",
    "_STALE_REVIEW_HOURS",
    "_STALE_REVIEW_WINDOW",
    "AppealSubmitMixin",
    "SubmitMessageMixin",
    "_clear_appeal_state",
    "_cooldown_remaining_h",
    "_is_stale_review",
    "cfg",
    "locale_for_update",
    "starts_with_appeal_tag",
    "text_references_log_message",
]
