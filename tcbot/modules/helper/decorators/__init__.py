# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Auth decorators, execution tracer, per-user rate limiter, and shared permission helpers."""

from __future__ import annotations

from tcbot import database as db
from tcbot.modules.helper.decorators.auth import (
    _ANON_BOT_ID,
    _REFUSAL_BY_LABEL,
    _auth_only,
    _is_anon_admin,
    basic_mod_only,
    mod_only,
    owner_only,
    staff_only,
)
from tcbot.modules.helper.decorators.checks import (
    ModTarget,
    action_owner_mismatch,
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
    _RL_LUA,
    _RL_REDIS_TIMEOUT_S,
    _AsyncRateLimiter,
    _cbq_limiter,
    _cmd_limiter,
    _cmd_staff_limiter,
    _is_exempt,
    _RateLimiter,
    _throttle_tier,
    global_rate_limit_handler,
    ratelimiter,
)
from tcbot.modules.helper.decorators.tracing import log_execution
