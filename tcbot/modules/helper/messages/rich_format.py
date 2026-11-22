# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich block formats: headings, text, quotes, highlights, code, footnotes, dividers."""

from __future__ import annotations

from tcbot.modules.helper.messages.rich_style import esc


def heading(text: object, level: int = 2) -> str:
    """Render a section heading. Rich style supports h1 through h6."""
    tag = min(6, max(1, level))
    return f"<h{tag}>{esc(text)}</h{tag}>"


def paragraph(text: str) -> str:
    """Render already-formatted rich HTML as a paragraph."""
    return f"<p>{text}</p>" if text else ""


def quote(text: str, *, expandable: bool = False) -> str:
    """Render a block quotation, optionally collapsed by default."""
    attr = " expandable" if expandable else ""
    return f"<blockquote{attr}>{text}</blockquote>"


def code(text: object) -> str:
    """Render inline code rich text."""
    content = esc(text)
    return f"<code>{content}</code>" if content else ""


def pre(text: object) -> str:
    """Render a preformatted code block."""
    content = esc(text)
    return f"<pre><code>{content}</code></pre>" if content else ""


def highlight(text: object) -> str:
    """Render marked text, corresponding to the rich ``<mark>`` tag."""
    content = esc(text)
    return f"<mark>{content}</mark>" if content else ""


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


__all__ = [
    "code",
    "code_block",
    "divider",
    "footnote",
    "footnote_ref",
    "heading",
    "highlight",
    "paragraph",
    "pre",
    "quote",
]
