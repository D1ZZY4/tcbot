# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A failed connected-group fetch must not leave the ban unenforced.

The ban executor writes the moderation record and then fans the Telegram
ban out across the connected groups. When the group list cannot be read,
the executor continues with the reduced scope instead of aborting, so the
record and the enforcement must agree: the group the moderator issued the
ban from has to stay in the scope.

The warn threshold already keeps its origin group in the scope; the ban
path now does the same.
"""

from __future__ import annotations

from typing import Any, cast

from tcbot.modules.helper.pipelines import ban_flow


def _scope(groups: list[dict[str, Any]], origin_chat_id: int) -> list[int]:
    scope = ban_flow._enforcement_scope(cast("Any", groups), origin_chat_id)
    return [int(g["chat_id"]) for g in scope]


def test_the_origin_group_joins_the_scope() -> None:
    """A ban issued in a group is enforced in that group."""
    assert -1001 in _scope([], -1001)


def test_a_private_origin_never_joins_the_scope() -> None:
    """A ban issued from the bot PM has no group to enforce in."""
    scope = _scope([], 555)
    assert 555 not in scope
    assert scope == [ban_flow.cfg.main_group]


def test_the_connected_groups_stay_in_the_scope() -> None:
    """The connected groups keep their place in the scope."""
    groups = [{"chat_id": 10, "title": "A"}, {"chat_id": 20, "title": "B"}]
    scope = _scope(groups, -1001)
    assert 10 in scope
    assert 20 in scope
    assert -1001 in scope
    assert ban_flow.cfg.main_group in scope


def test_the_origin_is_not_duplicated() -> None:
    """An origin that is already connected is listed once."""
    groups = [{"chat_id": -1001, "title": "A"}]
    scope = _scope(groups, -1001)
    assert scope.count(-1001) == 1
