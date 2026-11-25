# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Uploaded Markdown becomes editable items and renders as rich blocks."""

from __future__ import annotations

from tcbot.modules.helper.pipelines.rules_markdown import (
    parse_description,
    parse_document,
    render_body,
    render_items,
)

_DOC = """# Spam Rules

Intro paragraph.

## Definitions

Unsolicited **bulk** messages and *links*.

---

## Sanctions

- First: warning
- Second: mute
"""


def test_parse_document_splits_headings_and_keeps_markdown() -> None:
    """H1 names the category; H2 sections become editable items."""
    items = parse_document(_DOC, "spam.md")
    assert [item["title"] for item in items] == [
        "Spam Rules: Definitions",
        "Spam Rules: Sanctions",
    ]
    assert all(item["category_key"] == "spam" for item in items)
    assert "**bulk**" in items[0]["body"]
    assert "---" in items[0]["body"]


def test_parse_description_reads_the_intro_paragraph() -> None:
    """The paragraph below H1 becomes the category description."""
    assert parse_description(_DOC) == "Intro paragraph."


def test_render_body_converts_inline_and_block_markdown() -> None:
    """Bold, italic, divider, and list markers become rich HTML."""
    html = render_body("**bold** and *italic*\n\n---\n\n- first")
    assert "<b>bold</b>" in html
    assert "<i>italic</i>" in html
    assert "<hr/>" in html
    assert "&bull;" in html


def test_render_items_uses_headings() -> None:
    """Each uploaded item renders under its own heading."""
    html = render_items(parse_document(_DOC, "spam.md"))
    assert "<h3>Spam Rules: Definitions</h3>" in html
    assert "<h3>Spam Rules: Sanctions</h3>" in html


def test_inline_markdown_escapes_special_characters_once() -> None:
    """A staff-authored ampersand must not survive as a literal entity."""
    html = render_body("`a&b` and **x<y** and *c&d*")
    assert "<code>a&amp;b</code>" in html
    assert "&amp;amp;" not in html
    assert "<b>x&lt;y</b>" in html
    assert "<i>c&amp;d</i>" in html
