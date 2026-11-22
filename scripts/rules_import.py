#!/usr/bin/env python3
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Parse local community rule documents into plain-text rule items.

The bot stores rule bodies as plain text; Markdown syntax would render
literally to members. This module owns the conversion from the operator-local
Markdown files under ``rules/`` into the title/body pairs accepted by
``rules_db.add_item``. It has no database dependency so the conversion can be
tested without a server.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# * A rule body is capped by the editor contract; long documents split into
# * one item per ``##`` section so no item is silently truncated.
_BODY_LIMIT = 3500
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")


def _plain(line: str) -> str:
    """Strip inline Markdown, keeping readable plain text."""
    line = _LINK_RE.sub(r"\1", line)
    line = _BOLD_RE.sub(r"\1", line)
    line = line.replace("`", "")
    return line.strip()


def _sections(text: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Split a rule document into its title and ``##`` sections."""
    title = ""
    sections: list[tuple[str, list[str]]] = []
    current = ""
    lines: list[str] = []
    for raw in text.splitlines():
        match = _HEADING_RE.match(raw)
        if match is None:
            if raw.strip():
                lines.append(raw.rstrip())
            continue
        level, heading = len(match.group(1)), _plain(match.group(2))
        if level == 1:
            if not title:
                title = heading
            # * Drop the document preamble so it never becomes a rule item.
            lines = []
            continue
        if current or lines:
            sections.append((current, lines))
        current, lines = heading, []
    if current or lines:
        sections.append((current, lines))
    return title, sections


def _clean_block(lines: Iterable[str]) -> str:
    """Render section lines as plain text with list markers normalised."""
    cleaned: list[str] = []
    for line in lines:
        line = _LIST_RE.sub("", line)
        line = _plain(line)
        if line:
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def parse_rule(path: Path) -> list[tuple[str, str]]:
    """Return ``(title, body)`` items for one rule Markdown file.

    Each ``##`` section becomes one item. An empty document yields no items.
    The document H1 is used as a prefix in each title so items stay unique
    when several files share section names such as ``Istilah``.
    """
    text = path.read_text(encoding="utf-8")
    title, sections = _sections(text)
    base = title or path.stem.replace("-", " ").title()
    items: list[tuple[str, str]] = []
    for heading, lines in sections:
        # * The text between the H1 and the first "##" is a document
        # * description, not a rule of its own.
        if not heading:
            continue
        body = _clean_block(lines)
        if not body:
            continue
        item_title = f"{base}: {heading}"
        if len(body) > _BODY_LIMIT:
            raise ValueError(
                f"{path.name}: section {heading!r} is longer than {_BODY_LIMIT} chars"
            )
        items.append((item_title, body))
    return items


def parse_rules(folder: Path) -> dict[str, list[tuple[str, str]]]:
    """Return items keyed by source filename for every rule document."""
    return {path.name: parse_rule(path) for path in sorted(folder.glob("*.md"))}
