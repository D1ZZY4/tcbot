# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Comprehensive user-profile view for /check: bans, warns, kicks, mutes, appeals."""

from __future__ import annotations

from tcbot.modules.helper.workflows.check_flow.bans import CheckBansMixin
from tcbot.modules.helper.workflows.check_flow.events import CheckEventsMixin
from tcbot.modules.helper.workflows.check_flow.profile import CheckProfileMixin
from tcbot.modules.helper.workflows.check_flow.shared import (
    _back_to_check,
    _name,
)


class Check(CheckProfileMixin, CheckBansMixin, CheckEventsMixin):
    """All view builders for the /check user-profile command."""


__all__ = ("Check", "_back_to_check", "_name")
