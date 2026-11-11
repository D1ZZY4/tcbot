# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Target extraction helpers: extract_target() and extract_mod_target()."""

from __future__ import annotations

from tcbot.modules.helper.extraction.refresh import (
    identity_needs_refresh,
    launch_identity_refresh,
    sync_user_identity,
)
from tcbot.modules.helper.extraction.resolve import (
    extract_mod_target,
    extract_target,
    first_arg_is_explicit,
    reply_uid,
)
