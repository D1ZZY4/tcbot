# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Every locale-dependent keyboard builder names its locale explicitly."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import tcbot.modules.helper.keyboards as keyboards


def test_keyboard_builders_take_a_locale() -> None:
    neutral = {"help_topics_kb"}
    missing: list[str] = []
    for module_info in pkgutil.iter_modules(keyboards.__path__):
        module = importlib.import_module(f"{keyboards.__name__}.{module_info.name}")
        for name, value in vars(module).items():
            if not inspect.isfunction(value) or value.__module__ != module.__name__:
                continue
            if not name.endswith(("_kb", "_keyboard")):
                continue
            if name in neutral:
                continue
            if "locale" not in inspect.signature(value).parameters:
                missing.append(f"{module.__name__}.{name}")
    assert not missing, f"keyboard builders without locale: {missing}"
