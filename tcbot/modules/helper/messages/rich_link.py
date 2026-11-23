# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich links, mentions, and the complete button feature set.

Button sub-features follow the Bot API 10.3 rich-message specification:

- types: callback, URL, Web App, login URL, switch-inline-query (three
  variants), copy-text, and disabled;
- colours: ``default`` (no style), ``blue`` (primary), ``green`` (success),
  ``red`` (danger), and ``link`` (borderless callback);
- rows: left, center, or right aligned, up to eight buttons per row.

Raw API style names are accepted as well as the friendly colour names.
"""

from __future__ import annotations

from typing import Any

from tcbot.modules.helper.messages.rich_style import bold, esc

_STYLES = {
    "default": "",
    "blue": "primary",
    "green": "success",
    "red": "danger",
}

# * The Bot API defines exactly these three horizontal alignments for a rich
# * button row. There is no full-width attribute; a single-button row is the
# * supported way to give one button a whole row.
_ALIGNMENTS = frozenset({"left", "center", "right"})


def link(text: object, url: str) -> str:
    """Render an inline link, escaping both label and URL."""
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def user_ref(user_id: int, name: str) -> str:
    """Mention a user by ID. Non-positive IDs render as bold text."""
    label = str(name) if name else str(user_id)
    if user_id <= 0:
        return bold(label)
    return link(label, f"tg://user?id={user_id}")


def mention(user_id: int, name: str) -> str:
    """Alias of :func:`user_ref` for call sites that read as a mention."""
    return user_ref(user_id, name)


def _style(style: str | None) -> str:
    if not style:
        return ""
    resolved = _STYLES.get(style.lower(), style)
    return f' style="{esc(resolved)}"' if resolved else ""


def button(
    label: str,
    *,
    style: str | None = None,
    data: str | None = None,
    url: str | None = None,
    copy: str | None = None,
    web_app: str | None = None,
    login_url: str | None = None,
    forward_text: str | None = None,
    request_write_access: bool = False,
    switch_inline_query: str | None = None,
    switch_inline_query_current_chat: str | None = None,
    switch_inline_query_chosen_chat: str | None = None,
    allow_user_chats: bool = False,
    allow_bot_chats: bool = False,
    allow_group_chats: bool = False,
    allow_channel_chats: bool = False,
    disabled: bool = False,
) -> str:
    """Render one rich button with exactly one action type.

    The keyword arguments map one-to-one to the Bot API button fields so a
    caller can build any documented button without raw HTML.
    """
    attrs = ""
    if data is not None:
        attrs = f' type="callback_data" data="{esc(data)}"'
    elif url is not None:
        attrs = f' type="url" url="{esc(url)}"'
    elif copy is not None:
        attrs = f' type="copy_text" text="{esc(copy)}"'
    elif web_app is not None:
        attrs = f' type="web_app" url="{esc(web_app)}"'
    elif login_url is not None:
        attrs = f' type="login_url" url="{esc(login_url)}"'
        if forward_text is not None:
            attrs += f' forward-text="{esc(forward_text)}"'
        if request_write_access:
            attrs += " request-write-access"
    elif switch_inline_query is not None:
        attrs = f' type="switch_inline_query" query="{esc(switch_inline_query)}"'
    elif switch_inline_query_current_chat is not None:
        attrs = (
            ' type="switch_inline_query_current_chat"'
            f' query="{esc(switch_inline_query_current_chat)}"'
        )
    elif switch_inline_query_chosen_chat is not None:
        attrs = (
            ' type="switch_inline_query_chosen_chat"'
            f' query="{esc(switch_inline_query_chosen_chat)}"'
        )
        if allow_user_chats:
            attrs += " allow-user-chats"
        if allow_bot_chats:
            attrs += " allow-bot-chats"
        if allow_group_chats:
            attrs += " allow-group-chats"
        if allow_channel_chats:
            attrs += " allow-channel-chats"
    elif disabled:
        attrs = ' type="disabled"'
    attrs += _style(style)
    return f"<tg-button{attrs}>{esc(label)}</tg-button>"


def callback_button(label: str, data: str, *, style: str | None = None) -> str:
    """Render a callback button."""
    return button(label, data=data, style=style)


def url_button(label: str, url: str, *, style: str | None = None) -> str:
    """Render a URL button."""
    return button(label, url=url, style=style)


def copy_button(label: str, text: str, *, style: str | None = None) -> str:
    """Render a copy-text button."""
    return button(label, copy=text, style=style)


def web_app_button(label: str, url: str, *, style: str | None = None) -> str:
    """Render a Web App button (private chats only)."""
    return button(label, web_app=url, style=style)


def login_button(
    label: str,
    url: str,
    *,
    forward_text: str | None = None,
    request_write_access: bool = False,
    style: str | None = None,
) -> str:
    """Render a Telegram Login URL button."""
    return button(
        label,
        login_url=url,
        forward_text=forward_text,
        request_write_access=request_write_access,
        style=style,
    )


def switch_button(label: str, query: str = "", *, style: str | None = None) -> str:
    """Render a switch-inline-query button."""
    return button(label, switch_inline_query=query, style=style)


def switch_current_button(
    label: str, query: str = "", *, style: str | None = None
) -> str:
    """Render a switch-inline-query-current-chat button."""
    return button(label, switch_inline_query_current_chat=query, style=style)


def switch_chosen_button(
    label: str,
    query: str = "",
    *,
    allow_user_chats: bool = False,
    allow_bot_chats: bool = False,
    allow_group_chats: bool = False,
    allow_channel_chats: bool = False,
    style: str | None = None,
) -> str:
    """Render a switch-inline-query-chosen-chat button."""
    return button(
        label,
        switch_inline_query_chosen_chat=query,
        allow_user_chats=allow_user_chats,
        allow_bot_chats=allow_bot_chats,
        allow_group_chats=allow_group_chats,
        allow_channel_chats=allow_channel_chats,
        style=style,
    )


def disabled_button(label: str, *, style: str | None = None) -> str:
    """Render a disabled button that does nothing."""
    return button(label, disabled=True, style=style)


def button_row(buttons: list[str], *, align: str | None = None) -> str:
    """Render one row of rich inline buttons.

    ``align`` is one of ``left``, ``center``, or ``right`` (an unknown value is
    ignored so an invalid attribute is never sent). Up to eight buttons belong
    in one row per the Bot API. A single-button row is the supported way to
    give one button a full row; the API has no full-width attribute.
    """
    value = align if align in _ALIGNMENTS else None
    attr = f' align="{value}"' if value else ""
    return f"<tg-button-row{attr}>" + "".join(buttons) + "</tg-button-row>"


def button_rows(rows: list[list[str]], *, align: str | None = None) -> str:
    """Render several aligned button rows as one block."""
    return "\n".join(button_row(row, align=align) for row in rows if row)


# ───────────────────── Inline keyboard to rich buttons ────────────────── #

# * Bot API style names accepted from a PTB inline keyboard button.
_RICH_BUTTON_STYLES = frozenset({"primary", "success", "danger", "link"})
# * Telegram caps callback_data at 64 bytes; a longer payload keeps the
# * original inline keyboard as the fallback.
_CALLBACK_MAX_BYTES = 64


def _markup_dict(reply_markup: Any | None) -> dict[str, Any] | None:
    """Serialise a PTB markup object or pass a dict through."""
    if reply_markup is None:
        return None
    if isinstance(reply_markup, dict):
        return reply_markup
    return reply_markup.to_dict()


def keyboard_button(cell: dict[str, object]) -> str | None:
    """Render one inline-keyboard cell as a rich button via :func:`button`.

    An unsupported style is dropped, leaving the button in its default
    color. Returns ``None`` only when the cell has no label, its callback
    exceeds 64 bytes, or it has no callback or URL. One unmappable cell
    keeps the whole keyboard inline.
    """
    label = cell.get("text")
    if not isinstance(label, str):
        return None
    raw_style = cell.get("style")
    style_value = str(raw_style) if raw_style is not None else None
    if style_value is not None and style_value not in _RICH_BUTTON_STYLES:
        style_value = None
    data = cell.get("callback_data")
    if isinstance(data, str) and data:
        if len(data.encode()) > _CALLBACK_MAX_BYTES:
            return None
        return button(label, data=data, style=style_value)
    url = cell.get("url")
    if isinstance(url, str) and url:
        return button(label, url=url, style=style_value)
    return None


def keyboard_rows(reply_markup: object | None) -> list[str] | None:
    """Convert a PTB inline keyboard into rich button rows, all-or-nothing."""
    markup = _markup_dict(reply_markup)
    if markup is None:
        return None
    cells = markup.get("inline_keyboard")
    if not isinstance(cells, list) or not cells:
        return None
    rows: list[str] = []
    for row in cells:
        if not isinstance(row, list) or not row:
            continue
        buttons = [keyboard_button(cell) for cell in row]
        if any(item is None for item in buttons):
            return None
        rows.append(button_row([item for item in buttons if item]))
    return rows or None


__all__ = [
    "button",
    "button_row",
    "button_rows",
    "callback_button",
    "copy_button",
    "disabled_button",
    "keyboard_button",
    "keyboard_rows",
    "link",
    "login_button",
    "mention",
    "switch_button",
    "switch_chosen_button",
    "switch_current_button",
    "url_button",
    "user_ref",
    "web_app_button",
]
