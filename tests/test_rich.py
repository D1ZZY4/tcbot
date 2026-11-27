# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich messages: focused builders and the Kurigram native transport."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from pyrogram.enums import ButtonStyle
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichMessage,
    InputRichMessageMedia,
)

from tcbot.modules.helper.rich import block as rich_block
from tcbot.modules.helper.rich import edit_msg as rich_edit
from tcbot.modules.helper.rich import media as rich_media
from tcbot.modules.helper.rich import send_msg as rc
from tcbot.modules.helper.rich.button import (
    button,
    button_row,
    is_mentionable_user_id,
    mention_button,
)
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
    time_tag,
)
from tcbot.modules.helper.rich.link import link
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
from tcbot.modules.helper.rich.table import table, table_cell
from tcbot.utils.i18n import user_ref


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


def test_user_ref_uses_native_rich_mention_buttons() -> None:
    assert user_ref(42, "Name") == "Name"
    assert user_ref(42, "Name", "real_user") == (
        '<tg-button type="url" url="https://t.me/real_user">Name</tg-button>'
    )
    assert user_ref(0, "Anon") == "Anon"
    # * A pseudo-account id is never a valid profile target, even when an
    # * observed username is available.
    assert user_ref(0, "Anon", "cached_name") == "Anon"


def test_mention_id_gate_rejects_every_non_user_shape() -> None:
    """The roster's get_users batch must never receive an invalid peer id."""
    assert is_mentionable_user_id(42) is True
    assert is_mentionable_user_id((1 << 40) - 1) is True
    for value in (
        0,
        -1,
        True,
        False,
        1.5,
        float("nan"),
        "123",
        None,
        1 << 40,
        777000,
        1087968824,
    ):
        assert is_mentionable_user_id(value) is False


def test_unaddressable_ids_never_become_user_profile_buttons() -> None:
    """A stored id must never turn a rich edit into BUTTON_USER_INVALID."""
    for value in (
        0,
        -1,
        True,
        1.5,
        float("nan"),
        "123",
        None,
        1 << 40,
        777000,
        1087968824,
    ):
        rendered = user_ref(value, "Name")  # type: ignore[arg-type]
        assert rendered == "Name"
        assert "tg://user?id=" not in rendered
        assert mention_button(value, "Name") == rendered  # type: ignore[arg-type]


def test_safe_edit_cb_can_explicitly_clear_a_keyboard() -> None:
    """A decided card must not keep its old buttons after a text edit."""

    class _Query:
        def __init__(self) -> None:
            self.kwargs: list[dict[str, Any]] = []

        async def edit_message_text(self, **kwargs: Any) -> str:
            self.kwargs.append(kwargs)
            return "edited"

    q = _Query()
    assert asyncio.run(rich_edit.safe_edit_cb(q, "done", clear_markup=True)) is True  # type: ignore[arg-type]
    assert q.kwargs[0]["reply_markup"].inline_keyboard == []


def test_standalone_keyboard_clear_uses_the_native_endpoint() -> None:
    """Both keyboard-only helpers send an explicit empty markup."""

    class _Target:
        def __init__(self, *, fail: bool = False) -> None:
            self.kwargs: list[dict[str, Any]] = []
            self.fail = fail

        async def edit_message_reply_markup(self, **kwargs: Any) -> None:
            self.kwargs.append(kwargs)
            if self.fail:
                raise RuntimeError("Message to edit not found")

    bot = _Target()
    asyncio.run(rich_edit.clear_markup(cast("Any", bot), -100, 5))
    assert bot.kwargs[0] == {
        "chat_id": -100,
        "message_id": 5,
        "reply_markup": InlineKeyboardMarkup([]),
    }

    query = _Target()
    asyncio.run(rich_edit.clear_markup_cb(cast("Any", query)))
    assert query.kwargs[0] == {"reply_markup": InlineKeyboardMarkup([])}

    benign = _Target(fail=True)
    asyncio.run(rich_edit.clear_markup(cast("Any", benign), -100, 6))
    assert len(benign.kwargs) == 1


def test_embedded_file_id_media_serializes_without_an_upload() -> None:
    """A file id is decoded locally; no client upload call is needed."""
    rich = InputRichMessage(
        html='<tg-slideshow><img src="tg://photo?id=m0"/></tg-slideshow>',
        media=[
            InputRichMessageMedia(
                "m0", InputMediaPhoto("AgACAgEAAwF4AAIBAAcCAAcBAAcCAAMBAAcCAAcBAAMeBA")
            )
        ],
    )

    written = rich.write(client=None, chat_id=None)

    assert written.files is not None
    assert len(written.files) == 1
    assert written.files[0].id == "m0"


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


def test_rich_values_follow_kurigram_constraints() -> None:
    with pytest.raises(ValueError):
        rich_media.slideshow([("bad id", "photo")])
    with pytest.raises(ValueError):
        rich_media.slideshow([("m0", "thinking")])
    with pytest.raises(ValueError):
        time_tag(1, "bad", "label")
    assert ordered_list(["x"], marker="bad") == "<ol><li>x</li></ol>"


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


