# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Verbatim rich text passthrough.

Rich messages carry their own HTML, so ``style`` deliberately returns its input
unchanged. Block conversion and payload assembly live in ``rich.block``.
"""

from __future__ import annotations


def style(text: str) -> str:
    """Return rich text unchanged; rich messages own their formatting."""
    return text


__all__ = ["style"]
