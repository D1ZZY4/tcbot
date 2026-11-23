# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Renderers for the rules editor, the public menu, and the channel."""

from __future__ import annotations

import hashlib
from typing import Any

from tcbot import database as db
from tcbot.modules.helper.messages import rich_msg
from tcbot.modules.helper.messages.rich_format import footer, heading, paragraph
from tcbot.modules.helper.messages.rich_style import bold as rich_bold
from tcbot.modules.helper.messages.rich_style import esc as rich_esc
from tcbot.modules.helper.messages.rich_text import blocks
from tcbot.utils.i18n import (
    Safe,
    bold,
    bullet_list,
    code,
    divider,
    esc,
    section,
    t,
)
from tcbot.utils.logger import get_logger

# * Telegram accepts 4096 UTF-16 units in a message; stay below it so the
# * category title, part marker, and footer always fit.
CHANNEL_LIMIT: int = 4000

# * Category keys come from the operator-local document stems. The catalog owns
# * the wording; these keys only gate the lookup so a staff-created category
# * falls back to its stored title instead of logging a missing key.
_CATEGORY_KEYS: frozenset[str] = frozenset(
    {
        "cheat",
        "doxing-dan-privasi",
        "identitas",
        "karya-dan-atribusi",
        "konten-pornografi-nsfw",
        "materi-pengujian",
        "mod-apk-dan-bajakan",
        "module-root",
        "out-off-topic",
        "pengelola",
        "penipuan",
        "perundungan-dan-kebencian",
        "politik",
        "promosi",
        "sanksi",
        "spam",
        "transaksi",
        "federasi",
        "keanggotaan",
        "klarifikasi",
        "persetujuan-pendiri",
    }
)

log = get_logger(__name__)


