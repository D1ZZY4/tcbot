# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich block formats: headings, text, quotes, highlights, code, maps and footnotes.

Every helper returns rich HTML inline or block markup. Untrusted text is
escaped by ``rich.style.esc``; callers may pass trusted rendered markup only
where a helper explicitly documents it.
"""

from __future__ import annotations

import re

from tcbot.modules.helper.rich.style import esc

# * Kurigram's date-time entity accepts exactly this format alphabet.
_TIME_FORMAT_RE = re.compile(r"r|w?[dD]?[tT]?")


def heading(text: object, level: int = 2) -> str:
    """Render an h1-h6 section heading. Empty text renders nothing."""
    content = esc(text)
    if not content:
        return ""
    size = min(6, max(1, level))
    return f"<h{size}>{content}</h{size}>"


def paragraph(text: str) -> str:
    """Render already-formatted rich HTML as a paragraph."""
    return f"<p>{text}</p>" if text else ""


def quote(text: str, *, expandable: bool = False, author: object | None = None) -> str:
    """Render a block quotation with an optional attributed author."""
    attr = " expandable" if expandable else ""
    credit = f"<cite>{esc(author)}</cite>" if author else ""
    return f"<blockquote{attr}>{text}{credit}</blockquote>"


def pull_quote(text: str, *, author: object | None = None) -> str:
    """Render a centred pull quote with an optional credited author."""
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
    """Render marked text with an escaped plain-text credit."""
    content = esc(text)
    if not content:
        return ""
    credit = f" ({esc(author)})" if author else ""
    return f"<mark>{content}</mark>{credit}"


def code_block(text: object, *, language: str | None = None) -> str:
    """Render a preformatted code block with an optional language class."""
    lang = f' class="language-{esc(language)}"' if language else ""
    return f"<pre><code{lang}>{esc(text)}</code></pre>"


def footnote(name: str, text: object) -> str:
    """Define a reference that :func:`footnote_ref` can link to."""
    return f'<tg-reference name="{esc(name)}">{esc(text)}</tg-reference>'


def footnote_ref(name: str, label: object) -> str:
    """Render an in-document link to a defined reference."""
    return f'<a href="#{esc(name)}">{esc(label)}</a>'


def divider() -> str:
    """Render the horizontal rule block."""
    return "<hr/>"


def footer(text: object) -> str:
    """Render a footer block."""
    content = esc(text)
    return f"<footer>{content}</footer>" if content else ""


def anchor(name: str) -> str:
    """Render an in-document anchor."""
    return f'<a name="{esc(name)}"></a>'


def math(expression: object) -> str:
    """Render an inline LaTeX expression."""
    content = esc(expression)
    return f"<tg-math>{content}</tg-math>" if content else ""


def math_block(expression: object) -> str:
    """Render a LaTeX block."""
    content = esc(expression)
    return f"<tg-math-block>{content}</tg-math-block>" if content else ""


def map_block(
    latitude: float,
    longitude: float,
    *,
    zoom: int | None = None,
    caption: str | None = None,
    credit: object | None = None,
) -> str:
    """Render a map block with an optional figure caption and credit.

    ``zoom`` follows Kurigram's 0-24 range. Width and height are fields of the
    typed block but are not part of the rich HTML tag, so they are not exposed.
    """
    if zoom is not None and not 0 <= zoom <= 24:
        raise ValueError(f"Invalid rich map zoom: {zoom!r}")
    attrs = f' lat="{esc(latitude)}" long="{esc(longitude)}"'
    if zoom is not None:
        attrs += f' zoom="{int(zoom)}"'
    tag = f"<tg-map{attrs}/>"
    if not caption and credit is None:
        return tag
    cite = f"<cite>{esc(credit)}</cite>" if credit else ""
    label = esc(caption) if caption else ""
    return f"<figure>{tag}<figcaption>{label}{cite}</figcaption></figure>"


def time_tag(unix: int, fmt: str, label: object) -> str:
    """Render a formatted date-time entity.

    An invalid ``fmt`` is rejected here rather than shipping markup Telegram
    cannot parse. Numeric attributes are escaped as well.
    """
    if not _TIME_FORMAT_RE.fullmatch(fmt):
        raise ValueError(f"Invalid rich date-time format: {fmt!r}")
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
    "map_block",
    "math",
    "math_block",
    "paragraph",
    "pre",
    "pull_quote",
    "quote",
    "time_tag",
]
