# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Category slugs stay within Telegram's 64-byte callback_data budget."""

from __future__ import annotations

from tcbot.database.rules_db import categories as categories_db
from tcbot.modules.helper.pipelines import rules_editor_steps

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
