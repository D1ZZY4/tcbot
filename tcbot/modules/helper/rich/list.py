# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich list formats: ordered, bulleted, checklist, and collapsible details."""

from __future__ import annotations

from tcbot.modules.helper.rich.style import esc


def bullet_list(items: list[str]) -> str:
    """Render a bulleted list. Items may contain inline rich HTML."""
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items if item) + "</ul>"


def ordered_list(
    items: list[str],
    *,
    start: int | None = None,
    marker: str | None = None,
    reversed_order: bool = False,
) -> str:
    """Render an ordered list with optional start, marker and direction.

    ``marker`` is the Bot API ``type`` attribute (``a``, ``A``, ``i``, ``I``
    or ``1``) that selects the numbering style.
    """
    attrs = ""
    if start is not None:
        attrs += f' start="{start}"'
    if marker:
        attrs += f' type="{esc(marker)}"'
    if reversed_order:
        attrs += " reversed"
    return (
        f"<ol{attrs}>" + "".join(f"<li>{item}</li>" for item in items if item) + "</ol>"
    )


def checklist(items: list[tuple[str, bool]]) -> str:
    """Render a task list from ``(label, checked)`` pairs."""
    rows = "".join(
        f'<li><input type="checkbox"{" checked" if checked else ""}>{label}</li>'
        for label, checked in items
        if label
    )
    return f"<ul>{rows}</ul>"


def details(summary: str, body: str, *, open: bool = False) -> str:
    """Render a collapsible details block."""
    attr = " open" if open else ""
    return f"<details{attr}><summary>{summary}</summary>{body}</details>"


__all__ = ["bullet_list", "checklist", "details", "ordered_list"]
