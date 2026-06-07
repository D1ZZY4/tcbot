# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Shared type aliases for module and workflow interfaces."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

CommandHandlerFn = Callable[
    [Update, ContextTypes.DEFAULT_TYPE],
    Awaitable[object],
]
CallbackHandlerFn = Callable[
    [Update, ContextTypes.DEFAULT_TYPE],
    Awaitable[object],
]
DataCoroutine = Callable[[], Awaitable[tuple[str, object]]]
TargetId = int
TargetFirstName = str | None
