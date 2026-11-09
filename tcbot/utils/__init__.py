# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Utils package: dispatching, error reporting, logging, prefixes, datetime helpers, and MarkdownV2 formatters."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    from . import (
        circuit_breaker,
        dispatch,
        error_reporter,
        formatter,
        i18n,
        logger,
        pagination,
        prefixes,
        time_and_date,
        transport,
    )

__all__ = [
    "circuit_breaker",
    "dispatch",
    "error_reporter",
    "formatter",
    "i18n",
    "logger",
    "pagination",
    "prefixes",
    "time_and_date",
    "transport",
]


def __getattr__(name: str) -> ModuleType:
    """Lazily load utils submodules on attribute access.

    Eager imports here pull every submodule (including ``error_reporter`` and
    ``prefixes``, which read ``tcbot.cfg``) whenever any single submodule is
    imported, which blocks ``tcbot/__init__.py`` from importing the logger
    at the top level without a circular import.
    """
    if name in __all__:
        return importlib.import_module(f"tcbot.utils.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Return the lazily exposed submodule names."""
    return [*__all__]
