# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Privacy summary and full privacy-policy menu callbacks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes

from tcbot import cfg
from tcbot.modules.helper import decorators, keyboards
from tcbot.modules.helper.locale import locale_for_update
from tcbot.utils.formatter import bold
from tcbot.utils.i18n import t

if TYPE_CHECKING:
    from telegram import Update

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CB_LIMIT: int = 15

__module_name__ = None


# ──────────────────────── Privacy Messages ──────────────────────── #

_SECTION_KEYS: tuple[str, ...] = (
    "collect",
    "why",
    "access",
    "retention",
    "rights",
    "contact",
)


def _privacy_msg(botname: str, locale: str | None = None) -> str:
    """Build the data-collection notice for the given plain-text bot display name."""
    return t("privacy.msg.body", locale, bot=botname)


def _privacy_policy_index_msg(botname: str, locale: str | None = None) -> str:
    """Build the privacy policy section index page for the plain-text bot name."""
    return t("privacy.index.body", locale, bot=botname)


def _section_labels(locale: str | None = None) -> list[str]:
    """Localized section labels in keyboard order."""
    return [
        t(f"privacy.section.{key}.label", locale, plain=True) for key in _SECTION_KEYS
    ]


def _section_body(idx: int, locale: str | None = None) -> tuple[str, str]:
    """Return (label, body) for a section index."""
    key = _SECTION_KEYS[idx]
    return (
        t(f"privacy.section.{key}.label", locale, plain=True),
        t(f"privacy.section.{key}.body", locale, community=cfg.community_name),
    )


_POLICY_SECTION_LABELS: list[str] = _section_labels()


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_privacy_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the data-collection privacy notice when the Privacy button is tapped."""
    q = update.callback_query
    if q is None:
        return

    botname = ctx.bot.first_name or "This bot"
    locale = await locale_for_update(update)
    # * q.answer() and edit are independent; run in parallel.
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _privacy_msg(botname, locale),
            parse_mode="MarkdownV2",
            reply_markup=keyboards.privacy_kb(locale),
        ),
        return_exceptions=True,
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_privacy_policy_menu(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Render the privacy policy section index when Privacy Policy is tapped."""
    q = update.callback_query
    if q is None:
        return

    botname = ctx.bot.first_name or "This bot"
    locale = await locale_for_update(update)
    # * q.answer() and edit are independent; run in parallel.
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            _privacy_policy_index_msg(botname, locale),
            parse_mode="MarkdownV2",
            reply_markup=keyboards.privacy_policy_sections_kb(
                _section_labels(locale), locale
            ),
        ),
        return_exceptions=True,
    )


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_privacy_section(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a single privacy policy section."""
    q = update.callback_query
    if q is None or not q.data:
        return

    try:
        idx = int(q.data[len("privacy_section_") :])
    except ValueError:
        # * Slicing never raises IndexError; only non-numeric tails land here.
        await q.answer(
            t(
                "privacy.error.invalid_section",
                await locale_for_update(update),
                plain=True,
            ),
            show_alert=True,
        )
        return
    if idx < 0 or idx >= len(_SECTION_KEYS):
        await q.answer(
            t("privacy.error.not_found", await locale_for_update(update), plain=True),
            show_alert=True,
        )
        return

    locale = await locale_for_update(update)
    label, content = _section_body(idx, locale)
    body = f"{bold(label)}\n\n{content}"
    # * q.answer() and edit are independent; run in parallel.
    await asyncio.gather(
        q.answer(),
        q.edit_message_text(
            body,
            parse_mode="MarkdownV2",
            reply_markup=keyboards.back_to_privacy_policy_kb(locale),
        ),
        return_exceptions=True,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_privacy_menu, pattern=r"^privacy_menu$"),
    CallbackQueryHandler(on_privacy_policy_menu, pattern=r"^privacy_policy_menu$"),
    CallbackQueryHandler(on_privacy_section, pattern=r"^privacy_section_\d+$"),
]
