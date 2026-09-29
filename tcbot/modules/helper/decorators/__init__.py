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
    classify_and_check,
    recheck_executor_rank,
    resolve_and_check,
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

__all__ = [
    "_ANON_BOT_ID",
    "_REFUSAL_BY_LABEL",
    "_RL_LUA",
    "_RL_REDIS_TIMEOUT_S",
    "_AsyncRateLimiter",
    "_RateLimiter",
    "_auth_only",
    "_cbq_limiter",
    "_cmd_limiter",
    "_cmd_staff_limiter",
    "_is_anon_admin",
    "_is_exempt",
    "_throttle_tier",
    "basic_mod_only",
    "classify_and_check",
    "db",
    "global_rate_limit_handler",
    "log_execution",
    "mod_only",
    "owner_only",
    "ratelimiter",
    "recheck_executor_rank",
    "resolve_and_check",
    "staff_only",
]
