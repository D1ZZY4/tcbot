# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich Telegram messages and the shared layout of formatted text.

Two responsibilities live here on purpose. First, the visual grammar that
every formatted reply already uses: a bold heading, a divider beneath it,
and arrow bullets with bold labels. Second, the modern rich-message API,
which adds headings, tables, block quotations, details blocks, inline
buttons, and media that plain MarkdownV2 cannot express.

Rich messages are a Bot API message type, not a ``parse_mode``. The pinned
python-telegram-bot release does not wrap ``sendRichMessage`` yet, but its
documented ``do_api_request`` escape hatch calls any current Bot API method,
so PTB remains the single Telegram transport. Kurigram is MTProto-only and
has no equivalent surface, which is why this module does not use it.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Any, cast

from tcbot.utils.formatter import BULLET, SECTION_RULE
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot, Message

log = get_logger(__name__)

# * Rich HTML style has its own named entity set. Escaping with quote=True
# * covers the five characters Telegram asks callers to replace.
_HTML_ESCAPE = html.escape


def esc(text: object) -> str:
    """Escape untrusted text for a rich HTML field."""
    return _HTML_ESCAPE(str(text), quote=True)


# ─────────────────────────── Inline formatting ────────────────────────── #


def bold(text: object) -> str:
    """Render bold rich text."""
    content = esc(text)
    return f"<b>{content}</b>" if content else ""


def italic(text: object) -> str:
    """Render italic rich text."""
    content = esc(text)
    return f"<i>{content}</i>" if content else ""


def underline(text: object) -> str:
    """Render underlined rich text."""
    content = esc(text)
    return f"<u>{content}</u>" if content else ""


def strike(text: object) -> str:
    """Render struck-through rich text."""
    content = esc(text)
    return f"<s>{content}</s>" if content else ""


def spoiler(text: object) -> str:
    """Render spoiler-rich text."""
    content = esc(text)
    return f"<tg-spoiler>{content}</tg-spoiler>" if content else ""


def code(text: object) -> str:
    """Render inline code rich text."""
    content = esc(text)
    return f"<code>{content}</code>" if content else ""


def link(text: object, url: str) -> str:
    """Render an inline link, escaping both label and URL."""
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def user_ref(user_id: int, name: str) -> str:
    """Mention a user by ID, the same identity rule as formatter.user_ref."""
    label = str(name) or str(user_id)
    if user_id <= 0:
        return bold(label)
    return link(label, f"tg://user?id={user_id}")


# ───────────────────────────── Block builders ─────────────────────────── #


def heading(text: object, level: int = 2) -> str:
    """Render a section heading. Rich style supports h1 through h6."""
    tag = min(6, max(1, level))
    return f"<h{tag}>{esc(text)}</h{tag}>"


def paragraph(text: str) -> str:
    """Render already-formatted rich HTML as a paragraph."""
    return f"<p>{text}</p>" if text else ""


def divider() -> str:
    """Render the horizontal rule block."""
    return "<hr/>"


def bullet_list(items: list[str]) -> str:
    """Render a bulleted list. Items may contain inline rich HTML."""
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items if item) + "</ul>"


def ordered_list(items: list[str], *, start: int | None = None) -> str:
    """Render an ordered list, optionally starting at a given number."""
    attr = f' start="{start}"' if start is not None else ""
    return (
        f"<ol{attr}>" + "".join(f"<li>{item}</li>" for item in items if item) + "</ol>"
    )


def quote(text: str, *, expandable: bool = False) -> str:
    """Render a block quotation, optionally collapsed by default."""
    attr = " expandable" if expandable else ""
    return f"<blockquote{attr}>{text}</blockquote>"


def details(summary: str, body: str, *, open: bool = False) -> str:
    """Render a collapsible details block."""
    attr = " open" if open else ""
    return f"<details{attr}><summary>{summary}</summary>{body}</details>"


def table(
    headers: list[str],
    rows: list[list[str]],
    *,
    bordered: bool = True,
    striped: bool = False,
    caption: str | None = None,
    raw_cells: bool = False,
) -> str:
    """Render a table. Up to 20 columns are supported by the Bot API.

    Cells are escaped by default. Set ``raw_cells`` only when every cell was
    built with the inline helpers above and is therefore trusted markup.
    """

    def cell(value: object) -> str:
        return str(value) if raw_cells else esc(value)

    flags = " bordered" if bordered else ""
    if striped:
        flags += " striped"
    parts = [f"<table{flags}>"]
    if caption:
        parts.append(f"<caption>{esc(caption)}</caption>")
    parts.append("<tr>" + "".join(f"<th>{cell(h)}</th>" for h in headers) + "</tr>")
    for row in rows:
        cells = "".join(f"<td>{cell(value)}</td>" for value in row)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return "".join(parts)


