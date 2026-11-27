# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich message payload assembly and block conversion.

Kurigram exposes ``InputRichMessage`` with exactly one content field (``html``,
``markdown`` or ``blocks``) plus optional attached ``media``. This module owns
the application's payload dictionaries and the conversion from a rendered
multiline fragment into real rich blocks. Sending, replying and editing consume
these payloads; they never assemble their own.
"""

from __future__ import annotations

import re
from typing import Any

from pyrogram.types import InputRichMessage

from tcbot.modules.helper.rich.button import buttons_from_markup
from tcbot.modules.helper.rich.formats import divider
from tcbot.utils.logger import get_logger

log = get_logger(__name__)

_CODE = r"<code>[^<]+</code>"
_COMMAND_LINE = re.compile(rf"^({_CODE})(.*)$")
_BARE_ALIAS = re.compile(rf"^{_CODE}(?:[\s,]+{_CODE})*$")
_BULLET_LINE = re.compile(r"^[-*]\s+(.*)$")
_ORDERED_LINE = re.compile(r"^\d+\.\s+(.*)$")
_BLOCK_TAGS = (
    "<p>",
    # * Bot API RichBlockAnchor: a standalone <a name> is a block, not a
    # * paragraph child. Other child tags are covered by their parent tags.
    "<a name=",
    "<pre",
    "<ul",
    "<ol",
    "<table",
    "<hr/>",
    "<blockquote",
    "<details",
    "<h1",
    "<h2",
    "<h3",
    "<h4",
    "<h5",
    "<h6",
    "<aside",
    "<img",
    "<video",
    "<footer",
    "<figure",
    "<figcaption",
    "<tg-map",
    "<audio",
    "<tg-document",
    "<tg-math-block",
    "<tg-slideshow",
    "<tg-collage",
    "<tg-button-row",
)


def html_message(
    *blocks: str,
    rtl: bool = False,
    skip_entity_detection: bool = False,
    media: list[Any] | None = None,
) -> dict[str, Any]:
    """Build a rich message payload keyed by HTML content."""
    payload: dict[str, Any] = {"html": "\n".join(b for b in blocks if b)}
    if rtl:
        payload["is_rtl"] = True
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    if media:
        payload["media"] = list(media)
    return payload


def blocks_message(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a rich message payload from explicit block objects."""
    return {"blocks": blocks}


def _markup_has_buttons(reply_markup: Any | None) -> bool:
    """Return True when a supplied markup actually carries button rows."""
    rows = getattr(reply_markup, "inline_keyboard", None)
    if rows is None and isinstance(reply_markup, dict):
        rows = reply_markup.get("inline_keyboard")
    return isinstance(rows, list) and any(isinstance(row, list) and row for row in rows)


def _message_with_buttons(
    message: dict[str, Any], reply_markup: Any | None
) -> dict[str, Any]:
    """Append rich button rows; never fall back to a native keyboard.

    Every bot message travels as one rich payload. A keyboard that cannot be
    expressed as rich buttons is dropped with a loud log rather than forwarded
    as a second representation. An empty or missing markup produces no rows;
    clearing an existing keyboard is the caller's explicit decision.
    """
    rows = buttons_from_markup(reply_markup)
    html_value = message.get("html")
    if not rows or not isinstance(html_value, str):
        if rows is None and _markup_has_buttons(reply_markup):
            log.error("Rich keyboard conversion failed; sending without buttons")
        return message
    payload = dict(message)
    separator = [] if html_value.rstrip().endswith("<hr/>") else [divider()]
    payload["html"] = "\n".join([html_value, *separator, *rows])
    return payload


def _input_rich(message: dict[str, Any]) -> InputRichMessage:
    """Convert an application rich payload into Kurigram's native payload."""
    kwargs: dict[str, Any] = {}
    if "html" in message:
        kwargs["html"] = message["html"]
    elif "blocks" in message:
        kwargs["blocks"] = message["blocks"]
    if message.get("is_rtl"):
        kwargs["is_rtl"] = True
    if message.get("skip_entity_detection"):
        kwargs["skip_entity_detection"] = True
    if message.get("media"):
        kwargs["media"] = message["media"]
    return InputRichMessage(**kwargs)


def _alias_cell(remainder: str) -> tuple[str, bool]:
    """Return the alias cell and whether this command row carries an alias."""
    stripped = remainder.strip()
    return stripped, bool(_BARE_ALIAS.fullmatch(stripped))


def blocks(
    text: str,
    *,
    command_header: str = "Command",
    alias_header: str = "Alias",
    detail_header: str = "Details",
    caption: str | None = None,
    table_header: bool = True,
) -> str:
    """Render a newline-separated rich fragment as rich block markup.

    Command lines become a two-column table, ``- `` lines a rich bullet list,
    ``1. `` lines an ordered list, and every other line its own paragraph.
    ``table_header=False`` omits the column header row for read-only views
    that already carry a title; the default keeps every existing caller's
    output unchanged.
    """
    if any(tag in text for tag in _BLOCK_TAGS):
        return text
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
    any_alias = False

    def flush_bullets() -> None:
        if bullets:
            parts.append("<ul>" + "".join(f"<li>{x}</li>" for x in bullets) + "</ul>")
            bullets.clear()

    def flush_ordered() -> None:
        if ordered:
            parts.append("<ol>" + "".join(f"<li>{x}</li>" for x in ordered) + "</ol>")
            ordered.clear()

    def flush_commands() -> None:
        nonlocal any_alias
        if not commands:
            return
        header = alias_header if any_alias else detail_header
        cap = f"<caption>{caption}</caption>" if caption else ""
        rows = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in commands)
        head = (
            f"<tr><th>{command_header}</th><th>{header}</th></tr>"
            if table_header
            else ""
        )
        parts.append(f"<table bordered>{cap}{head}{rows}</table>")
        commands.clear()
        any_alias = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_bullets()
            flush_ordered()
            flush_commands()
            continue
        command = _COMMAND_LINE.match(line)
        if command:
            flush_bullets()
            flush_ordered()
            detail, has_alias = _alias_cell(command.group(2))
            commands.append((command.group(1), detail))
            any_alias = any_alias or has_alias
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


__all__ = ["blocks", "blocks_message", "html_message"]
