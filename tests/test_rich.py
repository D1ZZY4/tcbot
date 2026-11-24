# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich messages: focused builders and the PTB Bot API transport."""

from __future__ import annotations

import asyncio
import warnings
from typing import Any, cast

import pytest
from telegram import Bot

from tcbot.modules.helper.messages import rich_edit
from tcbot.modules.helper.messages import rich_msg as rc
from tcbot.modules.helper.messages.rich_format import (
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
from tcbot.modules.helper.messages.rich_link import button, button_row, link, user_ref
from tcbot.modules.helper.messages.rich_list import bullet_list, details, ordered_list
from tcbot.modules.helper.messages.rich_style import (
    bold,
    esc,
    italic,
    spoiler,
    strike,
    subscript,
    superscript,
    underline,
)
from tcbot.modules.helper.messages.rich_table import table


class _FakeBot:
    """Record the do_api_request call made by the rich transport."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Any]] = []

    async def do_api_request(
        self,
        endpoint: str,
        api_kwargs: dict[str, Any] | None = None,
        return_type: Any = None,
    ) -> str:
        self.calls.append((endpoint, api_kwargs or {}, return_type))
        return "sent"

    async def edit_message_text(
        self,
        text: Any = None,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        api_kwargs: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> str:
        self.calls.append(
            (
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    **(api_kwargs or {}),
                },
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


def test_send_rich_goes_through_ptb_do_api_request() -> None:
    bot = _FakeBot()
    message = rc.html_message(paragraph("hi"))
    result = asyncio.run(
        rc.send_rich(cast("Any", bot), -100, message, message_thread_id=7)
    )
    assert result == "sent"
    endpoint, kwargs, return_type = bot.calls[0]
    assert endpoint == "sendRichMessage"
    assert kwargs["chat_id"] == -100
    assert kwargs["rich_message"] == message
    assert kwargs["message_thread_id"] == 7
    assert return_type is not None


def test_edit_rich_uses_edit_message_text_with_rich_field() -> None:
    bot = _FakeBot()
    message = rc.html_message(paragraph("new"))
    asyncio.run(rich_edit.edit_rich(cast("Any", bot), -100, 55, message))
    endpoint, kwargs, _ = bot.calls[0]
    assert endpoint == "editMessageText"
    assert kwargs["message_id"] == 55
    assert kwargs["rich_message"] == message


def test_edit_rich_does_not_emit_the_ptb_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = Bot("123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

    async def _edit(_self: object, **_kwargs: Any) -> str:
        return "edited"

    def _forbidden(_self: object, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("do_api_request must not be used for rich edits")

    monkeypatch.setattr(Bot, "edit_message_text", _edit)
    monkeypatch.setattr(Bot, "do_api_request", _forbidden)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(rich_edit.edit_rich(bot, -100, 5, rc.html_message("x")))

    assert not [w for w in caught if issubclass(w.category, UserWarning)]


def test_reply_markup_is_serialised_for_the_api() -> None:
    class _Markup:
        def to_dict(self) -> dict[str, Any]:
            return {"inline_keyboard": []}

    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot), -100, rc.html_message("x"), reply_markup=_Markup()
        )
    )
    assert bot.calls[0][1]["reply_markup"] == {"inline_keyboard": []}


def test_rich_embeds_keyboard_as_rich_buttons() -> None:
    class _Markup:
        def to_dict(self) -> dict[str, Any]:
            return {
                "inline_keyboard": [
                    [
                        {"text": "Go", "callback_data": "go", "style": "primary"},
                        {"text": "Open", "url": "https://t.me"},
                    ]
                ]
            }

    bot = _FakeBot()
    message = rc.html_message("<p>body</p>")
    asyncio.run(rc.send_rich(cast("Any", bot), -100, message, reply_markup=_Markup()))

    kwargs = bot.calls[0][1]
    html = kwargs["rich_message"]["html"]
    assert "<tg-button-row>" in html
    assert 'type="callback_data" data="go"' in html
    assert 'type="url" url="https://t.me"' in html
    assert "reply_markup" not in kwargs
    assert message == {"html": "<p>body</p>"}


def test_rich_buttons_keep_inline_markup_for_unmappable_cells() -> None:
    class _Markup:
        def to_dict(self) -> dict[str, Any]:
            return {
                "inline_keyboard": [
                    [{"text": "App", "web_app": {"url": "https://t.me"}}]
                ]
            }

    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot), -100, rc.html_message("x"), reply_markup=_Markup()
        )
    )
    kwargs = bot.calls[0][1]
    assert kwargs["reply_markup"]["inline_keyboard"][0][0]["text"] == "App"
    assert "tg-button" not in kwargs["rich_message"]["html"]


def test_rich_edit_embeds_buttons() -> None:
    class _Markup:
        def to_dict(self) -> dict[str, Any]:
            return {"inline_keyboard": [[{"text": "Go", "callback_data": "go"}]]}

    bot = _FakeBot()
    asyncio.run(
        rich_edit.edit_rich(
            cast("Any", bot),
            -100,
            1,
            rc.html_message("x"),
            reply_markup=_Markup(),
        )
    )
    kwargs = bot.calls[0][1]
    assert "<tg-button-row>" in kwargs["rich_message"]["html"]
