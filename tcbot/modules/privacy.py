# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Privacy summary and full privacy-policy menu callbacks."""

from __future__ import annotations

from tcbot import cfg
from tcbot.modules.helper import buttons, decorators
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.handlers import CallbackQueryHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import answer_and_edit
from tcbot.modules.helper.rich.edit import callback_text_of
from tcbot.modules.helper.rich.formats import (
    divider,
    footer,
    heading,
    paragraph,
)
from tcbot.modules.helper.rich.list import bullet_list
from tcbot.utils.i18n import t

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

# * The catalog owns wording; this table owns how many items each page has.
_SECTION_ITEM_COUNTS: dict[str, int] = {
    "collect": 7,
    "why": 3,
    "access": 3,
    "retention": 4,
    "rights": 2,
    "contact": 2,
}


def _items(
    prefix: str, count: int, locale: str | None, *, community: str | None = None
) -> list[str]:
    """Read a numbered item group as rich HTML, in catalog order.

    ``None`` is never passed as a placeholder value: the renderer rejects it
    so a missing value fails loudly instead of rendering an empty word.
    """
    if community is None:
        return [t(f"{prefix}_{n}", locale) for n in range(1, count + 1)]
    return [
        t(f"{prefix}_{n}", locale, community=community) for n in range(1, count + 1)
    ]


def _privacy_msg(botname: str, locale: str | None = None) -> str:
    """Build the data-collection notice from real rich blocks.

    The record list ends with a paragraph about who may read enforcement
    history. A divider separates that paragraph from the policy hint so the
    two messages never fold together on Telegram.
    """
    return "\n".join(
        (
            heading(t("privacy.msg.title", locale)),
            divider(),
            paragraph(t("privacy.msg.lead", locale, bot=botname)),
            paragraph(t("privacy.msg.list_title", locale)),
            bullet_list(_items("privacy.msg.item", 6, locale)),
            paragraph(t("privacy.msg.visibility", locale)),
            divider(),
            paragraph(t("privacy.msg.policy_hint", locale)),
        )
    )


def _privacy_policy_index_msg(botname: str, locale: str | None = None) -> str:
    """Build the privacy policy section index page."""
    return "\n".join(
        (
            heading(t("privacy.index.title", locale)),
            paragraph(t("privacy.index.lead", locale, bot=botname)),
            divider(),
            paragraph(t("privacy.index.hint", locale)),
        )
    )


def _section_labels(locale: str | None = None) -> list[str]:
    """Localized section labels in keyboard order."""
    return [
        t(f"privacy.section.{key}.label", locale, plain=True) for key in _SECTION_KEYS
    ]


def _section_body(idx: int, botname: str, locale: str | None = None) -> tuple[str, str]:
    """Return (label, body) for one policy section, laid out in rich blocks."""
    key = _SECTION_KEYS[idx]
    prefix = f"privacy.section.{key}"
    label = t(f"{prefix}.label", locale, plain=True)
    community = cfg.community_name
    body = "\n".join(
        (
            paragraph(t(f"{prefix}.lead", locale, bot=botname, community=community)),
            bullet_list(
                _items(
                    f"{prefix}.item",
                    _SECTION_ITEM_COUNTS[key],
                    locale,
                    community=community,
                )
            ),
            divider(),
            footer(t(f"{prefix}.tail", locale, plain=True)),
        )
    )
    return label, body


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_privacy_menu(ctx: Ctx) -> None:
    """Render the data-collection privacy notice when the Privacy button is tapped."""
    q = ctx.callback_query
    if q is None:
        return

    locale = await locale_for_update(ctx)
    botname = (await ctx.bot_identity()).first_name or t(
        "privacy.msg.bot_fallback", locale, plain=True
    )
    await answer_and_edit(
        q,
        _privacy_msg(botname, locale),
        reply_markup=buttons.privacy_btn(locale),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_privacy_policy_menu(ctx: Ctx) -> None:
    """Render the privacy policy section index when Privacy Policy is tapped."""
    q = ctx.callback_query
    if q is None:
        return

    locale = await locale_for_update(ctx)
    botname = (await ctx.bot_identity()).first_name or t(
        "privacy.msg.bot_fallback", locale, plain=True
    )
    await answer_and_edit(
        q,
        _privacy_policy_index_msg(botname, locale),
        reply_markup=buttons.privacy_policy_sections_btn(
            _section_labels(locale), locale
        ),
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_privacy_section(ctx: Ctx) -> None:
    """Render a single privacy policy section."""
    q = ctx.callback_query
    if q is None:
        return
    data = callback_text_of(q)
    if not data:
        await q.answer()
        return

    locale = await locale_for_update(ctx)

    try:
        idx = int(data[len("privacy_section_") :])
    except ValueError:
        # * Slicing never raises IndexError; only non-numeric tails land here.
        await q.answer(
            t("privacy.error.invalid_section", locale, plain=True),
            show_alert=True,
        )
        return
    if idx < 0 or idx >= len(_SECTION_KEYS):
        await q.answer(
            t("privacy.error.not_found", locale, plain=True),
            show_alert=True,
        )
        return

    botname = (await ctx.bot_identity()).first_name or t(
        "privacy.msg.bot_fallback", locale, plain=True
    )
    label, content = _section_body(idx, botname, locale)
    body = f"{heading(label, 3)}\n{divider()}\n{content}"
    await answer_and_edit(
        q,
        body,
        reply_markup=buttons.back_to_privacy_policy_btn(locale),
    )


# ──────────────────────────── Handlers ──────────────────────────── #

__handlers__ = [
    CallbackQueryHandler(on_privacy_menu, pattern=r"^privacy_menu$"),
    CallbackQueryHandler(on_privacy_policy_menu, pattern=r"^privacy_policy_menu$"),
    CallbackQueryHandler(on_privacy_section, pattern=r"^privacy_section_\d+$"),
]
