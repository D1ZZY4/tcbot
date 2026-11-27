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

import re
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
# * Kurigram's RichMessageButton requires one action field and bounds callback
# * data to 1-64 bytes and copy text to 1-256 characters.
_CALLBACK_MAX_BYTES = 64
_COPY_MAX_CHARS = 256
_NATIVE_ONLY_FIELDS = (
    "user_id",
    "pay",
    "callback_game",
    "requires_password",
    "icon_custom_emoji_id",
)
# * A tg://user URL is normalised by Telegram into a user-profile button. The
# * client only accepts ids in 1..2^40-1 as users; larger values, chat ids and
# * sentinels reach Telegram and fail the whole message with BUTTON_USER_INVALID.
_MAX_MENTION_USER_ID: int = (1 << 40) - 1
# * Telegram's service account and the GroupAnonymousClient placeholder have no
# * addressable profile; identity classification imports the same constants.
TELEGRAM_USER_ID: int = 777000
ANONYMOUS_BOT_ID: int = 1087968824
_NON_PROFILE_USER_IDS: frozenset[int] = frozenset({TELEGRAM_USER_ID, ANONYMOUS_BOT_ID})
_USERNAME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def is_valid_username(username: object) -> bool:
    """Return True only for a shape-valid Telegram username."""
    return isinstance(username, str) and bool(_USERNAME_RE.fullmatch(username))


def is_mentionable_user_id(user_id: object) -> bool:
    """Return True only for an id Telegram accepts as a user-profile target."""
    return (
        isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and 0 < user_id <= _MAX_MENTION_USER_ID
        and user_id not in _NON_PROFILE_USER_IDS
    )


def _resolved_style(style: str | None) -> str:
    """Normalize a friendly or raw style name to the API spelling."""
    if not style:
        return ""
    key = style.strip().lower()
    return _STYLES.get(key, key)


