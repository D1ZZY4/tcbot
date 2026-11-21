# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Renderers for the rules editor, the public menu, and the channel."""

from __future__ import annotations

import hashlib
from typing import Any

from tcbot import database as db
from tcbot.utils.formatter import bold, esc
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

# * Telegram accepts 4096 UTF-16 units in a message; stay below it so the
# * category title, part marker, and footer always fit.
CHANNEL_LIMIT: int = 4000

log = get_logger(__name__)


def utf16_len(text: str) -> int:
    """Return the length of *text* in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def split_utf16(text: str, limit: int = CHANNEL_LIMIT) -> list[str]:
    """Split *text* into parts that fit *limit* UTF-16 units.

    Boundaries are lines first and characters last. A Python string holds
    an astral character as one code point, so a character split cannot cut
    a UTF-16 surrogate pair.
    """
    if utf16_len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if utf16_len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        if utf16_len(line) <= limit:
            current = line
            continue
        buffer = ""
        for char in line:
            if utf16_len(buffer + char) > limit:
                parts.append(buffer)
                buffer = ""
            buffer += char
        current = buffer
    if current:
        parts.append(current)
    return parts


def _category_title(item: dict[str, Any]) -> str:
    return str(item.get("category_title") or item.get("category_key") or "Rules")


def _grouped(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(_category_title(item), []).append(item)
    return groups


def render_channel(
    items: list[dict[str, Any]],
    *,
    version_number: int,
    published_at: str,
    limit: int = CHANNEL_LIMIT,
) -> list[tuple[str, int, str]]:
    """Render channel parts as ``(category, part_index, text)``.

    Content is escaped here and never by the editor, so staff cannot inject
    MarkdownV2. Each part carries the final text whose hash the publication
    slot records.
    """
    ordered = sorted(
        _grouped(items).items(),
        key=lambda group: min(
            int(item.get("category_sort_order") or 100) for item in group[1]
        ),
    )
    result: list[tuple[str, int, str]] = []
    footer = ""
    if ordered:
        footer = f"\n{esc(f'v{version_number}')} - {esc(published_at)}"
    for category, category_items in ordered:
        lines = [
            f"{esc(f'{number}.')} {bold(esc(str(item['title'])))}\n{esc(str(item['body']))}"
            + (
                f"\n{esc(str(item['reference_url']))}"
                if item.get("reference_url")
                else ""
            )
            for number, item in enumerate(
                sorted(
                    category_items,
                    key=lambda item: (
                        int(item.get("sort_order") or 100),
                        item.get("id", 0),
                    ),
                ),
                start=1,
            )
        ]
        body = "\n".join(lines)
        budget = max(1, limit - utf16_len(footer) - 40)
        chunks = split_utf16(body, budget)
        for index, chunk in enumerate(chunks):
            marker = f" ({index + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            text = f"{bold(esc(category))}{marker}\n{chunk}"
            if index == len(chunks) - 1:
                text += footer
            result.append((category, index, text))
    return result


def content_hash(text: str) -> str:
    """Return a stable hash of the final rendered text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def editor_panel(
    set_doc: dict[str, Any], version: dict[str, Any], locale: str | None
) -> str:
    """Render the editor panel text."""
    header = esc(t("button.manage_rules", locale, plain=True))
    body = t(
        "rules.editor.panel",
        locale,
        name=esc(str(set_doc.get("name", "Rules"))),
        status=esc(str(version.get("status", "draft"))),
        count=len(version.get("items", [])),
    )
    text = f"{bold(header)}\n{body}"
    try:
        counts = await db.rules_db.status_counts(int(set_doc["id"]))
        acks = 0
        if version.get("status") == "published":
            acks = await db.rules_db.acknowledgement_count(int(version["id"]))
        text += "\n" + t(
            "rules.editor.status",
            locale,
            synced=counts.get("synced", 0),
            failed=counts.get("failed", 0),
            missing=counts.get("missing", 0),
            retired=counts.get("retired", 0),
            acks=acks,
        )
    except Exception:
        log.debug("Rules channel status lookup failed")
    return text


def category_list(categories: list[dict[str, Any]], locale: str | None) -> str:
    """Render the category list body."""
    lines = [bold(esc("Categories"))]
    lines.extend(f"- {esc(str(cat['title']))}" for cat in categories)
    return "\n".join(lines)


def item_list(items: list[dict[str, Any]], locale: str | None) -> str:
    """Render the item list of one category."""
    lines = [bold(esc("Items"))]
    for number, item in enumerate(items, start=1):
        lines.append(f"{number}. {esc(str(item['title']))}")
    return "\n".join(lines)


async def preview(items: list[dict[str, Any]], locale: str | None) -> str:
    """Render the draft as it would appear on the channel, with a marker."""
    parts = render_channel(items, version_number=0, published_at="-")
    body = "\n\n".join(part[2] for part in parts)
    return f"{t('rules.menu.preview', locale)}\n\n{body}"


def rules_menu(locale: str | None, community_name: str) -> str:
    """Render the public /rules menu text."""
    return t("rules.menu.body", locale, community=community_name)


def category_view(
    category: str, items: list[dict[str, Any]], locale: str | None
) -> str:
    """Render one category of the public read-only menu."""
    header = t("rules.menu.category", locale, category=category)
    if not items:
        return f"{header}\n\n{t('rules.menu.no_rules', locale)}"
    lines = []
    for number, item in enumerate(items, start=1):
        lines.append(f"{number}. {esc(str(item['title']))}")
        lines.append(esc(str(item["body"])))
    return f"{header}\n\n" + "\n".join(lines)


def selected_summary(titles: list[str], note: str | None, locale: str | None) -> str:
    """Render the moderator's rule selection for a proof prompt or summary."""
    if note:
        return t("rules.selected.other", locale, note=note)
    if not titles:
        return t("rules.selected.none", locale)
    joined = ", ".join(titles)
    if len(titles) == 1:
        return t("rules.selected.one", locale, titles=joined)
    return t("rules.selected.many", locale, count=len(titles), titles=joined)
