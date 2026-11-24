# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rule categories follow the operator documents and use localized labels."""

from __future__ import annotations

from scripts import seed_rules
from tcbot.modules.helper.messages.rules import category_label, rich_category_view
from tcbot.modules.helper.pipelines.rules_picker import picker_text


def test_seed_uses_document_stems_as_categories() -> None:
    assert seed_rules._category("cheat.md") == "cheat"
    assert seed_rules._category("penipuan.md") == "penipuan"
    assert seed_rules._category("doxing-dan-privasi.md") == "doxing-dan-privasi"
    assert seed_rules._category("federasi.md") == "federasi"
    assert "other" in seed_rules._RETIRED_KEYS


def test_category_label_uses_the_title_stored_with_the_rule_set() -> None:
    """The public button label comes from the database, not the catalog."""
    assert category_label("cheat", "en-US", "Cheating") == "Cheating"
    assert category_label("cheat", "id-ID", "Cheating") == "Cheating"
    assert category_label("custom", "en-US", "Custom") == "Custom"
    assert category_label("custom", "en-US", "") == "custom"


def test_category_page_uses_the_privacy_style_blocks() -> None:
    page = rich_category_view(
        "cheat",
        [{"title": "Cheat: Aturan", "body": "No cheats."}],
        "en-US",
        category_title="Cheating",
    )["html"]
    rendered = str(page)
    assert "<table" not in rendered
    assert "Cheating" in rendered


def test_picker_shows_the_localized_category_of_a_selection() -> None:
    items = [
        {
            "id": 7,
            "title": "Cheat: Aturan",
            "category_key": "cheat",
            "category_title": "Cheating",
        }
    ]
    text = picker_text(items, [7], "en-US")
    assert "Cheating: Cheat: Aturan" in text