def _style(style: str | None) -> str:
    resolved = _resolved_style(style)
    # * Telegram accepts only the four documented style names. An unknown
    # * value would fail parsing for the entire rich message, so a direct
    # * builder call drops it exactly like the keyboard-conversion path does.
    if resolved and resolved not in _RICH_BUTTON_STYLES:
        resolved = ""
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
    caller can build any documented button without raw HTML. Like Kurigram's
    ``RichMessageButton.write()``, exactly one action must be set.
    """
    actions = {
        "data": data,
        "url": url,
        "copy": copy,
        "web_app": web_app,
        "login_url": login_url,
        "switch_inline_query": switch_inline_query,
        "switch_inline_query_current_chat": switch_inline_query_current_chat,
        "switch_inline_query_chosen_chat": switch_inline_query_chosen_chat,
        "disabled": disabled if disabled else None,
    }
    provided = [name for name, value in actions.items() if value is not None]
    if len(provided) != 1:
        raise ValueError(
            f"Exactly one rich button action must be set, got {provided or 'none'}"
        )
    if data is not None and not 1 <= len(data.encode()) <= _CALLBACK_MAX_BYTES:
        raise ValueError("Rich button callback_data must be 1-64 bytes")
    if copy is not None and not 1 <= len(copy) <= _COPY_MAX_CHARS:
        raise ValueError("Rich button copy_text must be 1-256 characters")
    resolved = _resolved_style(style)
    if resolved == "link" and provided[0] != "data":
        raise ValueError("The link style is only valid for callback buttons")
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


def url_button(label: str, url: str, *, style: str | None = None) -> str:
    """Render a URL button."""
    return button(label, url=url, style=style)


def copy_button(label: str, text: str, *, style: str | None = None) -> str:
    """Render a copy-text button."""
    return button(label, copy=text, style=style)


def mention_button(
    user_id: int,
    name: str,
    *,
    username: str | None = None,
    style: str | None = None,
) -> str:
    """Render a rich mention button for a live, addressable user.

    A shape-valid username becomes an ordinary URL button. There is no
    ``tg://user`` form: Telegram turns it into a user-profile button and
    refuses any id without a live account, which fails the whole edit with
    ``BUTTON_USER_INVALID``. A user without a verified username therefore
    renders as escaped plain text, never as a message-breaking button.
    """
    label = name or str(user_id)
    # * A tg://user URL becomes a native user-profile button, and Telegram
    # * rejects it for every id whose account no longer exists. Shape checks
    # * cannot prove existence, and stored ban/role rows can outlive an
    # * account, so only a verified username becomes a button. Every other
    # * mention stays readable text rather than a message-breaking button.
    if is_valid_username(username) and is_mentionable_user_id(user_id):
        return url_button(label, f"https://t.me/{username}", style=style)
    return esc(label)


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
    if not 1 <= len(buttons) <= 8:
        raise ValueError("A rich button row holds 1-8 buttons")
    value = align if align in _ALIGNMENTS else None
    attr = f' align="{value}"' if value else ""
    return f"<tg-button-row{attr}>" + "".join(buttons) + "</tg-button-row>"


def button_rows(rows: list[list[str]], *, align: str | None = None) -> str:
    """Render several aligned button rows as one block."""
    return "\n".join(button_row(row, align=align) for row in rows if row)


def _has_native_only_action(cell: Any) -> bool:
    """Return True when a cell carries an action rich HTML cannot express."""
    if isinstance(cell, dict):
        if any(cell.get(name) is not None for name in _NATIVE_ONLY_FIELDS):
            return True
        login = cell.get("login_url")
        return isinstance(login, dict) and login.get("bot_username") is not None
    if any(getattr(cell, name, None) is not None for name in _NATIVE_ONLY_FIELDS):
        return True
    login = getattr(cell, "login_url", None)
    return login is not None and getattr(login, "bot_username", None) is not None


def _markup_dict(reply_markup: Any | None) -> dict[str, Any] | None:
    """Serialise a Kurigram inline keyboard to the dict shape used here."""
    if reply_markup is None:
        return None
    if isinstance(reply_markup, dict):
        dict_cells = reply_markup.get("inline_keyboard")
        if isinstance(dict_cells, list) and any(
            _has_native_only_action(cell)
            for row in dict_cells
            if isinstance(row, list)
            for cell in row
        ):
            return None
        return reply_markup
    rows = getattr(reply_markup, "inline_keyboard", None)
    if not isinstance(rows, list):
        return None
    encoded: list[list[dict[str, Any]]] = []
    for row in rows:
        cells: list[dict[str, Any]] = []
        for cell in row:
            # * Rich HTML has no equivalent for these native actions. The whole
            # * keyboard is dropped with an ERROR by the transport instead of
            # * becoming a second, native representation of the message.
            if _has_native_only_action(cell):
                return None
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
    unmappable cell drops the whole keyboard; no native representation is
    sent instead.
    """
    label = cell.get("text")
    if not isinstance(label, str):
        return None
    data = cell.get("callback_data")
    is_callback = isinstance(data, str) and bool(data)
    raw_style = cell.get("style")
    style_value = str(raw_style) if raw_style is not None else None
    if style_value is not None and style_value not in _RICH_BUTTON_STYLES:
        style_value = None
    if style_value == "link" and not is_callback:
        # * The link style is only valid on a callback button; drop it rather
        # * than raising and breaking the whole message.
        style_value = None
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
    if isinstance(copy, dict) and isinstance(copy.get("text"), str) and copy["text"]:
        if len(copy["text"]) > _COPY_MAX_CHARS:
            return None
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


def buttons_from_markup(reply_markup: object | None) -> list[str] | None:
    """Convert a Kurigram inline markup into rich button rows.

    Conversion is all-or-nothing: one cell that cannot be expressed as a rich
    button drops the whole keyboard, which the transport reports with an ERROR.
    There is no native representation of the message.
    """
    markup = _markup_dict(reply_markup)
    if markup is None:
        return None
    cells = markup.get("inline_keyboard")
    if not isinstance(cells, list) or not cells:
        return None
    rows: list[str] = []
    for row in cells:
        if not isinstance(row, list) or len(row) > 8:
            return None
        # * Paged keyboard builders emit an empty nav row on a single page.
        # * Dropping it is lossless and keeps those keyboards on the rich path.
        if not row:
            continue
        converted = [button_from_cell(cell) for cell in row]
        if any(item is None for item in converted):
            return None
        rows.append(button_row([item for item in converted if item]))
    return rows or None


__all__ = [
    "ANONYMOUS_BOT_ID",
    "TELEGRAM_USER_ID",
    "button",
    "button_from_cell",
    "button_row",
    "button_rows",
    "buttons_from_markup",
    "copy_button",
    "disabled_button",
    "is_mentionable_user_id",
    "is_valid_username",
    "login_button",
    "mention_button",
    "switch_button",
    "switch_chosen_button",
    "switch_current_button",
    "url_button",
    "web_app_button",
]
