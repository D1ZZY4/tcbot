# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared text contract for rich messages.

Rich messages carry their own markup, so there is no layout pass. ``style``
keeps call sites stable while making it explicit that rich text is sent
verbatim.
"""

from __future__ import annotations


def style(text: str) -> str:
    """Return rich text unchanged; rich messages own their formatting."""
    return text


__all__ = ["style"]
