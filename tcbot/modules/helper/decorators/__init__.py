# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Auth decorators, execution tracer, per-user rate limiter, and shared permission helpers."""

from __future__ import annotations

from tcbot.modules.helper.decorators.auth import (
    basic_mod_only,
    mod_only,
    owner_only,
    staff_only,
)
from tcbot.modules.helper.decorators.checks import (
    ModTarget,
    action_owner_mismatch,
    banned_target_refusal,
    can_demote_admin,
    cancel_owner_mismatch,
    check_callback_staff,
    classify_and_check,
    classify_and_load_role,
    prompt_owner_mismatch,
    recheck_executor_rank,
    require_federation_origin,
    resolve_and_check,
    resolve_executor_target,
    resolve_mod_target,
)
from tcbot.modules.helper.decorators.ratelimit import (
    THROTTLE_BULK,
    THROTTLE_CALLBACK,
    THROTTLE_CALLBACK_DEEP,
    THROTTLE_CRITICAL,
    THROTTLE_FEDERATION,
    THROTTLE_MODERATION,
    THROTTLE_READ,
    THROTTLE_STAFF,
    THROTTLE_SWEEP,
    Throttle,
    global_rate_limit_handler,
    ratelimiter,
)
from tcbot.modules.helper.decorators.tracing import log_execution
