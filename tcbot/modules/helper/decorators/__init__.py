# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Handler decorators: federated-tier authorization, rate limits, and tracing.

The permission gates that decide whether an executor may act live next
to this package, in ``tcbot.modules.helper.guards``.
"""

from __future__ import annotations

from tcbot.modules.helper.decorators.auth import (
    basic_mod_only,
    mod_only,
    owner_only,
    staff_only,
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

__all__ = [
    "THROTTLE_BULK",
    "THROTTLE_CALLBACK",
    "THROTTLE_CALLBACK_DEEP",
    "THROTTLE_CRITICAL",
    "THROTTLE_FEDERATION",
    "THROTTLE_MODERATION",
    "THROTTLE_READ",
    "THROTTLE_STAFF",
    "THROTTLE_SWEEP",
    "Throttle",
    "basic_mod_only",
    "global_rate_limit_handler",
    "log_execution",
    "mod_only",
    "owner_only",
    "ratelimiter",
    "staff_only",
]
