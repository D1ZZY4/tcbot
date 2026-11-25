# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich button rendering and inline-keyboard conversion for Kurigram.

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

from tcbot.modules.helper.rich.style import esc

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

# * Bot API style names accepted from a Kurigram inline keyboard button.
_RICH_BUTTON_STYLES = frozenset({"primary", "success", "danger", "link"})
# * Telegram caps callback_data at 64 bytes; a longer payload keeps the
# * original inline keyboard as the fallback.
_CALLBACK_MAX_BYTES = 64


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
    return (
        f'<tg-button type="callback_data" data="{esc(data)}"{_style(style)}>'
        f"{esc(label)}</tg-button>"
    )


def url_button(label: str, url: str, *, style: str | None = None) -> str:
    """Render a URL button."""
    return f'<tg-button type="url" url="{esc(url)}"{_style(style)}>{esc(label)}</tg-button>'


def copy_button(label: str, text: str, *, style: str | None = None) -> str:
    """Render a copy-text button."""
    return (
        f'<tg-button type="copy_text" text="{esc(text)}"{_style(style)}>'
        f"{esc(label)}</tg-button>"
    )


def mention_button(user_id: int, name: str, *, style: str | None = None) -> str:
    """Render a native rich button that mentions a user by numeric ID.

    Telegram has no separate mention button type: a mention is a URL button
    carrying ``tg://user?id=``. Keeping the construction here means callers do
    not build that URL themselves, and the button can be placed inline in a
    table cell as well as in a keyboard row. A non-positive ID has no target,
    so it renders as a disabled button rather than a dead link.
    """
    label = name or str(user_id)
    if user_id <= 0:
        return f'<tg-button type="disabled"{_style(style)}>{esc(label)}</tg-button>'
    return (
        f'<tg-button type="url" url="tg://user?id={user_id}"{_style(style)}>'
        f"{esc(label)}</tg-button>"
    )


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


def _markup_dict(reply_markup: Any | None) -> dict[str, Any] | None:
    """Serialise a Kurigram inline keyboard to the dict shape used here."""
    if reply_markup is None:
        return None
    if isinstance(reply_markup, dict):
        return reply_markup
    rows = getattr(reply_markup, "inline_keyboard", None)
    if not isinstance(rows, list):
        return None
    encoded: list[list[dict[str, Any]]] = []
    for row in rows:
        cells: list[dict[str, Any]] = []
        for cell in row:
            data: dict[str, Any] = {"text": getattr(cell, "text", "")}
            for name in (
                "callback_data",
                "url",
                "style",
                "switch_inline_query",
                "switch_inline_query_current_chat",
                "switch_inline_query_chosen_chat",
            ):
                value = getattr(cell, name, None)
                if value is not None:
                    data[name] = getattr(value, "value", value)
            for nested, fields in (
                ("web_app", ("url",)),
                ("login_url", ("url", "forward_text", "request_write_access")),
                ("copy_text", ("text",)),
            ):
                obj = getattr(cell, nested, None)
                if obj is None:
                    continue
                data[nested] = {
                    name: getattr(obj, name, None)
                    for name in fields
                    if getattr(obj, name, None) is not None
                }
            for flag in (
                "allow_user_chats",
                "allow_bot_chats",
                "allow_group_chats",
                "allow_channel_chats",
            ):
                value = getattr(cell, flag, None)
                if value is not None:
                    data[flag] = value
            cells.append(data)
        encoded.append(cells)
    return {"inline_keyboard": encoded}