def test_a_button_can_live_inside_a_table_cell() -> None:
    """A raw cell keeps inline rich markup, including a button, verbatim."""
    html = table(["Action"], [[table_cell(button("Go", data="go"), raw=True)]])
    assert '<td><tg-button type="callback_data" data="go">Go</tg-button></td>' in html
    other = table(["Action"], [[table_cell(button("Go", data="go"))]])
    assert "&lt;tg-button" in other


def test_an_empty_navigation_row_does_not_force_native_markup() -> None:
    """Single-page keyboards emit empty rows; they must stay fully rich."""
    markup = {
        "inline_keyboard": [
            [{"text": "Topic", "callback_data": "topic"}],
            [],
            [{"text": "Close", "callback_data": "close"}],
        ]
    }
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot),
            -100,
            rich_block.html_message("<p>body</p>"),
            reply_markup=markup,
        )
    )
    kwargs = bot.calls[0][1]
    assert "reply_markup" not in kwargs
    assert kwargs["rich_message"].html.count("<tg-button-row>") == 2


def test_message_assembly_uses_exactly_one_content_field() -> None:
    html_msg = rich_block.html_message(heading("T"), paragraph("B"))
    assert set(html_msg) == {"html"}
    assert "<h2>T</h2>" in html_msg["html"]
    assert rich_block.blocks_message([{"type": "x"}]) == {"blocks": [{"type": "x"}]}


def test_send_rich_uses_native_kurigram_rich_message() -> None:
    bot = _FakeBot()
    message = rich_block.html_message(paragraph("hi"))
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
    message = rich_block.html_message(paragraph("new"))
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
        rich_edit.edit_rich(_FakeClient(), -100, 5, rich_block.html_message("<b>x</b>"))  # type: ignore[arg-type]
    )
    rich = captured["rich_message"]
    assert rich.html == "<b>x</b>"


def test_reply_markup_is_serialised_for_the_api() -> None:
    markup = InlineKeyboardMarkup([])
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot), -100, rich_block.html_message("x"), reply_markup=markup
        )
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
    message = rich_block.html_message("<p>body</p>")
    asyncio.run(rc.send_rich(cast("Any", bot), -100, message, reply_markup=markup))

    kwargs = bot.calls[0][1]
    html = kwargs["rich_message"].html
    assert "<tg-button-row>" in html
    assert 'type="callback_data" data="go"' in html
    assert 'type="url" url="https://t.me"' in html
    assert "reply_markup" not in kwargs
    assert message == {"html": "<p>body</p>"}


def test_an_unconvertible_keyboard_is_forwarded_as_native_markup() -> None:
    """One overlong callback keeps the whole keyboard, not zero buttons."""
    markup = {"inline_keyboard": [[{"text": "Long", "callback_data": "x" * 65}]]}
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot), -100, rich_block.html_message("x"), reply_markup=markup
        )
    )
    kwargs = bot.calls[0][1]
    assert kwargs["reply_markup"] is markup
    assert "<tg-button-row>" not in kwargs["rich_message"].html


def test_a_link_style_url_button_drops_the_style_instead_of_raising() -> None:
    """The link style is callback-only; a URL button must not break a send."""
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Open", url="https://t.me", style=ButtonStyle.LINK)]]
    )
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot), -100, rich_block.html_message("x"), reply_markup=markup
        )
    )
    html = bot.calls[0][1]["rich_message"].html
    assert 'type="url" url="https://t.me"' in html
    assert 'style="link"' not in html


def test_a_profile_button_keeps_the_native_keyboard() -> None:
    """A native action without a rich equivalent must stay clickable."""
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Profile", user_id=42)]])
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot), -100, rich_block.html_message("x"), reply_markup=markup
        )
    )
    kwargs = bot.calls[0][1]
    assert kwargs["reply_markup"] is markup
    assert '<tg-button type="disabled">' not in kwargs["rich_message"].html


def test_rich_buttons_render_a_disabled_cell_as_a_rich_button() -> None:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("App")]])
    bot = _FakeBot()
    asyncio.run(
        rc.send_rich(
            cast("Any", bot), -100, rich_block.html_message("x"), reply_markup=markup
        )
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
            rich_block.html_message("x"),
            reply_markup=markup,
        )
    )
    kwargs = bot.calls[0][1]
    assert "<tg-button-row>" in kwargs["rich_message"].html
    assert "reply_markup" not in kwargs


def test_an_empty_markup_object_still_clears_the_keyboard() -> None:
    """An explicit empty keyboard and a None markup mean the same thing."""
    bot = _FakeBot()
    asyncio.run(
        rich_edit.safe_edit_message(
            cast("Any", bot),
            -100,
            1,
            "x",
            reply_markup=InlineKeyboardMarkup([]),
        )
    )
    assert bot.calls[0][1]["reply_markup"].inline_keyboard == []


def test_rich_edit_can_clear_a_keyboard() -> None:
    bot = _FakeBot()
    asyncio.run(
        rich_edit.edit_rich(
            cast("Any", bot), -100, 1, rich_block.html_message("x"), clear_markup=True
        )
    )
    kwargs = bot.calls[0][1]
    assert kwargs["reply_markup"].inline_keyboard == []
