# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich list formats: ordered, bulleted, checklist, and collapsible details."""

from __future__ import annotations


def bullet_list(items: list[str]) -> str:
    """Render a bulleted list. Items may contain inline rich HTML."""
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items if item) + "</ul>"


def ordered_list(items: list[str], *, start: int | None = None) -> str:
    """Render an ordered list, optionally starting at a given number."""
    attr = f' start="{start}"' if start is not None else ""
    return (
        f"<ol{attr}>" + "".join(f"<li>{item}</li>" for item in items if item) + "</ol>"
    )


def checklist(items: list[tuple[str, bool]]) -> str:
    """Render a task list from ``(label, checked)`` pairs."""
    rows = "".join(
        f'<li><input type="checbtnox"{" checked" if checked else ""}>{label}</li>'
        for label, checked in items
        if label
    )
    return f"<ul>{rows}</ul>"


def details(summary: str, body: str, *, open: bool = False) -> str:
    """Render a collapsible details block."""
    attr = " open" if open else ""
    return f"<details{attr}><summary>{summary}</summary>{body}</details>"


__all__ = ["bullet_list", "checklist", "details", "ordered_list"]