def button(
    label: str,
    *,
    style: str | None = None,
    data: str | None = None,
    url: str | None = None,
) -> str:
    """Render one inline rich button, callback or URL."""
    attrs = ""
    if data is not None:
        attrs = f' type="callback_data" data="{esc(data)}"'
    elif url is not None:
        attrs = f' type="url" url="{esc(url)}"'
    if style:
        attrs += f' style="{esc(style)}"'
    return f"<tg-button{attrs}>{esc(label)}</tg-button>"


def button_row(buttons: list[str], *, align: str | None = None) -> str:
    """Render one row of rich inline buttons."""
    attr = f' align="{esc(align)}"' if align else ""
    return f"<tg-button-row{attr}>" + "".join(buttons) + "</tg-button-row>"


def collage(urls: list[str]) -> str:
    """Render a collage block from media URLs."""
    return (
        "<tg-collage>"
        + "".join(f'<img src="{esc(url)}"/>' for url in urls)
        + "</tg-collage>"
    )


# ───────────────────────────── Message assembly ───────────────────────── #


def html_message(
    *blocks: str, rtl: bool = False, skip_entity_detection: bool = False
) -> dict[str, Any]:
    """Build an ``InputRichMessage`` with HTML content.

    Exactly one of ``html``, ``markdown``, or ``blocks`` is allowed by the
    Bot API, so this is the only field this helper sets.
    """
    payload: dict[str, Any] = {"html": "\n".join(b for b in blocks if b)}
    if rtl:
        payload["is_rtl"] = True
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    return payload


def markdown_message(
    markdown: str, *, rtl: bool = False, skip_entity_detection: bool = False
) -> dict[str, Any]:
    """Build an ``InputRichMessage`` with GitHub-flavored rich Markdown."""
    payload: dict[str, Any] = {"markdown": markdown}
    if rtl:
        payload["is_rtl"] = True
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    return payload


