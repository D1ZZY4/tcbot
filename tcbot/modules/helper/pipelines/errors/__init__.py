# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error-reporting pipeline: classification, redaction, and report delivery."""

from __future__ import annotations

from tcbot.modules.helper.pipelines.errors.exceptions import PollingConflictError
from tcbot.modules.helper.pipelines.errors.redaction import (
    scrub_sentry_event,
    scrub_text,
)
from tcbot.modules.helper.pipelines.errors.report import (
    attach,
    build_error_report_payload,
    drain_pending,
    report_exc,
    send_to_log_errors,
    send_to_owner,
    set_owner,
)

__all__ = [
    "PollingConflictError",
    "attach",
    "build_error_report_payload",
    "drain_pending",
    "report_exc",
    "scrub_sentry_event",
    "scrub_text",
    "send_to_log_errors",
    "send_to_owner",
    "set_owner",
]
