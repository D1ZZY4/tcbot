# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared mute-flow reason and proof collector instances."""

from __future__ import annotations

from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow import BuildReason

# * Per-action instances; imported by muting.py.
reason = BuildReason("mute")
proof = BuildProof("mute")
