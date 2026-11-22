# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared rich-text contracts: verbatim styling and block conversion.

Rich messages carry their own markup, so ``style`` is a verbatim passthrough.
``blocks`` converts an already-rendered multiline fragment into real rich
blocks. Catalog strings arrive from ``t()`` with literal text escaped and
`` `code` `` / ``*bold*`` spans already resolved to ``<code>`` / ``<b>``, so
the converter only groups lines and never escapes them again.
"""

from __future__ import annotations

import re

_CODE = r"<code>[^<]+</code>"
_COMMAND_LINE = re.compile(rf"^({_CODE})(.*)$")
_ALIAS_WRAPPER = re.compile(r"\((?:alias|aliases):\s*(.+?)\)")
# * A second bare code span on a command line is the alias cell. The rich
# * table already labels that column, so no "(alias: ...)" prose is needed.
_BARE_ALIAS = re.compile(rf"^{_CODE}(?:[\s,]+{_CODE})*$")
_BULLET_LINE = re.compile(r"^[-*]\s+(.*)$")
_ORDERED_LINE = re.compile(r"^\d+\.\s+(.*)$")
_BLOCK_TAGS = (
    "<p>",
    "<ul>",
    "<ol>",
    "<table",
    "<hr/>",
    "<blockquote",
    "<details",
    "<tg-button-row",
)


def style(text: str) -> str:
    """Return rich text unchanged; rich messages own their formatting."""
    return text


def _alias_cell(remainder: str) -> tuple[str, bool]:
    """Return the alias cell and whether this command row has an alias."""
    stripped = remainder.strip()
    if _BARE_ALIAS.fullmatch(stripped):
        return stripped, True
    match = _ALIAS_WRAPPER.search(remainder)
    if match is None:
        return stripped, False
    cleaned = remainder[: match.start()] + match.group(1) + remainder[match.end() :]
    return cleaned.strip(), True


def blocks(
    text: str,
    *,
    command_header: str = "Command",
    alias_header: str = "Alias",
    detail_header: str = "Details",
    caption: str | None = None,
) -> str:
    """Render a newline-separated rich fragment as rich block markup.

    Command lines become a two-column table, ``- `` lines a rich bullet list,
    ``1. `` lines an ordered list, and every other line its own paragraph.
    The second column uses the alias header when every command row carries an
    alias marker; otherwise it uses the details header. Alias wrappers and
    their parentheses are removed from the cell content.
    """
    if any(tag in text for tag in _BLOCK_TAGS):
        return text
    # * A single plain line needs no wrapper; short notices keep their exact
    # * wording and existing callers keep their asserted output.
    if "\n" not in text and not (
        _BULLET_LINE.match(text)
        or _ORDERED_LINE.match(text)
        or _COMMAND_LINE.match(text)
    ):
        return text

    parts: list[str] = []
    bullets: list[str] = []
    ordered: list[str] = []
    commands: list[tuple[str, str]] = []
    all_aliases = True

    def flush_bullets() -> None:
        if bullets:
            parts.append("<ul>" + "".join(f"<li>{x}</li>" for x in bullets) + "</ul>")
            bullets.clear()

    def flush_ordered() -> None:
        if ordered:
            parts.append("<ol>" + "".join(f"<li>{x}</li>" for x in ordered) + "</ol>")
            ordered.clear()

    def flush_commands() -> None:
        nonlocal all_aliases
        if not commands:
            return
        header = alias_header if all_aliases else detail_header
        cap = f"<caption>{caption}</caption>" if caption else ""
        rows = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in commands)
        parts.append(
            f"<table bordered>{cap}<tr><th>{command_header}</th><th>{header}</th></tr>{rows}</table>"
        )
        commands.clear()
        all_aliases = True

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_bullets()
            flush_ordered()
            flush_commands()
            continue
        command = _COMMAND_LINE.match(line)
        if command and command.group(2).strip():
            flush_bullets()
            flush_ordered()
            detail, has_alias = _alias_cell(command.group(2))
            if detail:
                commands.append((command.group(1), detail))
                all_aliases = all_aliases and has_alias
            continue
        bullet = _BULLET_LINE.match(line)
        if bullet:
            flush_ordered()
            flush_commands()
            bullets.append(bullet.group(1))
            continue
        numbered = _ORDERED_LINE.match(line)
        if numbered:
            flush_bullets()
            flush_commands()
            ordered.append(numbered.group(1))
            continue
        flush_bullets()
        flush_ordered()
        flush_commands()
        parts.append(f"<p>{line}</p>")
    flush_bullets()
    flush_ordered()
    flush_commands()
    return "".join(parts)


__all__ = ["blocks", "style"]
