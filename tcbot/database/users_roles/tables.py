# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role hierarchy tables shared by every users_roles submodule."""

from __future__ import annotations

from typing import Literal

# ────────────────────── Role hierarchy tables ───────────────────── #
# * Numeric ranks compare executor vs target; labels render to humans.

VALID_ROLES: tuple[Literal["developer", "tester"], ...] = ("developer", "tester")

ROLE_RANK: dict[str, int] = {
    "founder": 4,
    "admin": 3,
    "developer": 2,
    "tester": 1,
}

ROLE_LABEL: dict[str, str] = {
    "founder": "Founder",
    "admin": "Admin",
    "developer": "Developer",
    "tester": "Tester",
}


def role_rank(role: str | None) -> int:
    """Convert a role string to its numeric rank value for comparison."""
    return ROLE_RANK.get(role or "", 0)
