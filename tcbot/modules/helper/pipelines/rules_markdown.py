# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Parse operator Markdown into rule items and render it as rich blocks.

The editor accepts ``.md`` documents from the bundled ``rules/`` folder. A
level-one heading names the category; deeper headings become items. Inline
Markdown is preserved in the stored body and converted to rich HTML when the
panel is rendered, so staff can upload a document and keep editing it in bot.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.messages.rich_format import (
    code,
    divider,
    heading,
    paragraph,
)
from tcbot.modules.helper.messages.rich_style import bold, esc, italic

if TYPE_CHECKING:
    from collections.abc import Iterable

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|_([^_\n]+)_")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _inline(text: str) -> str:
    """Convert inline Markdown to rich HTML, escaping everything else."""
    value = esc(text)
    value = _LINK.sub(lambda m: esc(m.group(1)), value)
    value = _INLINE_CODE.sub(lambda m: code(esc(m.group(1))), value)
    value = _BOLD.sub(lambda m: bold(esc(m.group(1))), value)
    return _ITALIC.sub(lambda m: italic(esc(m.group(1) or m.group(2) or "")), value)


def parse_document(text: str, filename: str = "rules.md") -> list[dict[str, Any]]:
    """Split one Markdown document into editable rule items."""
    stem = filename.rsplit(".", 1)[0]
    category = stem
    category_title = stem.replace("-", " ").title()
    title = ""
    items: list[dict[str, Any]] = []
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        content = "\n".join(line for line in body if line.strip()).strip()
        if title and content:
            items.append(
                {
                    "category_key": category,
                    "category_title": category_title,
                    "title": f"{category_title}: {title}",
                    "body": content,
                }
            )
        body = []

    for raw in text.splitlines():
        match = _HEADING.match(raw)
        if match:
            flush()
            level, value = len(match.group(1)), match.group(2).strip()
            if level == 1:
                category_title = value
                title = ""
            else:
                title = value
            continue
        if _RULE.match(raw):
            body.append("---")
            continue
        body.append(raw.rstrip())
    flush()
    return items


def parse_description(text: str) -> str:
    """Return the intro paragraph between H1 and the first H2 heading."""
    lines: list[str] = []
    seen_h1 = False
    for raw in text.splitlines():
        match = _HEADING.match(raw)
        if match:
            level = len(match.group(1))
            if level == 1:
                seen_h1 = True
                continue
            if seen_h1:
                break
        if seen_h1 and raw.strip():
            lines.append(raw.rstrip())
    return "\n".join(lines).strip()


def render_body(body: str) -> str:
    """Render a stored Markdown body as rich HTML blocks."""
    blocks: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "---":
            blocks.append(divider())
            continue
        list_item = _LIST.match(stripped)
        if list_item:
            marker = list_item.group(0).strip()
            bullet = esc(marker) if marker[:-1].isdigit() else "&bull;"
            blocks.append(f"<p>{bullet} {_inline(list_item.group(1))}</p>")
            continue
        blocks.append(paragraph(_inline(stripped)))
    return "\n".join(blocks)


def render_items(items: Iterable[dict[str, Any]]) -> str:
    """Render a list of uploaded items with headings and their rich bodies."""
    blocks: list[str] = []
    for item in items:
        blocks.append(heading(str(item.get("title") or ""), 3))
        blocks.append(render_body(str(item.get("body") or "")))
    return "\n".join(blocks)
