# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich messages: builders and the PTB Bot API transport."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from tcbot.modules.helper.messages import rich


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


def test_escaping_is_html_safe() -> None:
    assert rich.esc('<b>&"') == "&lt;b&gt;&amp;&quot;"
    assert rich.bold("<x>") == "<b>&lt;x&gt;</b>"
    assert rich.bold("") == ""


def test_inline_helpers_cover_modern_formatting() -> None:
    assert rich.italic("x") == "<i>x</i>"
    assert rich.underline("x") == "<u>x</u>"
    assert rich.strike("x") == "<s>x</s>"
    assert rich.spoiler("x") == "<tg-spoiler>x</tg-spoiler>"
    assert rich.code("x") == "<code>x</code>"
    assert rich.link("t.me", "https://t.me/") == '<a href="https://t.me/">t.me</a>'


def test_user_ref_uses_id_and_avoids_dead_mentions() -> None:
    assert rich.user_ref(42, "Name") == ('<a href="tg://user?id=42">Name</a>')
    assert rich.user_ref(0, "Anon") == "<b>Anon</b>"


def test_blocks_render_expected_rich_html() -> None:
    assert rich.heading("Title") == "<h2>Title</h2>"
    assert rich.heading("Title", 9) == "<h6>Title</h6>"
    assert rich.divider() == "<hr/>"
    assert rich.bullet_list(["a", "b"]) == "<ul><li>a</li><li>b</li></ul>"
    assert rich.ordered_list(["a"], start=3) == '<ol start="3"><li>a</li></ol>'
    assert rich.quote("q", expandable=True) == "<blockquote expandable>q</blockquote>"
    assert rich.details("S", "B") == "<details><summary>S</summary>B</details>"


def test_table_renders_header_and_rows() -> None:
    html = rich.table(["Name", "Status"], [["Alice", "OK"]])
    assert html.startswith("<table bordered>")
    assert "<th>Name</th>" in html
    assert "<td>Alice</td>" in html


def test_table_escapes_cells_unless_explicitly_raw() -> None:
    assert "<td>&lt;b&gt;x&lt;/b&gt;</td>" in rich.table(["C"], [["<b>x</b>"]])
    assert "<td><b>x</b></td>" in rich.table(["C"], [["<b>x</b>"]], raw_cells=True)


def test_button_rows_support_callback_and_url() -> None:
    row = rich.button_row(
        [
            rich.button("Go", data="rules_menu"),
            rich.button("Open", url="https://t.me/"),
        ],
        align="center",
    )
    assert row.startswith('<tg-button-row align="center">')
    assert 'type="callback_data" data="rules_menu"' in row
    assert 'type="url" url="https://t.me/"' in row


def test_message_assembly_uses_exactly_one_content_field() -> None:
    html_msg = rich.html_message(rich.heading("T"), rich.paragraph("B"))
    assert set(html_msg) == {"html"}
    assert "<h2>T</h2>" in html_msg["html"]
    assert rich.markdown_message("**bold**") == {"markdown": "**bold**"}
    assert rich.blocks_message([{"type": "x"}]) == {"blocks": [{"type": "x"}]}


def test_send_rich_goes_through_ptb_do_api_request() -> None:
    bot = _FakeBot()
    message = rich.html_message(rich.paragraph("hi"))
    result = asyncio.run(
        rich.send_rich(cast("Any", bot), -100, message, message_thread_id=7)
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
    message = rich.html_message(rich.paragraph("new"))
    asyncio.run(rich.edit_rich(cast("Any", bot), -100, 55, message))
    endpoint, kwargs, _ = bot.calls[0]
    assert endpoint == "editMessageText"
    assert kwargs["message_id"] == 55
    assert kwargs["rich_message"] == message


def test_markdownv2_conversion_produces_rich_blocks() -> None:
    converted = rich.from_markdown_v2(
        "*Heading*\n━━━━━━━━━━━━━━━━━━━━\n➛ Owner: 1\n*bold* and `code`"
    )
    assert "<h2>Heading</h2>" in converted
    assert "<hr/>" in converted
    assert "<li>Owner: 1</li>" in converted
    assert "<b>bold</b>" in converted
    assert "<code>code</code>" in converted
    assert "━━" not in converted


def test_markdownv2_escapes_become_literal_text() -> None:
    assert rich.from_markdown_v2(r"Halo\- semua") == "<p>Halo- semua</p>"


def test_unsupported_rich_send_retries_as_markdownv2() -> None:
    class _UnsupportedBot(_FakeBot):
        async def do_api_request(self, *args: Any, **kwargs: Any) -> str:
            raise ValueError("method not found: sendRichMessage")

        async def send_message(self, *args: Any, **kwargs: Any) -> str:
            self.calls.append(("sendMessage", kwargs, None))
            return "fallback"

    bot = _UnsupportedBot()
    result = asyncio.run(
        rich.send_rich(
            cast("Any", bot), -100, rich.html_message("x"), fallback_text="*x*"
        )
    )
    assert result == "fallback"
    assert bot.calls[0][0] == "sendMessage"
    assert bot.calls[0][1]["parse_mode"] == "MarkdownV2"


def test_unsupported_rich_edit_retries_as_markdownv2() -> None:
    class _UnsupportedBot(_FakeBot):
        async def do_api_request(self, *args: Any, **kwargs: Any) -> str:
            raise ValueError("method not found: editMessageText")

        async def edit_message_text(self, *args: Any, **kwargs: Any) -> str:
            self.calls.append(("editMessageText", kwargs, None))
            return "fallback"

    bot = _UnsupportedBot()
    asyncio.run(
        rich.edit_rich(
            cast("Any", bot), -100, 1, rich.html_message("x"), fallback_text="*x*"
        )
    )
    assert bot.calls[0][0] == "editMessageText"
    assert bot.calls[0][1]["parse_mode"] == "MarkdownV2"


def test_reply_markup_is_serialised_for_the_api() -> None:
    class _Markup:
        def to_dict(self) -> dict[str, Any]:
            return {"inline_keyboard": []}

    bot = _FakeBot()
    asyncio.run(
        rich.send_rich(
            cast("Any", bot), -100, rich.html_message("x"), reply_markup=_Markup()
        )
    )
    assert bot.calls[0][1]["reply_markup"] == {"inline_keyboard": []}
