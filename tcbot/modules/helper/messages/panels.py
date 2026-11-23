# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Informational panel renderers shared by the start menu and its own commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.modules.helper.messages.rich_format import footer, heading, paragraph
from tcbot.modules.helper.messages.rich_table import table
from tcbot.utils.i18n import bullet_list, code, divider, esc, t

if TYPE_CHECKING:
    from tcbot.database.documents import GroupDoc

# * Telegram caps message text at ~4096 chars; render_groups() truncates to
# * this budget so large federations get a partial list instead of an error.
_MAX_RENDER_CHARS: int = 3800

_ABOUT_SECTIONS: tuple[str, ...] = ("federasi", "keanggotaan", "klarifikasi")
_ABOUT_ITEM_COUNTS: dict[str, int] = {
    "federasi": 4,
    "keanggotaan": 4,
    "klarifikasi": 3,
}


def about_msg(locale: str | None = None) -> str:
    """Render the About section index in the given locale."""
    community = cfg.community_name
    return "\n".join(
        (
            # * heading() escapes its argument, so the community name must
            # * reach it as raw text; rich-mode t() would escape it twice.
            heading(t("about.index.title", locale, community=community, plain=True)),
            paragraph(t("about.index.lead", locale, community=community)),
            divider(),
            paragraph(t("about.index.hint", locale)),
        )
    )


def about_section_labels(locale: str | None = None) -> list[str]:
    """Localized About section labels in index order."""
    return [
        t(f"about.section.{key}.label", locale, plain=True) for key in _ABOUT_SECTIONS
    ]


def about_section_msg(idx: int, locale: str | None = None) -> str:
    """Render one About section with real rich blocks.

    Callers validate the index; an out-of-range value is a programming error.
    """
    key = _ABOUT_SECTIONS[idx]
    prefix = f"about.section.{key}"
    community = cfg.community_name
    body = "\n".join(
        (
            paragraph(t(f"{prefix}.lead", locale, community=community)),
            bullet_list(
                [
                    t(f"{prefix}.item_{n}", locale, community=community)
                    for n in range(1, _ABOUT_ITEM_COUNTS[key] + 1)
                ]
            ),
            divider(),
            footer(t(f"{prefix}.tail", locale, plain=True)),
        )
    )
    return (
        f"{heading(t(f'{prefix}.label', locale, plain=True), 3)}\n{divider()}\n{body}"
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
    rule = divider()
    headers = [esc(t("groups.list.table_group", locale, plain=True))]
    if detailed:
        headers.append(esc(t("groups.list.table_id", locale, plain=True)))
    used = len(header) + len(rule) + 2
    rows: list[list[str]] = []
    more = ""
    for i, g in enumerate(groups):
        title = g.get("title") or t("common.action.unknown_title", locale, plain=True)
        row: list[str] = [esc(title)]
        if detailed:
            row.append(code(str(g.get("chat_id", 0))))
        candidate = [*rows, row]
        rendered = table(headers, candidate, raw_cells=True, compact=True)
        if used + len(rendered) > _MAX_RENDER_CHARS:
            more = t("groups.list.more", locale, n=len(groups) - i)
            break
        rows = candidate
    body = table(headers, rows, raw_cells=True, compact=True)
    text = f"{header}\n{rule}\n{body}"
    if more:
        text += f"\n{more}"
    return text
