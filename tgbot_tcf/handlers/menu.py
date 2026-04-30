# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Start-menu, interactive help, information, and privacy callbacks.

The Telegram event plumbing (per-message ownership tracking, callback
routing, ``edit_message_text`` swallowing) lives here. The catalogue of
help modules and copy lives in :mod:`tgbot_tcf.modules.help_text`,
keyboards in :mod:`tgbot_tcf.modules.keyboards`, and copy in
:mod:`tgbot_tcf.modules.messages`.
"""
from __future__ import annotations

import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import ABOUT_TEXT
from ..modules import keyboards
from ..modules.help_text import HELP_DETAILS, HELP_MODULE_ROWS
from ..modules.messages import M
from .helper import messaging
from .lists import build_admins_text, build_fedgroups_text, build_fedstats_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------- ownership tracking

def _state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return context.application.bot_data.setdefault("menu_state", {})


def _key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _remember(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    mode: str,
) -> None:
    _state(context)[_key(chat_id, message_id)] = {
        "user_id": user_id,
        "mode": mode,
    }


def _get_entry(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
) -> dict[str, Any] | None:
    return _state(context).get(_key(chat_id, message_id))


def _is_owner(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
) -> bool:
    s = _get_entry(context, chat_id, message_id)
    return s is None or s["user_id"] == user_id


def _mode(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
) -> str:
    s = _get_entry(context, chat_id, message_id)
    return s["mode"] if s else "menu"


# ---------------------------------------------------------- entry points

async def send_start_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    sent = await msg.reply_text(
        M.START_WELCOME,
        reply_markup=keyboards.start_menu(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _remember(context, sent.chat.id, sent.message_id, user.id, "menu")


async def send_help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    sent = await msg.reply_text(
        M.HELP_INTRO,
        reply_markup=keyboards.help_modules(
            HELP_MODULE_ROWS, with_back_to_start=False
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _remember(context, sent.chat.id, sent.message_id, user.id, "cmd")


# ----------------------------------------------------------- main router

async def on_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    cq = update.callback_query
    if (
        cq is None
        or cq.message is None
        or getattr(cq, "from_user", None) is None
        or getattr(cq, "data", None) is None
    ):
        return
    chat_id = cq.message.chat.id
    message_id = cq.message.message_id

    if not _is_owner(context, chat_id, message_id, cq.from_user.id):
        await cq.answer(M.MENU_OWNER_ONLY_ALERT, show_alert=True)
        return

    await cq.answer()
    data = cq.data
    mode = _mode(context, chat_id, message_id)

    if data == "menu_back_start":
        await messaging.safe_edit_callback(
            cq, M.START_WELCOME, keyboards.start_menu()
        )
        return

    if data == "menu_about":
        await messaging.safe_edit_callback(cq, ABOUT_TEXT, keyboards.back_to_start())
        return

    if data == "menu_help":
        await messaging.safe_edit_callback(
            cq,
            M.HELP_INTRO,
            keyboards.help_modules(HELP_MODULE_ROWS, with_back_to_start=True),
        )
        return

    if data == "menu_help_main":
        await messaging.safe_edit_callback(
            cq,
            M.HELP_INTRO,
            keyboards.help_modules(
                HELP_MODULE_ROWS, with_back_to_start=(mode == "menu")
            ),
        )
        return

    if data == "menu_groups":
        groups_text = await build_fedgroups_text()
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Back", callback_data="menu_back_start")]]
        )
        await messaging.safe_edit_callback(cq, groups_text, kb)
        return

    if data == "menu_additional":
        from .links import get_links_view

        text, links_kb = get_links_view()
        rows = list(links_kb.inline_keyboard) + [
            [InlineKeyboardButton("Back", callback_data="menu_back_start")]
        ]
        await messaging.safe_edit_callback(cq, text, InlineKeyboardMarkup(rows))
        return

    if data == "menu_information":
        info_text = await build_fedstats_text(context)
        info_text = info_text.replace(
            "<b>TCF Statistics</b>", M.INFORMATION_HEADER
        )
        await messaging.safe_edit_callback(cq, info_text, keyboards.info_main())
        return

    if data == "info_admins":
        admins_text = await build_admins_text(context)
        await messaging.safe_edit_callback(
            cq, admins_text, keyboards.back_to_information()
        )
        return

    if data == "info_chats":
        chats_text = await build_fedgroups_text()
        await messaging.safe_edit_callback(
            cq, chats_text, keyboards.back_to_information()
        )
        return

    if data == "menu_privacy":
        await messaging.safe_edit_callback(
            cq, M.PRIVACY_MAIN, keyboards.privacy_menu()
        )
        return

    if data == "menu_privacy_policy":
        await messaging.safe_edit_callback(
            cq, M.PRIVACY_POLICY, keyboards.back_to_privacy(), parse_mode=None
        )
        return

    if data in HELP_DETAILS:
        await messaging.safe_edit_callback(
            cq,
            HELP_DETAILS[data],
            keyboards.help_detail(with_main_menu_button=(mode == "menu")),
        )
        return
