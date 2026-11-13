# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The permission catalog and the tier model agree.

The handlers gate a command on a tier: the Founder, the Admin, the
Developer, or the Tester. The schema carries a permission catalog, and
its grants decide which role holds which capability. The two have to
say the same thing, otherwise the catalog describes an authorization
model the code does not implement.

The contract is checked against the database, because the grants live
there: a seeded grant that no longer matches the tier the code
enforces is a silent privilege change, and a test that only read the
Python tables would not see it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tcbot import database as db
from tcbot.database.users_roles import ROLE_RANK
from tests.postgres_support import reset_community, seed_users

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# * The catalog names the tiers differently from the handlers: the
# * catalog speaks of the Owner, the Admin, the Developer, and the
# * Moderator, while the handlers speak of the Founder, the Admin, the
# * Developer, and the Tester. The mapping is the only place the two
# * vocabularies meet.
_ROLE_BY_TIER: dict[str, str] = {
    "founder": "owner",
    "admin": "admin",
    "developer": "developer",
    "tester": "moderator",
}

# * Every gated command, with the capability it needs and the tier the
# * handler enforces. The catalog has to grant the capability to
# * exactly the roles that sit at or above that tier.
_COMMAND_CAPABILITIES: dict[str, str] = {
    # * Federation-wide bans and their lift are the Developer work.
    "moderation.ban": "developer",
    "moderation.unban": "developer",
    # * The group-level actions are open to every staff tier.
    "moderation.kick": "tester",
    "moderation.mute": "tester",
    "moderation.unmute": "tester",
    "moderation.warn": "tester",
    "moderation.unwarn": "tester",
    "moderation.reset_warnings": "tester",
    # * Deciding an appeal and moving staff around are Admin work.
    "moderation.review_appeals": "admin",
    "roles.promote": "admin",
    "roles.demote": "admin",
    # * The owner-only operations keep their own permission, so an Admin
    # * never inherits them through the tier comparison.
    "roles.transfer_ownership": "founder",
    "roles.review_promotion_requests": "founder",
    "community.leave_all": "founder",
    "community.speedtest": "founder",
    # * The community-wide operations are Admin work.
    "community.broadcast": "admin",
    "community.cleanup": "admin",
    "groups.remove": "admin",
}

# * The tiers the contract walks, from the highest to the lowest.
_TIERS: tuple[str, ...] = ("founder", "admin", "developer", "tester")

# * The user that holds the role under test, and the user the role was
# * granted by.
_HOLDER_ID: int = 5_101
_GRANTER_ID: int = 5_102

pytestmark = [pytest.mark.postgres]


@pytest.fixture
async def community(postgres_db: str) -> AsyncIterator[str]:
    """Start from an empty community."""
    await reset_community()
    await seed_users(_HOLDER_ID, _GRANTER_ID)
    yield postgres_db
    await reset_community()


def _expected_holders(capability: str) -> set[str]:
    """Return the catalog roles that hold *capability* under the tier model."""
    required = ROLE_RANK[_COMMAND_CAPABILITIES[capability]]
    return {_ROLE_BY_TIER[tier] for tier, rank in ROLE_RANK.items() if rank >= required}


async def _assign(tier: str) -> None:
    """Give the holder user the role of *tier*."""
    if tier == "founder":
        await db.users_roles.set_owner(_HOLDER_ID)
        return
    if tier == "admin":
        await db.users_roles.add_admin(_HOLDER_ID, _GRANTER_ID)
        return
    await db.users_roles.set_role(_HOLDER_ID, tier, _GRANTER_ID)


async def _grant_tier(tier: str) -> set[str]:
    """Reset the community, grant *tier* to the holder, return its grants."""
    await reset_community()
    await seed_users(_HOLDER_ID, _GRANTER_ID)
    await _assign(tier)
    return set(await db.users_roles.permissions_for(_HOLDER_ID))


async def test_the_catalog_grants_every_capability_the_code_gates(
    community: str,
) -> None:
    """Every gated command names a permission the catalog knows."""
    rows = await db.users_roles.permission_catalog()
    catalog = {str(row["permission_key"]) for row in rows}

    missing = sorted(set(_COMMAND_CAPABILITIES) - catalog)
    assert missing == []


async def test_the_catalog_ranks_the_roles_like_the_code_does(
    community: str,
) -> None:
    """The priority of the catalog follows the rank of the tiers.

    The catalog numbers the roles on its own scale, so only the order
    can be compared. An order that disagrees with the code means the
    catalog describes a hierarchy the handlers do not apply.
    """
    rows = await db.users_roles.role_catalog()
    by_priority = [str(row["role_key"]) for row in rows]

    by_rank = [
        _ROLE_BY_TIER[tier]
        for tier, _rank in sorted(ROLE_RANK.items(), key=lambda item: -item[1])
    ]

    assert by_priority == by_rank


async def test_a_capability_reaches_exactly_the_roles_the_tier_allows(
    community: str,
) -> None:
    """Each capability is granted to the roles at or above its tier."""
    for tier in _TIERS:
        held = await _grant_tier(tier)

        for capability in _COMMAND_CAPABILITIES:
            granted = _ROLE_BY_TIER[tier] in _expected_holders(capability)
            assert (capability in held) is granted, (
                f"the {tier} tier holds {capability}={capability in held}, "
                f"the tier model expects {granted}"
            )


async def test_the_permission_check_agrees_with_the_grants(community: str) -> None:
    """The database check and the grant list report the same answer."""
    for tier in _TIERS:
        held = await _grant_tier(tier)

        for capability in _COMMAND_CAPABILITIES:
            allowed = await db.users_roles.has_permission(_HOLDER_ID, capability)
            assert allowed is (capability in held), (
                f"the {tier} tier was checked for {capability}: "
                f"the check says {allowed}, the grants say {capability in held}"
            )


async def test_a_user_without_a_role_holds_nothing(community: str) -> None:
    """A user without an assignment passes no capability check."""
    for capability in _COMMAND_CAPABILITIES:
        allowed = await db.users_roles.has_permission(_HOLDER_ID, capability)
        assert allowed is False
