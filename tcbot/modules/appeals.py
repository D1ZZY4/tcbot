# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal handlers: routes incoming appeals and admin review decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot.modules.helper import decorators
from tcbot.modules.helper.messages import replies
from tcbot.modules.helper.pipelines.appeal_review import LOCK_HOURS
from tcbot.modules.helper.pipelines.appeal_submit import REF_PATTERN, appeal
from tcbot.utils.i18n import Safe, bold, pre, t
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from telegram import Update

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Appeal"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    window = Safe(bold(t("appeals.help.window", locale, hours=LOCK_HOURS, plain=True)))
    overview = t("appeals.help.overview", locale, window=window)
    sections: list[tuple[str, str]] = [
        (
            t("appeals.help.start.title", locale, plain=True),
            t("appeals.help.start.body", locale),
        ),
        replies.who_section(t("appeals.help.who.body", locale), locale),
        (
            t("appeals.help.where.title", locale, plain=True),
            t("appeals.help.where.body", locale),
        ),
        (
            t("appeals.help.how.title", locale, plain=True),
            t("appeals.help.how.body", locale),
        ),
        (
            t("appeals.help.format.title", locale, plain=True),
            pre(t("appeals.help.format.body", locale, plain=True)),
        ),
        (
            t("appeals.help.next.title", locale, plain=True),
            t("appeals.help.next.body", locale, window=window),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()


# ──────────────────────────── Handlers ──────────────────────────── #

_APPEAL_START_CMDS = filters.ChatType.PRIVATE & filters.Regex(
    rf"^/start\s+appeal_{REF_PATTERN}$"
)


# * The review decision is an irreversible federation unban plus a possible
# * demote, and the #appeal message path is reachable by any group member.
# * Neither entry is covered by the prefixed-command flood ceiling, so each
# * gets its own per-user budget before the shared flow runs.
@decorators.ratelimiter(decorators.THROTTLE_STAFF)
async def on_appeal_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Rate-limit an appeal review decision before delegating to the flow."""
    await appeal.on_decision(update, ctx)


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
async def on_group_appeal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Rate-limit a member's #appeal entry before the submission gate runs."""
    await appeal.on_group_appeal(update, ctx)


__handlers__ = [
    appeal.build_handler(_APPEAL_START_CMDS),
    # * Legacy cards carry no review id; the handler accepts them only when
    # * the tapped message is the live review card.
    CallbackQueryHandler(on_appeal_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
    # * #appeal in the main group is a valid submission path alongside the
    # * DM deep link; the handler itself gates the chat. The filter keeps
    # * ordinary chat messages out of the per-user throttle and the flow.
    MessageHandler(
        filters.TEXT & ~ALL_PREFIXES_CMD_FILTER & filters.Regex(r"(?i)^\s*#appeal"),
        on_group_appeal,
    ),
]