def button_from_cell(cell: dict[str, object]) -> str | None:
    """Render one inline-markup cell as a rich button via :func:`button`.

    An unsupported style is dropped, leaving the button in its default
    color. Every Kurigram action maps to a rich button; ``None`` is returned
    only when the cell has no label or its callback exceeds 64 bytes. One
    unmappable cell keeps the whole keyboard inline.
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
    web_app = cell.get("web_app")
    if isinstance(web_app, dict) and isinstance(web_app.get("url"), str):
        return button(label, web_app=web_app["url"], style=style_value)
    login = cell.get("login_url")
    if isinstance(login, dict) and isinstance(login.get("url"), str):
        return button(
            label,
            login_url=login["url"],
            forward_text=login.get("forward_text"),
            request_write_access=bool(login.get("request_write_access", False)),
            style=style_value,
        )
    copy = cell.get("copy_text")
    if isinstance(copy, dict) and isinstance(copy.get("text"), str):
        return button(label, copy=copy["text"], style=style_value)
    switch_query = cell.get("switch_inline_query")
    if isinstance(switch_query, str):
        return button(label, switch_inline_query=switch_query, style=style_value)
    switch_current = cell.get("switch_inline_query_current_chat")
    if isinstance(switch_current, str):
        return button(
            label,
            switch_inline_query_current_chat=switch_current,
            style=style_value,
        )
    switch_chosen = cell.get("switch_inline_query_chosen_chat")
    if isinstance(switch_chosen, str):
        return button(
            label,
            switch_inline_query_chosen_chat=switch_chosen,
            allow_user_chats=bool(cell.get("allow_user_chats", False)),
            allow_bot_chats=bool(cell.get("allow_bot_chats", False)),
            allow_group_chats=bool(cell.get("allow_group_chats", False)),
            allow_channel_chats=bool(cell.get("allow_channel_chats", False)),
            style=style_value,
        )
    if not any(
        cell.get(name)
        for name in (
            "callback_data",
            "url",
            "web_app",
            "login_url",
            "copy_text",
            "switch_inline_query",
            "switch_inline_query_current_chat",
            "switch_inline_query_chosen_chat",
        )
    ):
        return button(label, disabled=True, style=style_value)
    return None


def _button_from_obj(cell: Any) -> str | None:
    """Convert a Kurigram InlineKeyboardButton directly without dict allocation."""
    label = getattr(cell, "text", None)
    if not isinstance(label, str):
        return None
    raw_style = getattr(cell, "style", None)
    if raw_style is not None:
        style_val = getattr(raw_style, "value", raw_style)
        style_s = str(style_val)
        style_attr = (
            f' style="{esc(style_s)}"' if style_s in _RICH_BUTTON_STYLES else ""
        )
    else:
        style_attr = ""

    data = getattr(cell, "callback_data", None)
    if isinstance(data, str) and data:
        if len(data) > _CALLBACK_MAX_BYTES or (
            not data.isascii() and len(data.encode()) > _CALLBACK_MAX_BYTES
        ):
            return None
        return (
            f'<tg-button type="callback_data" data="{esc(data)}"{style_attr}>'
            f"{esc(label)}</tg-button>"
        )
    url = getattr(cell, "url", None)
    if isinstance(url, str) and url:
        return (
            f'<tg-button type="url" url="{esc(url)}"{style_attr}>'
            f"{esc(label)}</tg-button>"
        )
    web_app = getattr(cell, "web_app", None)
    if web_app is not None:
        web_url = getattr(web_app, "url", None)
        if isinstance(web_url, str):
            return (
                f'<tg-button type="web_app" url="{esc(web_url)}"{style_attr}>'
                f"{esc(label)}</tg-button>"
            )
    login = getattr(cell, "login_url", None)
    if login is not None:
        login_url = getattr(login, "url", None)
        if isinstance(login_url, str):
            fwd = getattr(login, "forward_text", None)
            rwa = bool(getattr(login, "request_write_access", False))
            attrs = f' type="login_url" url="{esc(login_url)}"'
            if fwd is not None:
                attrs += f' forward-text="{esc(fwd)}"'
            if rwa:
                attrs += " request-write-access"
            return f"<tg-button{attrs}{style_attr}>{esc(label)}</tg-button>"
    copy = getattr(cell, "copy_text", None)
    if copy is not None:
        copy_txt = getattr(copy, "text", None)
        if isinstance(copy_txt, str):
            return (
                f'<tg-button type="copy_text" text="{esc(copy_txt)}"{style_attr}>'
                f"{esc(label)}</tg-button>"
            )
    switch_query = getattr(cell, "switch_inline_query", None)
    if isinstance(switch_query, str):
        return (
            f'<tg-button type="switch_inline_query" query="{esc(switch_query)}"'
            f"{style_attr}>{esc(label)}</tg-button>"
        )
    switch_current = getattr(cell, "switch_inline_query_current_chat", None)
    if isinstance(switch_current, str):
        return (
            f'<tg-button type="switch_inline_query_current_chat"'
            f' query="{esc(switch_current)}"{style_attr}>{esc(label)}</tg-button>'
        )
    switch_chosen = getattr(cell, "switch_inline_query_chosen_chat", None)
    if isinstance(switch_chosen, str):
        attrs = f' type="switch_inline_query_chosen_chat" query="{esc(switch_chosen)}"'
        if getattr(cell, "allow_user_chats", False):
            attrs += " allow-user-chats"
        if getattr(cell, "allow_bot_chats", False):
            attrs += " allow-bot-chats"
        if getattr(cell, "allow_group_chats", False):
            attrs += " allow-group-chats"
        if getattr(cell, "allow_channel_chats", False):
            attrs += " allow-channel-chats"
        return f"<tg-button{attrs}{style_attr}>{esc(label)}</tg-button>"
    if (
        data is None
        and url is None
        and web_app is None
        and login is None
        and copy is None
    ):
        return f'<tg-button type="disabled"{style_attr}>{esc(label)}</tg-button>'
    return None


def buttons_from_markup(reply_markup: object | None) -> list[str] | None:
    """Convert a Kurigram inline markup into rich button rows.

    Conversion is all-or-nothing: one cell that cannot be expressed as a rich
    button keeps the whole keyboard as native inline markup, so no button is
    silently lost.
    """
    if reply_markup is None:
        return None
    if isinstance(reply_markup, dict):
        cells = reply_markup.get("inline_keyboard")
        if not isinstance(cells, list) or not cells:
            return None
        rows: list[str] = []
        for row in cells:
            if not isinstance(row, list) or not row:
                continue
            converted: list[str] = []
            for cell in row:
                item = button_from_cell(cell)
                if item is None:
                    return None
                converted.append(item)
            rows.append(f"<tg-button-row>{''.join(converted)}</tg-button-row>")
        return rows or None
    inline_rows = getattr(reply_markup, "inline_keyboard", None)
    if not isinstance(inline_rows, list) or not inline_rows:
        return None
    rows = []
    for row in inline_rows:
        if not isinstance(row, list) or not row:
            continue
        converted = []
        for cell in row:
            item = (
                button_from_cell(cell)
                if isinstance(cell, dict)
                else _button_from_obj(cell)
            )
            if item is None:
                return None
            converted.append(item)
        rows.append(f"<tg-button-row>{''.join(converted)}</tg-button-row>")
    return rows or None


__all__ = [
    "button",
    "button_from_cell",
    "button_row",
    "button_rows",
    "buttons_from_markup",
    "callback_button",
    "copy_button",
    "disabled_button",
    "login_button",
    "mention_button",
    "switch_button",
    "switch_chosen_button",
    "switch_current_button",
    "url_button",
    "web_app_button",
]
