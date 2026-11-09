# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation staff role helpers (tc_owners, tc_admins, and tc_roles)."""

from __future__ import annotations

from tcbot.database.cache import effective_role_cache, owner_id_cache

from .admin import (
    add_admin,
    admin_count,
    all_admins,
    is_admin,
    remove_admin,
)
from .owner import (
    ensure_initial_owner,
    get_owner_id,
    is_owner,
    set_owner,
)
from .resolution import get_effective_role, is_staff, role_meta
from .roles import (
    all_by_role,
    get_role,
    remove_role,
    role_count,
    set_role,
)
from .tables import ROLE_LABEL, ROLE_RANK, VALID_ROLES, role_rank

__all__ = [
    "ROLE_LABEL",
    "ROLE_RANK",
    "VALID_ROLES",
    "add_admin",
    "admin_count",
    "all_admins",
    "all_by_role",
    "effective_role_cache",
    "ensure_initial_owner",
    "get_effective_role",
    "get_owner_id",
    "get_role",
    "is_admin",
    "is_owner",
    "is_staff",
    "owner_id_cache",
    "remove_admin",
    "remove_role",
    "role_count",
    "role_meta",
    "role_rank",
    "set_owner",
    "set_role",
]
