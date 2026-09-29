# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared ban-flow constants and proof collector instance."""

from __future__ import annotations

from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.utils.logger import get_logger

log = get_logger(__name__)

# * Ban-flow runtime prose lives in banning.toml [state]/[db_fail]/
# * [applied]/[pm]/[summary]; only the key tuple below stays in code.

# * Single owner for every ban_* user_data key in this flow and its entry
# * point: banning.py pops this same tuple on pre-prompt failures instead
# * of keeping a parallel list that can drift.
BAN_USER_DATA_KEYS = (
    "ban_target_id",
    "ban_target_fname",
    "ban_reason",
    "ban_admin_id",
    "ban_admin_fname",
    "ban_prompt_msg_id",
    "ban_prompt_chat_id",
    "ban_target_role",
    "ban_executing",
    "ban_locale",
)

WAITING_PROOF = 0
WAITING_UPDATE_CONFIRM = 1

# * Per-action BuildProof instance; imported by banning.py.
# * skip_allowed=False: ban proof is required; there is no Skip option.
proof = BuildProof("ban", skip_allowed=False)

# * Hard cap on one proof-collection session: the silence window below
# * slides with every arrival, so without a cap a steady trickle of media
# * would never flush. Far above any legitimate multi-send burst.
_PROOF_COLLECT_MAX_S: float = 60.0
