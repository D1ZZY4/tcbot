# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Every locale-dependent keyboard builder names its locale explicitly."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import tcbot.modules.helper.buttons as buttons
from tcbot.utils.i18n import t


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
