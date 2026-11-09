# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal conversation: entry via /start appeal<ban_id> deep link, DM only."""

from __future__ import annotations

from dataclasses import dataclass, field

from tcbot import cfg
from tcbot.config.parsing import tme_handle_from_url
from tcbot.modules.helper.workflows.appeal_review_flow import (
    LOCK_HOURS,
    AppealReviewMixin,
    reviewer_locked_out,
)
from tcbot.modules.helper.workflows.appeal_submit_flow import (
    WAITING_APPEAL,
    AppealSubmitMixin,
    starts_with_appeal_tag,
    text_references_log_message,
)

__all__ = (
    "LOCK_HOURS",
    "WAITING_APPEAL",
    "BuildAppeal",
    "appeal",
    "reviewer_locked_out",
    "starts_with_appeal_tag",
    "text_references_log_message",
)


@dataclass(frozen=True)
class BuildAppeal(AppealSubmitMixin, AppealReviewMixin):
    """Configurable appeal ConversationHandler builder.

    Submission paths live in ``appeal_submit_flow.AppealSubmitMixin`` and
    review paths in ``appeal_review_flow.AppealReviewMixin``; this class only
    binds them to one config surface so existing importers (``appeals.py``,
    appeal tests) keep working unchanged.
    """

    community_name: str
    log_channel: str
    cancel_label: str = field(default="Cancel", kw_only=True)
    cancel_callback: str = field(default="cancel_appeal", kw_only=True)


# ────────────────────── Module-level instance ───────────────────── #

# * The instruction handle is derived from the public logs link so no
# * separate handle variable is needed; APPEALS stays the numeric
# * destination that supports channel, group, and forum threads.
appeal = BuildAppeal(cfg.community_name, tme_handle_from_url(cfg.community_logs_url))
