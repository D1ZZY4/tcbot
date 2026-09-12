# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MarkdownV2 formatter escaping and entity shapes."""

from __future__ import annotations

from tcbot.utils.formatter import (
    bold,
    code,
    esc,
    italic,
    link,
    mention,
    pre,
    safe_username,
    user_ref,
)


def test_esc_escapes_v2_specials() -> None:
    assert esc("_*[\\`") == "\\_\\*\\[\\\\\\`"
    assert esc("a]b") == "a\\]b"
    assert esc("plain. text! (with) - dashes -") == (
        "plain\\. text\\! \\(with\\) \\- dashes \\-"
    )
    assert esc("") == ""


def test_bold_wraps_and_escapes() -> None:
    assert bold("hi") == "*hi*"
    assert bold("a_b*c") == "*a\\_b\\*c*"
    assert bold("") == ""


def test_italic_wraps_and_escapes() -> None:
    assert italic("hi") == "_hi_"
    assert italic("Tall_12") == "_Tall\\_12_"
    assert italic("") == ""


def test_code_keeps_inner_text_literal() -> None:
    assert code("a_b") == "`a_b`"
    assert code("a`b\\c") == "`a\\`b\\\\c`"
    assert code("") == ""


def test_pre_wraps_triple_backticks() -> None:
    assert pre("x_y") == "```x_y```"
    assert pre("") == ""


def test_link_escapes_text_and_parens_in_url() -> None:
    assert link("a_b", "https://t.me/x?a=b)") == "[a\\_b](https://t.me/x?a=b\\))"
    assert link("Go", "https://t.me/x") == "[Go](https://t.me/x)"


def test_user_ref_uses_id_link_and_ignores_username() -> None:
    assert user_ref(123, "A_B") == "[A\\_B](tg://user?id=123)"
    assert user_ref(123, "Ann", "ann_x") == "[Ann](tg://user?id=123)"
    assert mention(123, "Ann") == user_ref(123, "Ann")


def test_safe_username_shape() -> None:
    assert safe_username("valid_name123") == "valid_name123"
    assert safe_username("ab") is None
    assert safe_username("has space") is None
    assert safe_username(None) is None


def test_esc_covers_full_v2_set_multiline_unicode() -> None:
    assert esc("~>#+-=|{}.!") == "\\~\\>\\#\\+\\-\\=\\|\\{\\}\\.\\!"
    assert esc("line one\nline two") == "line one\nline two"
    assert esc("Halo, apa kabar? Baik-baik saja.") == (
        "Halo, apa kabar? Baik\\-baik saja\\."
    )
    assert esc("emoji \U0001f600 stays") == "emoji \U0001f600 stays"


def test_esc_escapes_backslash_itself() -> None:
    assert esc("a\\b") == "a\\\\b"
    assert esc("C:\\new") == "C:\\\\new"


def test_no_double_escape_when_helpers_nest_raw() -> None:
    # * Helpers escape, so pre-escaped input doubles up: callers must
    # * pass raw text and let the outermost helper escape exactly once.
    assert bold(esc("a_b")) == "*a\\\\\\_b*"
    assert esc("a\\.b") == "a\\\\\\.b"


def test_code_and_pre_leave_v2_punctuation_literal() -> None:
    assert code("a.b (x) - y!") == "`a.b (x) - y!`"
    assert pre("a_b") == "```a_b```"
    assert pre("x`y\\z") == "```x\\`y\\\\z```"


def test_link_keeps_query_intact_escapes_parens() -> None:
    assert link("a(b)", "https://t.me/c/1/2?x=1&y=2") == (
        "[a\\(b\\)](https://t.me/c/1/2?x=1&y=2)"
    )
    assert link("a)b\\c", "https://t.me/x") == "[a\\)b\\\\c](https://t.me/x)"
