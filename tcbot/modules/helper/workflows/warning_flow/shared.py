# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared warn-flow reason and proof collector instances."""

from __future__ import annotations

from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow import BuildReason

# * Per-action instances; imported by warnings.py.
# * skip_allowed=False because warn requires a reason; Skip is not offered.
reason = BuildReason("warn", skip_allowed=False)
proof = BuildProof("warn")
