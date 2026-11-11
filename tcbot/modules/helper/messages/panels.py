# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Informational panel renderers shared by the start menu and its own commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import Safe, t

if TYPE_CHECKING:
    from tcbot.database.documents import GroupDoc

# * Telegram caps message text at ~4096 chars; render_groups() truncates to
# * this budget so large federations get a partial list instead of an error.
_MAX_RENDER_CHARS: int = 3800


def about_msg(locale: str | None = None) -> str:
    """Render the About page in the given locale."""
    cname = cfg.community_name
    disc = Safe(t("about.page.disclaimer_text", locale, community=cname))
    return (
        f"{t('about.page.title', locale, title=Safe(bold(cname)))}\n\n"
        f"{t('about.page.intro', locale)}\n\n"
        f"{t('about.page.how_title', locale)}\n"
        f"{t('about.page.how_body', locale)}\n\n"
        f"{t('about.page.history_title', locale)}\n"
        f"{t('about.page.history_body', locale, community=cname)}\n\n"
        f"{t('about.page.disclaimer', locale, disc=disc)}"
    )


def render_groups(
    groups: list[GroupDoc], *, detailed: bool, locale: str | None = None
) -> str:
    """Render the group list, truncating to fit Telegram's message limit.

    Shared with the start-menu groups view: one renderer so truncation
    and item shapes cannot drift between the command and the menu.

    Telegram rejects messages over ~4096 chars; an unbounded render raises
    BadRequest (swallowed by callers, leaving the user with nothing) on
    large federations. Cap the body and name the remainder instead.
    """
    header = t("groups.list.header", locale, n=len(groups))
    lines = [header]
    used = len(header) + 1
    for i, g in enumerate(groups):
        title = g.get("title", "Unknown")
        if detailed:
            line = t(
                "groups.list.item_detailed",
                locale,
                title=title,
                id=Safe(code(str(g.get("chat_id", 0)))),
            )
        else:
            line = t("groups.list.item", locale, title=title)
        if used + len(line) + 1 > _MAX_RENDER_CHARS:
            lines.append(
                t("groups.list.more", locale, n=len(groups) - i),
            )
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
