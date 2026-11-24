# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Focused rich format modules keep their own responsibilities."""

from __future__ import annotations

from tcbot.modules.helper.rich import button as rich_buttons
from tcbot.modules.helper.rich import formats as rich_format
from tcbot.modules.helper.rich import link as rich_link
from tcbot.modules.helper.rich import list as rich_list
from tcbot.modules.helper.rich import media as rich_media
from tcbot.modules.helper.rich import style as rich_style
from tcbot.modules.helper.rich import table as rich_table
from tcbot.modules.helper.rich import text as rich_text
from tcbot.utils.i18n import t


def test_style_module_owns_inline_styles() -> None:
    assert rich_style.bold("<x>") == "<b>&lt;x&gt;</b>"
    assert rich_style.italic("x") == "<i>x</i>"
    assert rich_style.underline("x") == "<u>x</u>"
    assert rich_style.strike("x") == "<s>x</s>"
    assert rich_style.spoiler("x") == "<tg-spoiler>x</tg-spoiler>"
    assert rich_format.code("x") == "<code>x</code>"


def test_format_module_owns_blocks() -> None:
    for level in range(1, 7):
        assert rich_format.heading("T", level) == f"<h{level}>T</h{level}>"
    # * Levels outside the Bot API range clamp to h1/h6.
    assert rich_format.heading("T", 0) == "<h1>T</h1>"
    assert rich_format.heading("T", 9) == "<h6>T</h6>"
    assert rich_format.footnote_ref("n", "see") == '<a href="#n">see</a>'
    assert rich_format.highlight("x") == "<mark>x</mark>"
    assert rich_format.code_block("x", language="py") == (
        '<pre><code class="language-py">x</code></pre>'
    )
    assert rich_format.footnote("a", "A") == ('<tg-reference name="a">A</tg-reference>')
    assert rich_format.divider() == "<hr/>"
    assert rich_format.quote("q", expandable=True) == (
        "<blockquote expandable>q</blockquote>"
    )


def test_list_module_owns_lists_and_details() -> None:
    assert rich_list.bullet_list(["a"]) == "<ul><li>a</li></ul>"
    assert rich_list.ordered_list(["a"], start=3) == '<ol start="3"><li>a</li></ol>'
    assert rich_list.checklist([("done", True), ("todo", False)]) == (
        '<ul><li><input type="checkbox" checked>done</li>'
        '<li><input type="checkbox">todo</li></ul>'
    )
    assert rich_list.details("S", "B") == ("<details><summary>S</summary>B</details>")


def test_table_module_owns_tables() -> None:
    html = rich_table.table(["H"], [["<x>"]], compact=True, bordered=False)
    assert html.startswith("<table compact>")
    assert "<td>&lt;x&gt;</td>" in html


def test_link_module_owns_links_and_mentions() -> None:
    assert rich_link.link("t.me", "https://t.me") == ('<a href="https://t.me">t.me</a>')
    assert rich_link.mention(0, "Anon") == "<b>Anon</b>"
    assert rich_buttons.button("Go", data="go", style="green") == (
        '<tg-button type="callback_data" data="go" style="success">Go</tg-button>'
    )
    assert rich_buttons.button("Copy", copy="v") == (
        '<tg-button type="copy_text" text="v">Copy</tg-button>'
    )
    assert rich_buttons.button_row(
        [rich_buttons.button("Go", data="go")], align="right"
    ) == (
        '<tg-button-row align="right">'
        '<tg-button type="callback_data" data="go">Go</tg-button></tg-button-row>'
    )


