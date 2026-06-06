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
