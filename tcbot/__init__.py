# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Configuration singleton: loads env vars into a frozen dataclass and exposes a thin cfg adapter."""

from __future__ import annotations

from tcbot.config import Configs, _CfgAdapter

configs = Configs.load()

# * This adapter instance is the single global 'cfg' used by every module.
cfg = _CfgAdapter(configs)

__all__ = ["Configs", "cfg", "configs"]
