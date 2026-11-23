# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The connected-groups panel renders as one-column or two-column rich tables."""

from __future__ import annotations

from tcbot.database.documents import GroupDoc
from tcbot.database.types import GroupId
from tcbot.modules.helper.messages.panels import render_groups


def _groups(count: int = 2) -> list[GroupDoc]:
    return [
        {
            "chat_id": GroupId(-1001234567890 - index),
            "title": f"Group {index}",
        }
        for index in range(count)
    ]


def test_simple_view_is_a_one_column_table() -> None:
    text = render_groups(_groups(), detailed=False, locale="en-US")
    assert "<table" in text
    assert "<ul>" not in text
    assert text.count("<th>") == 1
    assert "<th>Group</th>" in text
    assert "Group 0" in text
    assert "<code>" not in text


def test_details_view_is_a_two_column_table() -> None:
    text = render_groups(_groups(), detailed=True, locale="en-US")
    assert "<table" in text
    assert text.count("<th>") == 2
    assert "<th>ID</th>" in text
    assert "<code>-1001234567890</code>" in text
    assert text.count("<td>") == 4


def test_group_titles_are_escaped_in_table_cells() -> None:
    text = render_groups(
        [
            {
                "chat_id": GroupId(-1001234567890),
                "title": "A & B <group>",
            }
        ],
        detailed=False,
        locale="en-US",
    )
    assert "A &amp; B &lt;group&gt;" in text


def test_large_federation_truncates_with_a_notice() -> None:
    text = render_groups(_groups(200), detailed=False, locale="en-US")
    assert "more not shown" in text
    assert "Group 199" not in text
