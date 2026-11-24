# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich messages: focused builders and the Kurigram native transport."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tcbot.modules.helper.rich import edit as rich_edit
from tcbot.modules.helper.rich import msg as rc
from tcbot.modules.helper.rich.button import button, button_row
from tcbot.modules.helper.rich.formats import (
    anchor,
    code,
    divider,
    emoji,
    footer,
    heading,
    highlight,
    math,
    math_block,
    paragraph,
    pull_quote,
    quote,
)
from tcbot.modules.helper.rich.link import link, user_ref
from tcbot.modules.helper.rich.list import bullet_list, details, ordered_list
from tcbot.modules.helper.rich.style import (
    bold,
    esc,
    italic,
    spoiler,
    strike,
    subscript,
    superscript,
    underline,
)
from tcbot.modules.helper.rich.table import table


class _FakeBot:
    """Record the native Kurigram rich calls made by the transport."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Any]] = []

    async def send_rich_message(
        self, chat_id: int | str, rich_message: Any, **kwargs: Any
    ) -> str:
        self.calls.append(
            (
                "sendRichMessage",
                {"chat_id": chat_id, "rich_message": rich_message, **kwargs},
                None,
            )
        )
        return "sent"

    async def edit_message_text(
        self, chat_id: int | str, message_id: int, **kwargs: Any
    ) -> str:
        self.calls.append(
            (
                "editMessageText",
                {"chat_id": chat_id, "message_id": message_id, **kwargs},
                None,
            )
        )
        return "edited"


def test_escaping_is_html_safe() -> None:
    assert esc('<b>&"') == "&lt;b&gt;&amp;&quot;"
    assert bold("<x>") == "<b>&lt;x&gt;</b>"
    assert bold("") == ""


def test_inline_helpers_cover_modern_formatting() -> None:
    assert italic("x") == "<i>x</i>"
    assert underline("x") == "<u>x</u>"
    assert strike("x") == "<s>x</s>"
    assert spoiler("x") == "<tg-spoiler>x</tg-spoiler>"
    assert code("x") == "<code>x</code>"
    assert link("t.me", "https://t.me/") == '<a href="https://t.me/">t.me</a>'


def test_user_ref_uses_id_and_avoids_dead_mentions() -> None:
    assert user_ref(42, "Name") == '<a href="tg://user?id=42">Name</a>'
    assert user_ref(0, "Anon") == "<b>Anon</b>"


def test_blocks_render_expected_rich_html() -> None:
    assert heading("Title") == "<h2>Title</h2>"
    assert heading("Title", 9) == "<h6>Title</h6>"
    assert divider() == "<hr/>"
    assert bullet_list(["a", "b"]) == "<ul><li>a</li><li>b</li></ul>"
    assert ordered_list(["a"], start=3) == '<ol start="3"><li>a</li></ol>'
    assert quote("q", expandable=True) == "<blockquote expandable>q</blockquote>"
    assert details("S", "B") == "<details><summary>S</summary>B</details>"


def test_quote_and_highlight_support_an_author() -> None:
    assert quote("q", author="Dizzy") == (
        "<blockquote>q<cite>Dizzy</cite></blockquote>"
    )
    assert quote("q", expandable=True, author="Dizzy") == (
        "<blockquote expandable>q<cite>Dizzy</cite></blockquote>"
    )
    assert highlight("x", author="Dizzy") == "<mark>x</mark> (Dizzy)"
    assert pull_quote("q", author="Dizzy") == "<aside>q<cite>Dizzy</cite></aside>"


def test_extra_inline_and_block_features_render() -> None:
    assert subscript("2") == "<sub>2</sub>"
    assert superscript("2") == "<sup>2</sup>"
    assert footer("End") == "<footer>End</footer>"
    assert anchor("a") == '<a name="a"></a>'
    assert math("x^2") == "<tg-math>x^2</tg-math>"
    assert math_block("x^2") == "<tg-math-block>x^2</tg-math-block>"
    assert emoji(123, "ok") == '<tg-emoji emoji-id="123">ok</tg-emoji>'
    assert ordered_list(["a"], marker="a", reversed_order=True) == (
        '<ol type="a" reversed><li>a</li></ol>'
    )


def test_table_renders_header_and_rows() -> None:
    html = table(["Name", "Status"], [["Alice", "OK"]])
    assert html.startswith("<table bordered>")
    assert "<th>Name</th>" in html
    assert "<td>Alice</td>" in html


def test_table_escapes_cells_unless_explicitly_raw() -> None:
    assert "<td>&lt;b&gt;x&lt;/b&gt;</td>" in table(["C"], [["<b>x</b>"]])
    assert "<td><b>x</b></td>" in table(["C"], [["<b>x</b>"]], raw_cells=True)


def test_button_rows_support_callback_and_url() -> None:
    row = button_row(
        [
            button("Go", data="rules_menu"),
            button("Open", url="https://t.me/"),
        ],
        align="center",
    )
    assert row.startswith('<tg-button-row align="center">')
    assert 'type="callback_data" data="rules_menu"' in row
    assert 'type="url" url="https://t.me/"' in row


def test_message_assembly_uses_exactly_one_content_field() -> None:
    html_msg = rc.html_message(heading("T"), paragraph("B"))
    assert set(html_msg) == {"html"}
    assert "<h2>T</h2>" in html_msg["html"]
    assert rc.blocks_message([{"type": "x"}]) == {"blocks": [{"type": "x"}]}


def test_send_rich_uses_native_kurigram_rich_message() -> None:
    bot = _FakeBot()
    message = rc.html_message(paragraph("hi"))
    result = asyncio.run(
        rc.send_rich(cast("Any", bot), -100, message, message_thread_id=7)
    )
    assert result == "sent"
    endpoint, kwargs, _ = bot.calls[0]
    assert endpoint == "sendRichMessage"
    assert kwargs["chat_id"] == -100
    assert kwargs["rich_message"].html == message["html"]
    assert kwargs["message_thread_id"] == 7


def test_edit_rich_uses_edit_message_text_with_rich_field() -> None:
    bot = _FakeBot()
    message = rc.html_message(paragraph("new"))
    asyncio.run(rich_edit.edit_rich(cast("Any", bot), -100, 55, message))
    endpoint, kwargs, _ = bot.calls[0]
    assert endpoint == "editMessageText"
    assert kwargs["message_id"] == 55
    assert kwargs["rich_message"].html == message["html"]


def test_edit_rich_uses_native_kurigram_rich_message() -> None:
    """Rich edits go through InputRichMessage, never a raw API escape hatch."""
    captured: dict[str, Any] = {}

    class _FakeClient:
        async def edit_message_text(
            self, chat_id: int, message_id: int, **kwargs: Any
        ) -> str:
            captured.update(kwargs)
            return "edited"

    asyncio.run(
        rich_edit.edit_rich(_FakeClient(), -100, 5, rc.html_message("<b>x</b>"))  # type: ignore[arg-type]
    )
    rich = captured["rich_message"]
    assert rich.html == "<b>x</b>"


def test_reply_markup_is_serialised_for_the_api() -> None:
    markup = InlineKeyboardMarkup([])
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(cast("Any", bot), -100, rc.html_message("x"), reply_markup=markup)
    )
    assert "reply_markup" not in bot.calls[0][1]


def test_rich_embeds_keyboard_as_rich_buttons() -> None:
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Go", callback_data="go"),
                InlineKeyboardButton("Open", url="https://t.me"),
            ]
        ]
    )
    bot = _FakeBot()
    message = rc.html_message("<p>body</p>")
    asyncio.run(rc.send_rich(cast("Any", bot), -100, message, reply_markup=markup))

    kwargs = bot.calls[0][1]
    html = kwargs["rich_message"].html
    assert "<tg-button-row>" in html
    assert 'type="callback_data" data="go"' in html
    assert 'type="url" url="https://t.me"' in html
    assert "reply_markup" not in kwargs
    assert message == {"html": "<p>body</p>"}


def test_rich_buttons_render_a_disabled_cell_as_a_rich_button() -> None:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("App")]])
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(cast("Any", bot), -100, rc.html_message("x"), reply_markup=markup)
    )
    kwargs = bot.calls[0][1]
    html = kwargs["rich_message"].html
    assert '<tg-button type="disabled">' in html
    assert "App</tg-button>" in html
    assert "reply_markup" not in kwargs


def test_rich_edit_embeds_buttons() -> None:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Go", callback_data="go")]])
    bot = _FakeBot()
    asyncio.run(
        rich_edit.edit_rich(
            cast("Any", bot),
            -100,
            1,
            rc.html_message("x"),
            reply_markup=markup,
        )
    )
    kwargs = bot.calls[0][1]
    assert "<tg-button-row>" in kwargs["rich_message"].html
    assert "reply_markup" not in kwargs
