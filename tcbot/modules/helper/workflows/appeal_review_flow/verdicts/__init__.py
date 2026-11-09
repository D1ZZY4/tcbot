# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Approve / reject executors for staff appeal review."""

from __future__ import annotations

from tcbot import database as db
from tcbot.modules.helper.workflows import appeal_review_flow as flow_pkg
from tcbot.modules.helper.workflows.appeal_review_flow.verdicts.approve import (
    ApproveMixin,
)
from tcbot.modules.helper.workflows.appeal_review_flow.verdicts.logmsg import (
    _update_or_send_log,
)
from tcbot.modules.helper.workflows.appeal_review_flow.verdicts.reject import (
    RejectMixin,
)
from tcbot.modules.helper.workflows.demote_flow import Demote

__all__ = [
    "AppealVerdictsMixin",
    "Demote",
    "_update_or_send_log",
    "db",
    "flow_pkg",
]


class AppealVerdictsMixin(ApproveMixin, RejectMixin):
    """Staff-side appeal verdict executors: approve fans out unbans, reject cools down.

    Combined into ``AppealReviewMixin``; ``cfg`` and locale lookups resolve
    through the package namespace (``flow_pkg``) so package-level
    monkeypatching keeps working as it did for the flat module.
    """