def test_button_subfeatures_cover_the_documented_api() -> None:
    assert rich_buttons.url_button("Go", "https://x").startswith(
        '<tg-button type="url"'
    )
    assert rich_buttons.copy_button("Copy", "v") == (
        '<tg-button type="copy_text" text="v">Copy</tg-button>'
    )
    assert rich_buttons.web_app_button("App", "https://x") == (
        '<tg-button type="web_app" url="https://x">App</tg-button>'
    )
    assert rich_buttons.login_button(
        "Login", "https://x", forward_text="f", request_write_access=True
    ) == (
        '<tg-button type="login_url" url="https://x" forward-text="f"'
        " request-write-access>Login</tg-button>"
    )
    assert rich_buttons.switch_button("S", "q") == (
        '<tg-button type="switch_inline_query" query="q">S</tg-button>'
    )
    assert rich_buttons.switch_current_button("S", "q") == (
        '<tg-button type="switch_inline_query_current_chat" query="q">S</tg-button>'
    )
    assert rich_buttons.switch_chosen_button(
        "S", "q", allow_user_chats=True, allow_channel_chats=True
    ) == (
        '<tg-button type="switch_inline_query_chosen_chat" query="q"'
        " allow-user-chats allow-channel-chats>S</tg-button>"
    )
    assert rich_buttons.disabled_button("No") == (
        '<tg-button type="disabled">No</tg-button>'
    )
    assert rich_buttons.button("CB", data="d", style="link") == (
        '<tg-button type="callback_data" data="d" style="link">CB</tg-button>'
    )
    assert rich_buttons.button_rows([["a"], ["b"]]) == (
        "<tg-button-row>a</tg-button-row>\n<tg-button-row>b</tg-button-row>"
    )


def test_button_colours_map_to_api_styles() -> None:
    for friendly, api in (
        ("default", ""),
        ("blue", "primary"),
        ("green", "success"),
        ("red", "danger"),
    ):
        rendered = rich_buttons.button("OK", data="d", style=friendly)
        expected = f' style="{api}"' if api else ""
        assert (
            rendered
            == f'<tg-button type="callback_data" data="d"{expected}>OK</tg-button>'
        )


def test_button_row_supports_all_documented_alignments() -> None:
    one = rich_buttons.button("Go", data="go")
    for align in ("left", "center", "right"):
        assert rich_buttons.button_row([one], align=align) == (
            f'<tg-button-row align="{align}">{one}</tg-button-row>'
        )
    # * An unsupported value is dropped rather than shipped to Telegram.
    assert rich_buttons.button_row([one], align="full") == (
        f"<tg-button-row>{one}</tg-button-row>"
    )
    # * A single-button row is the supported full-width layout.
    assert rich_buttons.button_row([one]).count("<tg-button ") == 1


def test_media_module_owns_media_and_slideshow() -> None:
    assert rich_media.photo("https://x/i.jpg") == '<img src="https://x/i.jpg"/>'
    assert rich_media.video("https://x/v.mp4") == (
        '<video src="https://x/v.mp4"></video>'
    )
    assert rich_media.collage(["https://x/i.jpg"]) == (
        '<tg-collage><img src="https://x/i.jpg"/></tg-collage>'
    )
    assert rich_media.slideshow(["https://x/i.jpg"]) == (
        '<tg-slideshow><img src="https://x/i.jpg"/></tg-slideshow>'
    )


def test_focused_modules_stay_distinct() -> None:
    assert rich_format.heading is not rich_style.bold
    assert rich_table.table is not rich_buttons.button
    assert rich_media.slideshow is not rich_list.details


def test_text_blocks_renders_alias_commands_as_a_table() -> None:
    html = rich_text.blocks(
        "<code>/tcpromote</code> <code>/tcp</code>\n"
        "<code>/tcdemote</code> <code>/tcd</code>",
        command_header="Command",
        alias_header="Alias",
        caption="Commands &amp; Aliases",
    )
    assert html.startswith("<table bordered><caption>Commands &amp; Aliases</caption>")
    assert "<th>Command</th><th>Alias</th>" in html
    assert html.count("<tr>") == 3
    assert "<li>" not in html


def test_text_blocks_groups_other_line_kinds() -> None:
    html = rich_text.blocks(
        "Intro line\n\n- first\n- second\n\n1. step one\n2. step two\n\n"
        "<code>/tcban</code> with a reason",
        detail_header="Details",
    )
    assert html.startswith("<p>Intro line</p>")
    assert "<ul><li>first</li><li>second</li></ul>" in html
    assert "<ol><li>step one</li><li>step two</li></ol>" in html
    assert "<th>Command</th><th>Details</th>" in html


def test_help_command_section_uses_a_real_table() -> None:
    """The admin Commands & Aliases section is a table, not one long bullet."""
    rendered = rich_text.blocks(
        t("admins.help.commands.body", "en-US"),
        command_header=t("common.help.command", "en-US"),
        alias_header=t("common.help.alias", "en-US"),
        caption=t("common.section.commands", "en-US"),
    )
    assert rendered.count("<tr>") == 7
    assert "<th>Command</th><th>Alias</th>" in rendered
    assert "<li>" not in rendered
