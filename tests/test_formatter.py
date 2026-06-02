# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.formatter — pure HTML markup helpers."""

from __future__ import annotations

from tcbot.modules.helper.formatter import bold, code, esc, italic, link, mention


class TestBold:
    def test_wraps_in_b_tag(self):
        assert bold("hello") == "<b>hello</b>"

    def test_escapes_html(self):
        result = bold("<b>inject</b>")
        assert "<b><b>" not in result
        assert "&lt;b&gt;" in result

    def test_converts_non_string_via_str(self):
        result = bold(42)
        assert result == "<b>42</b>"

    def test_ampersand_escaped(self):
        result = bold("A & B")
        assert "&amp;" in result


class TestItalic:
    def test_wraps_in_i_tag(self):
        assert italic("hello") == "<i>hello</i>"

    def test_escapes_html(self):
        result = italic("<script>xss</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_converts_non_string(self):
        result = italic(3.14)
        assert result == "<i>3.14</i>"


class TestCode:
    def test_wraps_in_code_tag(self):
        assert code("abc123") == "<code>abc123</code>"

    def test_escapes_angle_brackets(self):
        result = code("<div>")
        assert "&lt;div&gt;" in result
        assert "<div>" not in result

    def test_converts_int(self):
        assert code(999) == "<code>999</code>"


class TestLink:
    def test_builds_anchor_tag(self):
        result = link("click here", "https://example.com")
        assert result == '<a href="https://example.com">click here</a>'

    def test_escapes_link_text(self):
        result = link("<b>bold</b>", "https://example.com")
        assert "&lt;b&gt;" in result
        assert "<b>" not in result

    def test_url_not_escaped(self):
        result = link("visit", "https://example.com/path?a=1&b=2")
        assert 'href="https://example.com/path?a=1&b=2"' in result

    def test_converts_text_to_str(self):
        result = link(42, "https://example.com")
        assert ">42<" in result


class TestMention:
    def test_with_username_creates_link(self):
        result = mention(12345, "Alice", "alice_handle")
        assert 'href="https://t.me/alice_handle"' in result
        assert "Alice" in result

    def test_without_username_uses_code_id(self):
        result = mention(12345, "Alice", None)
        assert "<code>12345</code>" in result
        assert "Alice" in result
        assert "href" not in result

    def test_without_username_default_arg(self):
        result = mention(12345, "Bob")
        assert "<code>12345</code>" in result

    def test_name_is_escaped_in_link(self):
        result = mention(1, "<Evil>", "evil")
        assert "<Evil>" not in result
        assert "&lt;Evil&gt;" in result

    def test_name_escaped_without_username(self):
        result = mention(1, "<Name>")
        assert "&lt;Name&gt;" in result

    def test_empty_username_uses_code_fallback(self):
        result = mention(99, "Zara", "")
        assert "<code>99</code>" in result


class TestEsc:
    def test_escapes_ampersand(self):
        assert esc("a & b") == "a &amp; b"

    def test_escapes_angle_brackets(self):
        assert esc("<div>") == "&lt;div&gt;"

    def test_escapes_quote(self):
        assert esc('"quoted"') == "&quot;quoted&quot;"

    def test_plain_text_unchanged(self):
        assert esc("hello world") == "hello world"

    def test_converts_non_string(self):
        result = esc(42)
        assert result == "42"

    def test_combined_special_chars(self):
        result = esc("<a href='x'>link & text</a>")
        assert "<" not in result
        assert ">" not in result
        assert "&amp;" in result
