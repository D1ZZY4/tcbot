# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich block formats: headings, text, quotes, highlights, code, footnotes, dividers."""

from __future__ import annotations

from tcbot.modules.helper.rich.style import esc


def heading(text: object, level: int = 2) -> str:
    """Render a section heading. Rich style supports h1 through h6."""
    content = esc(text)
    if not content:
        return ""
    tag = min(6, max(1, level))
    return f"<h{tag}>{content}</h{tag}>"


def paragraph(text: str) -> str:
    """Render already-formatted rich HTML as a paragraph."""
    return f"<p>{text}</p>" if text else ""


def quote(text: str, *, expandable: bool = False, author: object | None = None) -> str:
    """Render a block quotation with an optional attributed author.

    The Bot API has no ``author`` attribute on ``blockquote``; authorship is
    expressed by a ``<cite>`` element inside the quotation.
    """
    attr = " expandable" if expandable else ""
    credit = f"<cite>{esc(author)}</cite>" if author else ""
    return f"<blockquote{attr}>{text}{credit}</blockquote>"


def pull_quote(text: str, *, author: object | None = None) -> str:
    """Render a centred pull quote with an optional attributed author."""
    credit = f"<cite>{esc(author)}</cite>" if author else ""
    return f"<aside>{text}{credit}</aside>"


def code(text: object) -> str:
    """Render inline code rich text."""
    content = esc(text)
    return f"<code>{content}</code>" if content else ""


def pre(text: object) -> str:
    """Render a preformatted code block."""
    content = esc(text)
    return f"<pre><code>{content}</code></pre>" if content else ""


def highlight(text: object, *, author: object | None = None) -> str:
    """Render marked text, optionally credited to an author.

    ``<cite>`` is only valid inside blockquote, aside, and figcaption; a bare
    one after an inline ``<mark>`` is outside the supported rich HTML set. The
    credit is therefore escaped plain text following the mark.
    """
    content = esc(text)
    if not content:
        return ""
    credit = f" ({esc(author)})" if author else ""
    return f"<mark>{content}</mark>{credit}"


def code_block(text: object, *, language: str | None = None) -> str:
    """Render a preformatted code block, with an optional language class."""
    lang = f' class="language-{esc(language)}"' if language else ""
    return f"<pre><code{lang}>{esc(text)}</code></pre>"


def footnote(name: str, text: object) -> str:
    """Define a reference that a :func:`footnote_ref` link points to."""
    return f'<tg-reference name="{esc(name)}">{esc(text)}</tg-reference>'


def footnote_ref(name: str, label: object) -> str:
    """Render an in-document link to a footnote defined by :func:`footnote`."""
    return f'<a href="#{esc(name)}">{esc(label)}</a>'


def divider() -> str:
    """Render the horizontal rule block."""
    return "<hr/>"


def line_break() -> str:
    """Render an explicit line break inside a block."""
    return "<br/>"


def footer(text: object) -> str:
    """Render a footer block."""
    content = esc(text)
    return f"<footer>{content}</footer>" if content else ""


def anchor(name: str) -> str:
    """Render an in-document anchor that :func:`footnote_ref` can link to."""
    return f'<a name="{esc(name)}"></a>'


def math(expression: object) -> str:
    """Render an inline LaTeX expression."""
    content = esc(expression)
    return f"<tg-math>{content}</tg-math>" if content else ""


def math_block(expression: object) -> str:
    """Render a LaTeX expression as its own block."""
    content = esc(expression)
    return f"<tg-math-block>{content}</tg-math-block>" if content else ""


def time_tag(unix: int, fmt: str, label: object) -> str:
    """Render a formatted date-time entity."""
    # * Escape numeric attributes too: a value crossing a loose type boundary
    # * must never break out of the double-quoted attribute.
    return f'<tg-time unix="{esc(unix)}" format="{esc(fmt)}">{esc(label)}</tg-time>'


def emoji(emoji_id: int, alt: str) -> str:
    """Render a custom emoji by its numeric identifier."""
    return f'<tg-emoji emoji-id="{esc(emoji_id)}">{esc(alt)}</tg-emoji>'


__all__ = [
    "anchor",
    "code",
    "code_block",
    "divider",
    "emoji",
    "footer",
    "footnote",
    "footnote_ref",
    "heading",
    "highlight",
    "line_break",
    "math",
    "math_block",
    "paragraph",
    "pre",
    "pull_quote",
    "quote",
    "time_tag",
]
