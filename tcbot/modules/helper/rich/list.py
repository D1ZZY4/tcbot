# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich list blocks: bullet, ordered, checklist and collapsible details.

These render the HTML forms Kurigram maps to ``PageBlockList``,
``PageBlockOrderedList`` and ``PageBlockDetails``. List items are trusted rich
markup: callers escape their own untrusted values before assembling them.
Only inline formatting belongs inside an item; a nested block such as another
list or a table is not supported by Telegram in that position.
"""

from __future__ import annotations

from dataclasses import dataclass

# * Kurigram's ordered-list label builder accepts exactly these type values.
_MARKERS = frozenset({"a", "A", "i", "I", "1"})


@dataclass(frozen=True)
class OrderedItem:
    """An ordered-list item with Kurigram's optional label overrides."""

    text: str
    value: int | None = None
    type: str | None = None


def ordered_item(
    text: str, *, value: int | None = None, type: str | None = None
) -> OrderedItem:
    """Build an ordered-list item with an explicit number or marker."""
    return OrderedItem(text=text, value=value, type=type)


def bullet_list(items: list[str]) -> str:
    """Render a bulleted list. Items may contain inline rich HTML."""
    return (
        "<ul>"
        + "".join(f"<li>{item}</li>" for item in items if item and item.strip())
        + "</ul>"
    )


def ordered_list(
    items: list[str | OrderedItem],
    *,
    start: int | None = None,
    marker: str | None = None,
    reversed_order: bool = False,
) -> str:
    """Render an ordered list with optional start, marker and direction.

    An unsupported ``marker`` is dropped instead of shipped as an invalid
    attribute, matching the way rich button alignment is handled. An
    ``OrderedItem`` may override the label for one item with ``value`` and
    ``type``, matching Kurigram's ``InputRichBlockListItem``.
    """
    list_attrs = ""
    if start is not None:
        list_attrs += f' start="{int(start)}"'
    if marker in _MARKERS:
        list_attrs += f' type="{marker}"'
    if reversed_order:
        list_attrs += " reversed"

    rendered: list[str] = []
    for item in items:
        if isinstance(item, OrderedItem):
            item_attrs = ""
            if item.value is not None:
                item_attrs += f' value="{int(item.value)}"'
            if item.type in _MARKERS:
                item_attrs += f' type="{item.type}"'
            if item.text and item.text.strip():
                rendered.append(f"<li{item_attrs}>{item.text}</li>")
        elif item and item.strip():
            rendered.append(f"<li>{item}</li>")
    return f"<ol{list_attrs}>" + "".join(rendered) + "</ol>"


def checklist(items: list[tuple[str, bool]]) -> str:
    """Render a task list from ``(label, checked)`` pairs."""
    rows = "".join(
        f'<li><input type="checkbox"{" checked" if checked else ""}>{label}</li>'
        for label, checked in items
        if label and label.strip()
    )
    return f"<ul>{rows}</ul>"


def details(summary: str, body: str, *, open: bool = False) -> str:
    """Render a collapsible details block."""
    attr = " open" if open else ""
    return f"<details{attr}><summary>{summary}</summary>{body}</details>"


__all__ = ["bullet_list", "checklist", "details", "ordered_item", "ordered_list"]
