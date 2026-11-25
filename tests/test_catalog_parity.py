# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Translation catalogs must expose the same keys and placeholders per locale."""

from __future__ import annotations

import re

from tcbot.utils.i18n import DEFAULT_LOCALE, load_catalog

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def test_every_locale_has_the_source_key_set() -> None:
    """A locale with missing or extra keys drifts from the source of truth."""
    catalog = load_catalog()
    source = set(catalog[DEFAULT_LOCALE])
    for locale, entries in catalog.items():
        missing = sorted(source - set(entries))
        extra = sorted(set(entries) - source)
        assert not missing, f"{locale} is missing keys: {missing}"
        assert not extra, f"{locale} has orphaned keys: {extra}"


def test_every_locale_uses_the_same_placeholders() -> None:
    """A mismatched placeholder would make a translated template fail to render."""
    catalog = load_catalog()
    source = catalog[DEFAULT_LOCALE]
    for locale, entries in catalog.items():
        for key, template in entries.items():
            if key not in source:
                continue  # The key-set test owns the orphaned-key failure.
            expected = sorted(set(_PLACEHOLDER.findall(source[key])))
            actual = sorted(set(_PLACEHOLDER.findall(template)))
            assert actual == expected, (
                f"{locale}:{key} placeholders {actual} differ from {expected}"
            )
