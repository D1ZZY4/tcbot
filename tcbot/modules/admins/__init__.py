# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Admin management handlers: promote, demote, transfer ownership, and manage requests."""

from __future__ import annotations

from telegram.ext import CallbackQueryHandler, MessageHandler

from tcbot.modules.admins.decision import on_promo_decision
from tcbot.modules.admins.demote import cmd_demote, on_demote_cancel, on_demote_confirm
from tcbot.modules.admins.promote import (
    cmd_promote,
    on_promote_role_btn,
    on_promote_role_cancel,
)
from tcbot.modules.admins.queue import cmd_promote_list, cmd_promote_request
from tcbot.modules.admins.shared import (
    _RL_BULK_LIMIT,
    _RL_CMD_LIMIT,
    _RL_PERIOD_BULK_S,
    _RL_PERIOD_LONG_S,
    _RL_PERIOD_S,
    _RL_QUERY_LIMIT,
    _check_callback_staff,
    _classify_and_load_role,
    _resolve_executor_target,
)
from tcbot.modules.admins.transfer import cmd_transfer
from tcbot.modules.helper import replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = "Admin"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("admins.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("admins.help.commands.body", locale),
        ),
        replies.who_section(
            t(
                "admins.help.who.body",
                locale,
                perm=Safe(replies.perm_founder_only(locale, plain=False)),
            ),
            locale,
        ),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            t("admins.help.roles.title", locale, plain=True),
            t("admins.help.roles.body", locale),
        ),
        replies.target_section(locale),
        (
            "/tcpromote",
            t("admins.help.promote.body", locale),
        ),
        (
            "/tcdemote",
            t("admins.help.demote.body", locale),
        ),
        (
            "/transferowner",
            t("admins.help.transferowner.body", locale),
        ),
        (
            replies.sec_examples(locale),
            t("admins.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]

_PMT_CMDS = build_prefixed_filters("tcpromote") | build_prefixed_filters("tcp")
_DMT_CMDS = build_prefixed_filters("tcdemote") | build_prefixed_filters("tcd")
_TF_CMDS = build_prefixed_filters("transferowner") | build_prefixed_filters("tfowner")
_PMTREQ_CMDS = build_prefixed_filters("tcpromoterequests") | build_prefixed_filters(
    "tcreqs"
)
_PMTLIST_CMDS = build_prefixed_filters("tcpromotelist") | build_prefixed_filters(
    "tcplist"
)

__handlers__ = [
    MessageHandler(_PMT_CMDS, cmd_promote),
    MessageHandler(_DMT_CMDS, cmd_demote),
    MessageHandler(_TF_CMDS, cmd_transfer),
    MessageHandler(_PMTREQ_CMDS, cmd_promote_request),
    MessageHandler(_PMTLIST_CMDS, cmd_promote_list),
    CallbackQueryHandler(on_promo_decision, pattern=r"^(promo_approve|promo_reject):"),
    CallbackQueryHandler(on_promote_role_btn, pattern=r"^promo_role:[a-z]+:\d+$"),
    CallbackQueryHandler(on_promote_role_cancel, pattern=r"^promo_role_cancel:\d+$"),
    CallbackQueryHandler(on_demote_confirm, pattern=r"^demote_confirm:\d+$"),
    CallbackQueryHandler(on_demote_cancel, pattern=r"^demote_cancel:\d+$"),
]

__all__ = [
    "_DMT_CMDS",
    "_PMTLIST_CMDS",
    "_PMTREQ_CMDS",
    "_PMT_CMDS",
    "_RL_BULK_LIMIT",
    "_RL_CMD_LIMIT",
    "_RL_PERIOD_BULK_S",
    "_RL_PERIOD_LONG_S",
    "_RL_PERIOD_S",
    "_RL_QUERY_LIMIT",
    "_TF_CMDS",
    "__handlers__",
    "__help__",
    "__help_sections__",
    "__help_text__",
    "__module_name__",
    "_check_callback_staff",
    "_classify_and_load_role",
    "_resolve_executor_target",
    "cmd_demote",
    "cmd_promote",
    "cmd_promote_list",
    "cmd_promote_request",
    "cmd_transfer",
    "get_help",
    "locale_for_update",
    "on_demote_cancel",
    "on_demote_confirm",
    "on_promo_decision",
    "on_promote_role_btn",
    "on_promote_role_cancel",
    "safe_reply",
]