def blocks_message(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an ``InputRichMessage`` from explicit block objects."""
    return {"blocks": blocks}


# ───────────────────────────── Transport ──────────────────────────────── #


def _markup_dict(reply_markup: Any | None) -> dict[str, Any] | None:
    if reply_markup is None:
        return None
    if isinstance(reply_markup, dict):
        return reply_markup
    return reply_markup.to_dict()


def _unsupported_rich(exc: BaseException) -> bool:
    """Recognise a Bot API that does not offer the rich-message methods."""
    detail = str(exc).lower()
    return any(
        marker in detail
        for marker in (
            "method not found",
            "unknown method",
            "rich_message",
            "can't parse",
        )
    )


async def send_rich(
    bot: Bot,
    chat_id: int | str,
    message: dict[str, Any],
    *,
    reply_markup: Any | None = None,
    message_thread_id: int | None = None,
    disable_notification: bool | None = None,
    reply_to_message_id: int | None = None,
    fallback_text: str | None = None,
) -> Message:
    """Send a rich message through PTB's Bot API escape hatch.

    ``sendRichMessage`` returns a normal ``Message``, so callers can keep
    using the same object shape as every other Telegram send path. When the
    connected Bot API does not support rich messages and the caller supplied
    ``fallback_text``, the message is retried as ordinary MarkdownV2.
    """
    from telegram import Message as MessageType  # noqa: PLC0415 (heavy import on use)

    if not hasattr(bot, "do_api_request"):
        if fallback_text is None:
            raise RuntimeError("rich send needs a Bot with do_api_request support")
        log.debug("Bot has no do_api_request; using MarkdownV2 fallback.")
        return await bot.send_message(
            chat_id,
            fallback_text,
            parse_mode="MarkdownV2",
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            disable_notification=disable_notification,
        )

    api_kwargs: dict[str, Any] = {"chat_id": chat_id, "rich_message": message}
    markup = _markup_dict(reply_markup)
    if markup is not None:
        api_kwargs["reply_markup"] = markup
    if message_thread_id is not None:
        api_kwargs["message_thread_id"] = message_thread_id
    if disable_notification is not None:
        api_kwargs["disable_notification"] = disable_notification
    if reply_to_message_id is not None:
        api_kwargs["reply_parameters"] = {"message_id": reply_to_message_id}
    try:
        return await bot.do_api_request(
            "sendRichMessage", api_kwargs=api_kwargs, return_type=MessageType
        )
    except Exception as exc:
        if fallback_text is None or not _unsupported_rich(exc):
            raise
        log.warning("Rich send unsupported; retrying as MarkdownV2: %s", exc)
        return await bot.send_message(
            chat_id,
            fallback_text,
            parse_mode="MarkdownV2",
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            disable_notification=disable_notification,
        )


async def edit_rich(
    bot: Bot,
    chat_id: int | str,
    message_id: int,
    message: dict[str, Any],
    *,
    reply_markup: Any | None = None,
    fallback_text: str | None = None,
) -> Message:
    """Edit a message's rich content.

    The Bot API documents that ``editMessageText`` accepts ``rich_message``,
    so a rich panel can be refreshed in place like a text panel. A caller
    can supply ``fallback_text`` to retry as MarkdownV2 when the connected
    Bot API rejects the rich field.
    """
    from telegram import Message as MessageType  # noqa: PLC0415 (same reason)

    if not hasattr(bot, "do_api_request"):
        if fallback_text is None:
            raise RuntimeError("rich edit needs a Bot with do_api_request support")
        log.debug("Bot has no do_api_request; using MarkdownV2 fallback.")
        return cast(
            "Message",
            await bot.edit_message_text(
                fallback_text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="MarkdownV2",
                reply_markup=reply_markup,
            ),
        )

    api_kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "rich_message": message,
    }
    markup = _markup_dict(reply_markup)
    if markup is not None:
        api_kwargs["reply_markup"] = markup
    try:
        return await bot.do_api_request(
            "editMessageText", api_kwargs=api_kwargs, return_type=MessageType
        )
    except Exception as exc:
        if fallback_text is None or not _unsupported_rich(exc):
            raise
        log.warning("Rich edit unsupported; retrying as MarkdownV2: %s", exc)
        return cast(
            "Message",
            await bot.edit_message_text(
                fallback_text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="MarkdownV2",
                reply_markup=reply_markup,
            ),
        )


# ──────────────────────── Shared visual grammar ───────────────────────── #

# * A message built only from escaped text has no entities. The i18n contract
# * requires such messages to stay entity-free, so layout must not introduce
# * markup into them; the divider and the arrow are plain characters.
_HAS_ENTITY_RE: re.Pattern[str] = re.compile(r"(?<!\\)\*|(?<!\\)`|(?<!\\)\[")
_LIST_PREFIXES: tuple[str, ...] = ("- ", "• ", "· ")


def _is_heading(line: str) -> bool:
    if len(line) < 3 or not line.startswith("*") or not line.endswith("*"):
        return False
    return line[1:-1].find("*") < 0


def _bold_label(line: str) -> str:
    body = line[len(BULLET) + 1 :]
    marker = body.find(": ")
    if marker <= 0:
        return line
    label = body[:marker]
    if any(char in label for char in "*_`[]()"):
        return line
    return f"{BULLET} *{label}:*{body[marker + 1 :]}"


def style(text: str) -> str:
    """Apply the shared heading, rule, and bullet grammar to MarkdownV2 text.

    This is the layout pass used by existing MarkdownV2 send paths. It never
    re-escapes content and is idempotent, so a renderer that styles its own
    output is left alone. Rich surfaces build their own blocks with the
    helpers above instead of calling this function.
    """
    if not text or SECTION_RULE in text or "\n" not in text:
        return text

    lines = text.split("\n")
    rich = bool(_HAS_ENTITY_RE.search(text))
    first = lines[0]
    if (
        rich
        and first
        and not first.startswith(BULLET)
        and not any(char in first for char in "*_`[]")
        and len(first) <= 80
    ):
        lines[0] = f"*{first}*"

    result: list[str] = []
    for index, line in enumerate(lines):
        current = line
        for prefix in _LIST_PREFIXES:
            if current.startswith(prefix):
                current = f"{BULLET} {current[len(prefix) :]}"
                break
        if rich and current.startswith(f"{BULLET} "):
            current = _bold_label(current)
        result.append(current)
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if (
            following
            and following != SECTION_RULE
            and (_is_heading(current) or index == 0)
        ):
            result.append(SECTION_RULE)
    return "\n".join(result)


# ─────────────────── MarkdownV2 to rich HTML conversion ────────────────── #

_MDV2_SPECIALS = r"_*[]()~`>#+\-=|{}.!"
_MDV2_ESCAPE_RE = re.compile(r"\\([" + re.escape(_MDV2_SPECIALS) + r"])")
_MDV2_BOLD_RE = re.compile(r"(?<!\\)\*((?:[^*]|\\\*)+)\*(?!\\)")
_MDV2_UNDERLINE_RE = re.compile(r"(?<!\\)__((?:[^_]|\\_)+)__(?!\\)")
_MDV2_ITALIC_RE = re.compile(r"(?<!\\)_((?:[^_]|\\_)+)_(?!\\)")
_MDV2_STRIKE_RE = re.compile(r"(?<!\\)~((?:[^~]|\\~)+)~(?!\\)")
_MDV2_CODE_RE = re.compile(r"(?<!\\)`([^`]+)`(?!\\)")
_MDV2_LINK_RE = re.compile(r"(?<!\\)\[([^\]]+)\]\(([^)]+)\)")


def _mdv2_inline(text: str) -> str:
    """Convert inline MarkdownV2 markup to rich HTML, escaping plain text."""
    # * Decode MarkdownV2 backslash escapes into literal characters first.
    text = _MDV2_ESCAPE_RE.sub(r"\1", text)
    # * Links and code spans are extracted into placeholders so the later
    # * emphasis passes cannot rewrite their contents.
    saved: list[str] = []

    def _stash(value: str) -> str:
        saved.append(value)
        return f"\x00{len(saved) - 1}\x00"

    def _link(match: re.Match[str]) -> str:
        return _stash(
            f'<a href="{_HTML_ESCAPE(match.group(2), quote=True)}">'
            f"{_HTML_ESCAPE(match.group(1), quote=True)}</a>"
        )

    text = _MDV2_LINK_RE.sub(_link, text)
    text = _MDV2_CODE_RE.sub(
        lambda m: _stash(f"<code>{_HTML_ESCAPE(m.group(1), quote=True)}</code>"), text
    )
    text = _MDV2_UNDERLINE_RE.sub(
        lambda m: _stash(f"<u>{_HTML_ESCAPE(m.group(1), quote=True)}</u>"), text
    )
    text = _MDV2_BOLD_RE.sub(
        lambda m: _stash(f"<b>{_HTML_ESCAPE(m.group(1), quote=True)}</b>"), text
    )
    text = _MDV2_ITALIC_RE.sub(
        lambda m: _stash(f"<i>{_HTML_ESCAPE(m.group(1), quote=True)}</i>"), text
    )
    text = _MDV2_STRIKE_RE.sub(
        lambda m: _stash(f"<s>{_HTML_ESCAPE(m.group(1), quote=True)}</s>"), text
    )
    text = _HTML_ESCAPE(text, quote=False)
    for index, value in enumerate(saved):
        text = text.replace(f"\x00{index}\x00", value)
    return text


def from_markdown_v2(text: str) -> str:
    """Convert a project MarkdownV2 message into rich HTML.

    This is the single translation point for the existing i18n catalog. The
    old bold-heading-plus-rule grammar becomes a real rich heading, the
    legacy divider becomes ``<hr/>``, and arrow bullets become list items.
    """
    if not text:
        return ""
    lines = text.split("\n")
    out: list[str] = []
    bullets: list[str] = []

    def _flush() -> None:
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and set(stripped) == {SECTION_RULE[0]}:
            _flush()
            out.append("<hr/>")
            continue
        if stripped.startswith(BULLET):
            bullets.append(_mdv2_inline(stripped[len(BULLET) :].strip()))
            continue
        _flush()
        if not stripped:
            continue
        # * A single bold line followed by a divider was the project's
        # * heading grammar. Promote it to a real rich heading.
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        divider_next = bool(following) and set(following) == {SECTION_RULE[0]}
        if _is_heading(stripped) and divider_next:
            out.append(f"<h2>{_mdv2_inline(stripped[1:-1])}</h2>")
        else:
            out.append(f"<p>{_mdv2_inline(stripped)}</p>")
    _flush()
    return "\n".join(out)


def markdown_message_from(text: str) -> dict[str, Any]:
    """Build an InputRichMessage by converting an existing MarkdownV2 string."""
    return html_message(from_markdown_v2(text))


# * Kept as the public name of the layout pass so existing call sites move
# * with a single import change and keep the same behavior.
apply_style = style

__all__ = [
    "apply_style",
    "blocks_message",
    "bold",
    "bullet_list",
    "button",
    "button_row",
    "code",
    "collage",
    "details",
    "divider",
    "edit_rich",
    "esc",
    "from_markdown_v2",
    "heading",
    "html_message",
    "italic",
    "link",
    "markdown_message",
    "markdown_message_from",
    "ordered_list",
    "paragraph",
    "quote",
    "send_rich",
    "spoiler",
    "strike",
    "style",
    "table",
    "underline",
    "user_ref",
]
