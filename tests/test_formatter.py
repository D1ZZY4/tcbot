# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich HTML escaping and entity shapes used by catalog rendering."""

from __future__ import annotations

from tcbot.utils.i18n import (
    BULLET,
    SECTION_RULE,
    bold,
    bullet_list,
    code,
    esc,
    italic,
    link,
    pre,
    safe_username,
    section,
    strike,
    underline,
    user_ref,
)


def test_esc_escapes_html_metacharacters() -> None:
    assert esc('<b>&"') == "&lt;b&gt;&amp;&quot;"
    assert esc("plain. text! (with) - dashes -") == "plain. text! (with) - dashes -"
    assert esc("") == ""


def test_bold_wraps_and_escapes() -> None:
    assert bold("hi") == "<b>hi</b>"
    assert bold("a<b") == "<b>a&lt;b</b>"
    assert bold("") == ""


def test_italic_wraps_and_escapes() -> None:
    assert italic("hi") == "<i>hi</i>"
    assert italic("Tall_12") == "<i>Tall_12</i>"
    assert italic("") == ""


def test_code_keeps_inner_text_literal() -> None:
    assert code("a_b") == "<code>a_b</code>"
    assert code("") == ""


def test_pre_wraps_a_code_block() -> None:
    assert pre("x_y") == "<pre><code>x_y</code></pre>"
    assert pre("") == ""


def test_link_escapes_both_parts() -> None:
    assert link("a&b", "https://t.me/x?a=1&b=2") == (
        '<a href="https://t.me/x?a=1&amp;b=2">a&amp;b</a>'
    )
    assert link("Go", "https://t.me/x") == '<a href="https://t.me/x">Go</a>'


def test_user_ref_uses_id_link_and_ignores_username() -> None:
    assert user_ref(123, "A_B") == '<a href="tg://user?id=123">A_B</a>'
    assert user_ref(123, "Ann", "ann_x") == '<a href="tg://user?id=123">Ann</a>'


def test_user_ref_without_an_account_renders_bold_text() -> None:
    assert user_ref(0, "anonymous admin") == "<b>anonymous admin</b>"


def test_safe_username_shape() -> None:
    assert safe_username("valid_name123") == "valid_name123"
    assert safe_username("ab") is None
    assert safe_username("has space") is None
    assert safe_username(None) is None


def test_esc_keeps_unicode_and_newlines() -> None:
    assert esc("line one\nline two") == "line one\nline two"
    assert esc("Halo, apa kabar? Baik-baik saja.") == "Halo, apa kabar? Baik-baik saja."
    assert esc("emoji \U0001f600 stays") == "emoji \U0001f600 stays"


def test_underline_and_strike_escape_their_content() -> None:
    assert underline("a&b") == "<u>a&amp;b</u>"
    assert strike("a<b") == "<s>a&lt;b</s>"
    assert underline("") == ""
    assert strike("") == ""


def test_section_and_bullets_use_the_shared_vocabulary() -> None:
    body = bullet_list(["one", "two"])
    assert body == f"{BULLET} one\n{BULLET} two"
    rendered = section("Heading", body)
    assert rendered == f"<b>Heading</b>\n{SECTION_RULE}\n{BULLET} one\n{BULLET} two"