def category_label(key: str, locale: str | None, fallback: str = "") -> str:
    """Return the localized label of a published rule category."""
    if key not in _CATEGORY_KEYS:
        return fallback or key
    return t(f"rules.category.{key}.label", locale, plain=True)


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

    Every value is escaped here and never by the editor, so staff cannot
    inject markup. ``published_at`` is a raw timestamp; ``fmt_dt_raw``
    produces it and this renderer owns the escaping. Each part carries the
    final text whose hash the publication slot records.
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
        footer = esc(f"\nv{version_number} - {published_at}")
    for category, category_items in ordered:
        lines = [
            f"{esc(f'{number}.')} {bold(str(item['title']))}\n{esc(str(item['body']))}"
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
            text = f"{bold(category)}{esc(marker)}\n{chunk}"
            if index == len(chunks) - 1:
                text += footer
            result.append((category, index, text))
    return result


def content_hash(text: str) -> str:
    """Return a stable hash of the final rendered text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def editor_panel(
    set_doc: dict[str, Any],
    version: dict[str, Any],
    locale: str | None,
    *,
    has_content: bool = False,
    item_count: int = 0,
) -> str:
    """Render the editor panel with a clear next step for the reader."""
    header = t("button.manage_rules", locale, plain=True)
    body = t(
        "rules.editor.panel",
        locale,
        name=Safe(code(str(set_doc.get("name", "Rules")))),
        status=Safe(code(str(version.get("status", "draft")))),
        count=Safe(code(str(item_count))),
    )
    text = section(header, bullet_list(body.splitlines()))
    hint = "rules.editor.ready_hint" if has_content else "rules.editor.empty_hint"
    text += f"\n{divider()}\n" + t(hint, locale)
    try:
        counts = await db.rules_db.status_counts(int(set_doc["id"]))
        published = await db.rules_db.published_version(int(set_doc["id"]))
        # * An empty, never-published set has no meaningful channel status;
        # * showing four zeroes there only obscures the next step.
        if published is None and not any(
            counts.get(key, 0) for key in ("synced", "failed", "missing", "retired")
        ):
            return text
        acks = (
            await db.rules_db.acknowledgement_count(int(published["id"]))
            if published
            else 0
        )
        text += f"\n{divider()}\n" + t(
            "rules.editor.status",
            locale,
            synced=Safe(code(str(counts.get("synced", 0)))),
            failed=Safe(code(str(counts.get("failed", 0)))),
            missing=Safe(code(str(counts.get("missing", 0)))),
            retired=Safe(code(str(counts.get("retired", 0)))),
            acks=Safe(code(str(acks))),
        )
    except Exception:
        log.debug("Rules channel status lookup failed")
    return text


def category_list(categories: list[dict[str, Any]], locale: str | None) -> str:
    """Render the category list body."""
    lines = [esc(str(cat["title"])) for cat in categories]
    return section(t("rules.editor.categories", locale, plain=True), bullet_list(lines))


def item_list(items: list[dict[str, Any]], locale: str | None) -> str:
    """Render the item list of one category."""
    lines = [
        f"{number}. {esc(str(item['title']))}"
        for number, item in enumerate(items, start=1)
    ]
    return section(
        t("rules.editor.items", locale, plain=True), blocks("\n".join(lines))
    )


async def preview(items: list[dict[str, Any]], locale: str | None) -> str:
    """Render the draft as it would appear on the channel, with a marker."""
    if not items:
        return t("rules.menu.preview_empty", locale)
    parts = render_channel(items, version_number=0, published_at="-")
    body = "\n\n".join(part[2] for part in parts)
    return f"{t('rules.menu.preview', locale)}\n\n{body}"


def rules_menu(locale: str | None, community_name: str) -> str:
    """Render the public /rules topic index text."""
    return t("rules.menu.body", locale, community=community_name)


def rich_index_page(intro: str, locale: str | None = None) -> dict[str, Any]:
    """Render the topic index heading and intro; categories live in the keyboard.

    The category names must not be repeated as text above the buttons. A long
    list pushes the keyboard down and duplicates what the buttons already say.
    """
    return rich_msg.html_message(
        heading(t("rules.menu.index_title", locale, plain=True)),
        paragraph(intro),
        divider(),
    )


def rich_section_page(
    category: str, section: str, items: list[dict[str, Any]], locale: str | None
) -> dict[str, Any]:
    """Render one section of a category as a rich block with a footer."""
    label = category_label(str(category), locale, str(category))
    title = t("rules.menu.section", locale, category=label, section=section, plain=True)
    lines = [
        f"{rich_bold(str(item['title']))}\n{rich_esc(str(item['body']))}"
        for item in items
    ]
    return rich_msg.html_message(
        heading(title),
        divider(),
        bullet_list(lines),
        divider(),
        footer(t("rules.menu.category_footer", locale, plain=True)),
    )


def rich_category_index(
    key: str, title: str, description: str, locale: str | None
) -> dict[str, Any]:
    """Render a category heading with its one-line description."""
    label = category_label(key, locale, title)
    return rich_msg.html_message(
        heading(t("rules.menu.category", locale, category=label, plain=True)),
        divider(),
        paragraph(description),
        divider(),
        footer(t("rules.menu.category_footer", locale, plain=True)),
    )


def rich_category_view(
    category: str,
    items: list[dict[str, Any]],
    locale: str | None,
    *,
    page: int | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    """Build one rich rules page holding a single topic and its rules.

    The public menu is paginated one topic per page. The optional page numbers
    render a position marker so a reader knows where they are in the set; the
    Prev and Next buttons live in the keyboard, not in this renderer.
    """
    label = category_label(str(category), locale, str(category))
    heading_text = t("rules.menu.category", locale, category=label, plain=True)
    blocks = [heading(heading_text)]
    if page is not None and total is not None:
        blocks.append(
            paragraph(t("rules.menu.page", locale, page=page + 1, total=total))
        )
    if not items:
        blocks.append(paragraph(t("rules.menu.no_rules", locale)))
        return rich_msg.html_message(*blocks)
    lines = [
        f"{rich_bold(str(item['title']))}\n{rich_esc(str(item['body']))}"
        for item in items
    ]
    blocks.extend(
        (
            divider(),
            bullet_list(lines),
            divider(),
            footer(t("rules.menu.category_footer", locale, plain=True)),
        )
    )
    return rich_msg.html_message(*blocks)


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
