# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federated groups and pending joins collection helpers."""

from __future__ import annotations

from .collections import _groups, _pending
from .core import (
    active_group_count,
    active_groups,
    add_group,
    deactivate_group,
    get_group_titles,
    is_connected,
    refresh_group_title,
    with_primary_groups,
)
from .locale import _GROUP_LOCALE_L1, get_group_locale, set_group_locale
from .migrate import migrate_group
from .pending import add_pending, get_pending, remove_pending

__all__ = [
    "_GROUP_LOCALE_L1",
    "_groups",
    "_pending",
    "active_group_count",
    "active_groups",
    "add_group",
    "add_pending",
    "deactivate_group",
    "get_group_locale",
    "get_group_titles",
    "get_pending",
    "is_connected",
    "migrate_group",
    "refresh_group_title",
    "remove_pending",
    "set_group_locale",
    "with_primary_groups",
]
