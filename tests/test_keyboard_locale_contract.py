# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Every locale-dependent keyboard builder names its locale explicitly."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import tcbot.modules.helper.buttons as buttons
from tcbot.modules.helper.buttons import rules as rules_buttons
from tcbot.utils.i18n import t

_FMT_KEYS = (
    "fmt_bold",
    "fmt_italic",
    "fmt_list",
    "fmt_divider",
    "fmt_code",
    "fmt_plain",
)


def test_help_topics_close_button_follows_locale() -> None:
    id_markup = buttons.help_topics_btn([("Ban", "help_bans")], "id-ID")
    en_markup = buttons.help_topics_btn([("Ban", "help_bans")], "en-US")
    assert id_markup.inline_keyboard[-1][0].text == t(
        "button.close", "id-ID", plain=True
    )
    assert en_markup.inline_keyboard[-1][0].text == t(
        "button.close", "en-US", plain=True
    )


def test_keyboard_builders_take_a_locale() -> None:
    neutral: set[str] = set()
    missing: list[str] = []
    for module_info in pkgutil.iter_modules(buttons.__path__):
        module = importlib.import_module(f"{buttons.__name__}.{module_info.name}")
        for name, value in vars(module).items():
            if not inspect.isfunction(value) or value.__module__ != module.__name__:
                continue
            if not name.endswith(("_btn", "_keyboard")):
                continue
            if name in neutral:
                continue
            if "locale" not in inspect.signature(value).parameters:
                missing.append(f"{module.__name__}.{name}")
    assert not missing, f"keyboard builders without locale: {missing}"


def test_rules_section_fallback_label_is_localized() -> None:
    """An untitled section must not show an English label to every reader."""
    for locale in ("en-US", "id-ID"):
        markup = rules_buttons.editor_sections_btn([{"id": 5}], locale)
        label = markup.inline_keyboard[0][0].text
        assert label == t("button.rules_section", locale, n=5, plain=True)
    assert t("button.rules_section", "en-US", n=5) != t(
        "button.rules_section", "id-ID", n=5
    )


def test_rules_editor_toolbar_follows_the_reader_locale() -> None:
    """Formatting buttons come from the catalog, not hardcoded English."""
    en_labels: list[str] = []
    id_labels: list[str] = []
    for locale, target in (("en-US", en_labels), ("id-ID", id_labels)):
        markup = rules_buttons.section_editor_btn(locale)
        target.extend(
            button.text for row in markup.inline_keyboard[:3] for button in row
        )
        assert target == [t(f"button.{key}", locale, plain=True) for key in _FMT_KEYS]
    assert en_labels != id_labels
