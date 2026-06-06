# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for shared handler type aliases in tcbot.modules.types."""

from __future__ import annotations

import inspect
from typing import get_origin

from tcbot.modules import types as module_types


def test_command_handler_fn_is_callable_alias() -> None:
    origin = get_origin(module_types.CommandHandlerFn)
    assert origin is not None
    assert origin.__name__ == "Callable"


def test_callback_handler_fn_is_callable_alias() -> None:
    origin = get_origin(module_types.CallbackHandlerFn)
    assert origin is not None
    assert origin.__name__ == "Callable"


def test_data_coroutine_is_callable_alias() -> None:
    origin = get_origin(module_types.DataCoroutine)
    assert origin is not None
    assert origin.__name__ == "Callable"


def test_target_id_is_int_alias() -> None:
    assert module_types.TargetId is int


def test_target_first_name_is_optional_str_alias() -> None:
    assert module_types.TargetFirstName == (str | None)


def test_module_exports_expected_aliases() -> None:
    exported = {
        name
        for name in dir(module_types)
        if not name.startswith("_")
        and not inspect.ismodule(getattr(module_types, name))
    }
    assert {
        "CallbackHandlerFn",
        "CommandHandlerFn",
        "DataCoroutine",
        "TargetFirstName",
        "TargetId",
    } <= exported


# ─────────────────────── get_handlers ───────────────────────────── #


def test_get_handlers_returns_list(monkeypatch) -> None:
    """get_handlers should return a flat list of handlers from all modules."""
    import importlib
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import tcbot.modules as modules_pkg

    fake_handler = MagicMock()
    fake_mod = SimpleNamespace(__handlers__=[fake_handler])

    monkeypatch.setattr(modules_pkg, "ALL_MODULES", ["fake_mod"])
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_mod)

    result = modules_pkg.get_handlers()
    assert isinstance(result, list)
    assert fake_handler in result


def test_get_handlers_empty_modules_returns_empty_list(monkeypatch) -> None:
    """get_handlers with no modules returns an empty list."""
    import tcbot.modules as modules_pkg

    monkeypatch.setattr(modules_pkg, "ALL_MODULES", [])

    result = modules_pkg.get_handlers()
    assert result == []


def test_get_handlers_module_without_handlers_attr(monkeypatch) -> None:
    """Modules with no __handlers__ attribute are silently skipped."""
    import importlib
    from types import SimpleNamespace

    import tcbot.modules as modules_pkg

    fake_mod = SimpleNamespace()  # no __handlers__
    monkeypatch.setattr(modules_pkg, "ALL_MODULES", ["no_handlers_mod"])
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_mod)

    result = modules_pkg.get_handlers()
    assert result == []


def test_get_handlers_raises_system_exit_on_import_failure(monkeypatch) -> None:
    """An import error on any module causes SystemExit."""
    import importlib

    import pytest

    import tcbot.modules as modules_pkg

    def _fail(name: str):
        raise ImportError("boom")

    monkeypatch.setattr(modules_pkg, "ALL_MODULES", ["broken_mod"])
    monkeypatch.setattr(importlib, "import_module", _fail)

    with pytest.raises(SystemExit):
        modules_pkg.get_handlers()
