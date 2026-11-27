# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Category slugs stay within Telegram's 64-byte callback_data budget."""

from __future__ import annotations

from tcbot.database.rules_db import categories as categories_db
from tcbot.modules.helper import buttons as btn
from tcbot.modules.helper.pipelines import rules_editor_steps, rules_markdown
from tcbot.modules.helper.rich.button import buttons_from_markup

# * The longest emitted payload is "rules_cat_rename:<key>".
_LONGEST_PREFIX_LEN = len("rules_cat_rename:")


def test_editor_slug_is_bounded() -> None:
    long_title = "a" * 120
    slug = rules_editor_steps.slug(long_title)

    assert len(slug.encode()) + _LONGEST_PREFIX_LEN <= 64


def test_db_slug_with_collision_suffix_is_bounded() -> None:
    long_title = "a" * 120
    used = {categories_db._available_key(long_title, set())}
    slug = categories_db._available_key(long_title, used)

    assert len(slug.encode()) + _LONGEST_PREFIX_LEN <= 64
    assert slug != used


def test_an_uploaded_filename_cannot_break_the_callback_budget() -> None:
    name = f"{'a' * 120}.md"
    items = rules_markdown.parse_document("# Title\n\n## Section\n\nbody", name)
    key = str(items[0]["category_key"])

    assert len(key.encode()) + _LONGEST_PREFIX_LEN <= 64


def test_a_bounded_category_keyboard_stays_on_the_rich_path() -> None:
    key = rules_editor_steps.slug("a" * 120)
    assert len(key.encode()) + _LONGEST_PREFIX_LEN <= 64
    markup = btn.rules.categories_btn(
        [{"category_key": key, "title": "Long category"}], "en-US"
    )
    rows = buttons_from_markup(markup)

    assert rows is not None
    assert sum(len(row) for row in markup.inline_keyboard) == sum(
        row.count("<tg-button ") for row in rows
    )
