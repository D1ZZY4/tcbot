# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules renderer and picker contracts that need no database."""

from __future__ import annotations

from tcbot.modules.helper.messages import rules as rules_msg
from tcbot.modules.helper.pipelines import reason_flow, rules_step


def _item(item_id: int, category: str = "Conduct", *, order: int = 1) -> dict:
    return {
        "id": item_id,
        "title": f"Rule {item_id}",
        "body": f"Body of rule {item_id}",
        "category_key": "conduct",
        "category_title": category,
        "category_sort_order": order,
        "sort_order": item_id,
        "reference_url": None,
    }


def test_utf16_units_count_astral_characters_twice() -> None:
    """UTF-16 length counts an astral character as two code units."""
    assert rules_msg.utf16_len("abc") == 3
    assert rules_msg.utf16_len("😀") == 2


def test_split_utf16_never_exceeds_the_budget() -> None:
    """Every part fits the limit and no content is lost."""
    text = "\n".join(f"line {index} 😀" for index in range(120))
    parts = rules_msg.split_utf16(text, 80)
    assert len(parts) > 1
    assert all(rules_msg.utf16_len(part) <= 80 for part in parts)
    assert "line 119" in parts[-1]


def test_render_channel_escapes_and_numbers_items() -> None:
    """Item titles are escaped and numbered from one."""
    parts = rules_msg.render_channel(
        [_item(1), _item(2)],
        version_number=3,
        published_at="2026-11-21",
    )
    assert len(parts) == 1
    assert parts[0][0] == "Conduct"
    assert "1\\. " in parts[0][2]
    assert "2\\. " in parts[0][2]
    assert "v3" in parts[0][2]


def test_content_hash_changes_with_text() -> None:
    """The slot hash tracks the exact rendered text."""
    first = rules_msg.content_hash("hello")
    assert rules_msg.content_hash("hello") == first
    assert rules_msg.content_hash("world") != first


def test_picker_toggle_and_callbacks_round_trip() -> None:
    """A toggle flips one id and the callback payload parses back to it."""
    data = rules_step.callback_for(42)
    assert rules_step.item_id_from_callback(data) == 42
    assert rules_step.item_id_from_callback("rules_step:done") is None
    assert rules_step.toggle([1, 2], 2) == [1]
    assert rules_step.toggle([1], 3) == [1, 3]


def test_rules_scope_round_trips_selection_and_note() -> None:
    """A flow stores the picker result under its action-prefixed keys."""
    scope = {"kick_rules": [1, 2], "kick_rules_note": "not covered"}
    assert reason_flow.rules_from_scope(scope, "kick") == ([1, 2], "not covered")
    assert reason_flow.rules_from_scope({}, "warn") == ([], None)
    assert reason_flow.WAITING_RULES != reason_flow.WAITING_PROOF


def test_picker_markup_offers_all_controls() -> None:
    """The picker always offers Other, Done, Clear, and Cancel."""
    markup = rules_step.picker_markup([_item(1), _item(2)], [1], "en-US")
    callbacks = {
        button.callback_data for row in markup.inline_keyboard for button in row
    }
    assert "rules_step:other" in callbacks
    assert "rules_step:done" in callbacks
    assert rules_step.callback_for(1) in callbacks
