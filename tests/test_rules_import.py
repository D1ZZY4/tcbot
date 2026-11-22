# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Local rule Markdown converts to plain-text items the bot can store."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import rules_import


def _doc(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "spam.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_sections_become_prefixed_plain_text_items(tmp_path: Path) -> None:
    path = _doc(
        tmp_path,
        "# Spam\n"
        "Intro line.\n"
        "## Aturan\n"
        "- **Dilarang** Spam dengan [tautan](https://example.com).\n"
        "## Sanksi\n"
        "Teguran tertulis.\n",
    )

    items = rules_import.parse_rule(path)

    assert [title for title, _ in items] == [
        "Spam: Aturan",
        "Spam: Sanksi",
    ]
    assert "Dilarang Spam dengan tautan" in items[0][1]
    assert "**" not in items[0][1]
    assert "https://example.com" not in items[0][1]
    assert "-" not in items[0][1].splitlines()[0]


def test_empty_and_markdown_only_sections_are_skipped(tmp_path: Path) -> None:
    path = _doc(tmp_path, "# Spam\n## Kosong\n\n## Isi\nTeks.\n")

    items = rules_import.parse_rule(path)

    assert items == [("Spam: Isi", "Teks.")]


def test_real_rule_documents_parse_within_body_limit() -> None:
    folder = Path(__file__).resolve().parent.parent / "rules"
    if not folder.is_dir():
        pytest.skip("local rules folder is operator-local and gitignored")

    parsed = rules_import.parse_rules(folder)

    assert parsed
    for items in parsed.values():
        assert items
        for title, body in items:
            assert title and body
            assert len(body) <= 3500
