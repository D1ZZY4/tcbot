# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Draft menu of the rules editor: categories, items, typers, and preview."""

from __future__ import annotations

from io import BytesIO

from tcbot import database as db
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.handlers import ConversationHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import reply_rich
from tcbot.modules.helper.messages import rules as rules_msg
from tcbot.modules.helper.pipelines.rules_editor_steps import (
    _BODY_MAX,
    _TITLE_MAX,
    _URL_MAX,
    _URL_SKIP,
    WAITING_EDITOR_MENU,
    WAITING_MARKDOWN,
    clear_item_step,
    edit_or_reply,
    editor_allowed,
    refuse_editor,
    set_and_draft,
    slug,
)
from tcbot.modules.helper.pipelines.rules_markdown import (
    parse_description,
    parse_document,
    render_body,
)
from tcbot.modules.helper.rich.edit import callback_text_of
from tcbot.modules.helper.rich.style import esc
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.pagination import clamp_page

log = get_logger(__name__)


def _cb_text(ctx: Ctx) -> str:
    """Return the callback payload of this context as text."""
    q = ctx.callback_query
    return callback_text_of(q) if q is not None else ""


class RulesDraftEditor:
    """Owns the draft-facing screens of one staff member's rules editor."""

    async def categories(self, ctx: Ctx) -> int:
        """List the categories of the open draft, creating the draft if needed."""
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, _version = opened
        categories = await db.rules_db.list_categories(int(set_doc["id"]))
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            rules_msg.category_list(categories, locale),
            rules_btn.categories_btn(categories, locale),
        )
        return WAITING_EDITOR_MENU

    async def cat_action(self, ctx: Ctx) -> int:
        """Handle rename, reorder, and delete actions on a category."""
        q = ctx.callback_query
        if q is None or not _cb_text(ctx):
            return WAITING_EDITOR_MENU
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return WAITING_EDITOR_MENU
        await q.answer()
        action, key = _cb_text(ctx).split(":", 1)
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        if action == "rules_cat_rename":
            scope = flow_scope(ctx)
            scope["rules_category_key"] = key
            scope["rules_step"] = "rename_category"
            locale = await self._locale(ctx)
            await edit_or_reply(
                ctx,
                t("rules.editor.ask_rename", locale, plain=True),
                rules_btn.prompt_btn("rules_categories", locale),
            )
            return WAITING_EDITOR_MENU
        set_id = int(opened[0]["id"])
        if action == "rules_cat_up":
            await db.rules_db.move_category(set_id, key, -1)
        elif action == "rules_cat_down":
            await db.rules_db.move_category(set_id, key, 1)
        elif action == "rules_cat_del":
            await db.rules_db.delete_category(set_id, key)
        return await self.categories(ctx)

    async def category_items(self, ctx: Ctx) -> int:
        """Select a category and list the items of the open draft in it."""
        q = ctx.callback_query
        if q is None or not _cb_text(ctx):
            return WAITING_EDITOR_MENU
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return WAITING_EDITOR_MENU
        await q.answer()
        key = _cb_text(ctx).split(":", 1)[1]
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        categories = await db.rules_db.list_categories(int(opened[0]["id"]))
        match = next(
            (cat for cat in categories if str(cat["category_key"]) == key), None
        )
        if match is None:
            return await self.categories(ctx)
        return await self._render_category(ctx, key)

    async def _render_category(self, ctx: Ctx, key: str) -> int:
        """Render a category page: H1, divider, description, divider, sections."""
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        categories = await db.rules_db.list_categories(int(opened[0]["id"]))
        match = next(
            (cat for cat in categories if str(cat["category_key"]) == key), None
        )
        if match is None:
            return await self.categories(ctx)
        flow_scope(ctx)["rules_category"] = match
        rows = await db.rules_db.list_items(int(opened[1]["id"]), key)
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            rules_msg.category_editor_panel(match, locale),
            rules_btn.editor_sections_btn(rows, locale),
        )
        return WAITING_EDITOR_MENU

    async def items(self, ctx: Ctx, page: int = 0) -> int:
        """List at most five items of the selected draft category."""
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx)
        version_id = int(scope["rules_version"]["id"])
        category = scope.get("rules_category")
        category_key = str(category["category_key"]) if category else None
        rows = await db.rules_db.list_items(version_id, category_key)
        total_pages, page = clamp_page(len(rows), page, 5)
        chunk = rows[page * 5 : (page + 1) * 5]
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            rules_msg.item_list(chunk, locale),
            rules_btn.editor_items_page_btn(page, total_pages, locale),
        )
        return WAITING_EDITOR_MENU

    async def items_page(self, ctx: Ctx) -> int:
        """Show another page of the editor item list."""
        query = ctx.callback_query
        page = 0
        if query is not None and _cb_text(ctx):
            try:
                page = int(_cb_text(ctx).split(":", 1)[1])
            except ValueError, IndexError:
                page = 0
        return await self.items(ctx, page)

    async def sections(self, ctx: Ctx) -> int:
        """Show the draft sections directly, one editable button each."""
        query = ctx.callback_query
        if query is not None:
            await query.answer()
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        rows = await db.rules_db.list_items(int(opened[1]["id"]))
        flow_scope(ctx).pop("rules_step", None)
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            t("rules.editor.sections", locale, count=len(rows)),
            rules_btn.editor_sections_btn(rows, locale),
        )
        return WAITING_EDITOR_MENU

    async def _render_section(self, ctx: Ctx) -> int:
        """Render the open section and its formatting toolbar."""
        scope = flow_scope(ctx)
        item_id = scope.get("rules_section_id")
        opened = await set_and_draft(ctx)
        if opened is None or item_id is None:
            return ConversationHandler.END
        rows = await db.rules_db.list_items(int(opened[1]["id"]))
        item = next((row for row in rows if int(row["id"]) == int(item_id)), None)
        if item is None:
            return await self.sections(ctx)
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            f"<b>{esc(str(item['title']))}</b>\n{render_body(str(item['body']))}",
            rules_btn.section_editor_btn(locale),
        )
        return WAITING_EDITOR_MENU

    async def edit_section(self, ctx: Ctx) -> int:
        """Open one section for editing."""
        query = ctx.callback_query
        if query is None or not _cb_text(ctx):
            return WAITING_EDITOR_MENU
        await query.answer()
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        scope = flow_scope(ctx)
        scope["rules_section_id"] = int(_cb_text(ctx).split(":", 1)[-1] or 0)
        scope.pop("rules_format", None)
        return await self._render_section(ctx)

    async def _append_body(self, ctx: Ctx, addition: str) -> None:
        scope = flow_scope(ctx)
        item_id = scope.get("rules_section_id")
        opened = await set_and_draft(ctx)
        if opened is None or item_id is None:
            return
        rows = await db.rules_db.list_items(int(opened[1]["id"]))
        item = next((row for row in rows if int(row["id"]) == int(item_id)), None)
        if item is None:
            return
        body = str(item["body"] or "")
        await db.rules_db.update_item_body(
            int(opened[1]["id"]), int(item_id), (body + addition).strip()
        )

    async def apply_format(self, ctx: Ctx) -> int:
        """Choose a rich style, then type the text to append to this section."""
        query = ctx.callback_query
        if query is None or not _cb_text(ctx):
            return WAITING_EDITOR_MENU
        await query.answer()
        style = _cb_text(ctx).split(":", 1)[-1]
        scope = flow_scope(ctx)
        if style == "divider":
            await self._append_body(ctx, "\n---\n")
            return await self._render_section(ctx)
        scope["rules_format"] = style
        scope["rules_step"] = "section_format_text"
        msg = ctx.effective_message
        if msg is not None:
            await reply_rich(
                msg,
                t(
                    "rules.editor.ask_format_text",
                    await self._locale(ctx),
                    plain=True,
                ),
                parse_mode=None,
            )
        return WAITING_EDITOR_MENU

    async def on_section_text(self, ctx: Ctx) -> int:
        """Append formatted text to the open section body."""
        msg = ctx.effective_message
        if msg is None or not msg.text:
            return WAITING_EDITOR_MENU
        scope = flow_scope(ctx)
        style = str(scope.get("rules_format") or "plain")
        text = msg.text.strip()
        wrapped = {
            "bold": f"**{text}**",
            "italic": f"*{text}*",
            "code": f"`{text}`",
            "list": "\n".join(f"- {line}" for line in text.splitlines()),
        }.get(style, text)
        await self._append_body(ctx, f"\n{wrapped}")
        scope.pop("rules_step", None)
        scope.pop("rules_format", None)
        return await self._render_section(ctx)

    async def ask_section_title(self, ctx: Ctx) -> int:
        """Ask for a new section title."""
        query = ctx.callback_query
        if query is not None:
            await query.answer()
        flow_scope(ctx)["rules_step"] = "section_title_text"
        msg = ctx.effective_message
        if msg is not None:
            await reply_rich(
                msg,
                t("rules.editor.ask_title", await self._locale(ctx), plain=True),
                parse_mode=None,
            )
        return WAITING_EDITOR_MENU

    async def on_section_title_text(self, ctx: Ctx) -> int:
        """Store a new title for the section being edited."""
        msg = ctx.effective_message
        if msg is None or not msg.text:
            return WAITING_EDITOR_MENU
        scope = flow_scope(ctx)
        item_id = scope.get("rules_section_id")
        opened = await set_and_draft(ctx)
        if opened is None or item_id is None:
            return ConversationHandler.END
        await db.rules_db.update_item_title(
            int(opened[1]["id"]), int(item_id), msg.text.strip()
        )
        scope.pop("rules_step", None)
        return await self._render_section(ctx)

    async def ask_markdown(self, ctx: Ctx) -> int:
        """Ask for a Markdown document to import into the open draft."""
        query = ctx.callback_query
        if query is not None:
            await query.answer()
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return WAITING_EDITOR_MENU
        flow_scope(ctx)["rules_step"] = "markdown_upload"
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            t("rules.editor.ask_markdown", locale, plain=True),
            rules_btn.prompt_btn("rules_panel", locale),
        )
        return WAITING_MARKDOWN

    async def on_markdown(self, ctx: Ctx) -> int:
        """Parse an uploaded .md document and store each heading as an item."""
        msg = ctx.effective_message
        document = msg.document if msg is not None else None
        if document is None or msg is None:
            return WAITING_MARKDOWN
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        locale = await self._locale(ctx)
        name = document.file_name or "rules.md"
        if not name.lower().endswith(".md"):
            await reply_rich(
                msg, t("rules.editor.markdown_bad", locale, plain=True), parse_mode=None
            )
            return WAITING_MARKDOWN
        try:
            payload = await ctx.bot.download_media(document, in_memory=True)
            if isinstance(payload, list):
                payload = payload[0] if len(payload) == 1 else None
            if isinstance(payload, BytesIO):
                data = payload.getvalue()
            elif isinstance(payload, bytes | bytearray):
                data = bytes(payload)
            else:
                data = None
            if data is None:
                raise ValueError("unexpected download payload")
            text = data.decode("utf-8")
            items = parse_document(text, name)
            description = parse_description(text)
        except Exception as exc:
            log.warning("Rules markdown upload failed: %s", exc)
            await reply_rich(
                msg, t("rules.editor.markdown_bad", locale, plain=True), parse_mode=None
            )
            return WAITING_MARKDOWN
        if not items:
            await reply_rich(
                msg, t("rules.editor.markdown_bad", locale, plain=True), parse_mode=None
            )
            return WAITING_MARKDOWN
        version_id = int(opened[1]["id"])
        set_id = int(opened[0]["id"])
        category_key = str(items[0]["category_key"])
        existing = await db.rules_db.list_categories(set_id)
        if not any(str(row["category_key"]) == category_key for row in existing):
            await db.rules_db.add_category(
                set_id, category_key, str(items[0]["category_title"])
            )
        await db.rules_db.set_category_description(set_id, category_key, description)
        # * Re-uploading a document replaces that category's items instead of
        # * appending duplicates to the draft.
        await db.rules_db.delete_draft_category_items(version_id, category_key)
        for item in items:
            await db.rules_db.add_item(
                version_id,
                str(item["category_key"]),
                str(item["title"]),
                str(item["body"]),
                None,
            )
        flow_scope(ctx).pop("rules_step", None)
        await reply_rich(
            msg,
            # * Rich mode: this travels through rich HTML, so the uploaded
            # * filename must be escaped rather than passed through verbatim.
            t(
                "rules.editor.markdown_ok",
                locale,
                count=len(items),
                name=name,
            ),
            parse_mode=None,
        )
        return await self._render_category(ctx, category_key)

    async def ask_category_title(self, ctx: Ctx) -> int:
        """Ask for a new category title."""
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        flow_scope(ctx)["rules_step"] = "category_title"
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            t("rules.editor.ask_category", locale, plain=True),
            rules_btn.prompt_btn("rules_panel", locale),
        )
        return WAITING_EDITOR_MENU

    async def ask_item_title(self, ctx: Ctx) -> int:
        """Ask for a new item title in the selected category."""
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx)
        if not isinstance(scope.get("rules_category"), dict):
            # * Add Item is also on the root menu, where no category has been
            # * selected. Pick the first stored category deterministically so
            # * the typed title and body are not discarded at the URL step.
            opened = await set_and_draft(ctx)
            if opened is None:
                return ConversationHandler.END
            categories = await db.rules_db.list_categories(int(opened[0]["id"]))
            if not categories:
                return await self.categories(ctx)
            scope["rules_category"] = categories[0]
        scope["rules_step"] = "item_title"
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            t("rules.editor.ask_title", locale, plain=True),
            rules_btn.prompt_btn("rules_categories", locale),
        )
        return WAITING_EDITOR_MENU

    async def on_text(self, ctx: Ctx) -> int:
        """Route a typed answer to the pending editor step."""
        msg = ctx.effective_message
        user = ctx.effective_user
        if msg is None or user is None or not msg.text:
            return ConversationHandler.END
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, version = opened
        scope = flow_scope(ctx)
        step = scope.get("rules_step")
        text = msg.text.strip()
        locale = await self._locale(ctx)

        if step == "section_format_text":
            return await self.on_section_text(ctx)
        if step == "section_title_text":
            return await self.on_section_title_text(ctx)

        if step == "category_title":
            if not text or len(text) > _TITLE_MAX:
                await reply_rich(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            category = await db.rules_db.add_category(
                int(set_doc["id"]), slug(text), text
            )
            scope["rules_category"] = category
            clear_item_step(scope)
            return await self.categories(ctx)

        if step == "rename_category":
            if not text or len(text) > _TITLE_MAX:
                await reply_rich(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            await db.rules_db.rename_category(
                int(set_doc["id"]),
                str(scope.get("rules_category_key") or ""),
                text,
            )
            scope.pop("rules_step", None)
            return await self.categories(ctx)

        if step == "item_title":
            if not text or len(text) > _TITLE_MAX:
                await reply_rich(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            scope["rules_item_title"] = text
            scope["rules_step"] = "item_body"
            await reply_rich(
                msg, t("rules.editor.ask_body", locale, plain=True), parse_mode=None
            )
            return WAITING_EDITOR_MENU

        if step == "item_body":
            if not text or len(text) > _BODY_MAX:
                await reply_rich(
                    msg,
                    t("rules.editor.bad_body", locale, limit=_BODY_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            scope["rules_item_body"] = text
            scope["rules_step"] = "item_url"
            await reply_rich(
                msg, t("rules.editor.ask_url", locale, plain=True), parse_mode=None
            )
            return WAITING_EDITOR_MENU

        if step == "item_url":
            skip_url = text == _URL_SKIP
            if (
                text
                and not skip_url
                and (
                    len(text) > _URL_MAX or not text.startswith(("https://", "http://"))
                )
            ):
                await reply_rich(
                    msg, t("rules.editor.bad_url", locale, plain=True), parse_mode=None
                )
                return WAITING_EDITOR_MENU
            category = scope.get("rules_category")
            title = scope.get("rules_item_title")
            body = scope.get("rules_item_body")
            if not category or not title or not body:
                clear_item_step(scope)
                await reply_rich(
                    msg,
                    t("rules.editor.unexpected", locale, plain=True),
                    log_label="rules editor incomplete item",
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            try:
                await db.rules_db.add_item(
                    int(version["id"]),
                    str(category["category_key"]),
                    str(title),
                    str(body),
                    None if skip_url or not text else text,
                )
            except ValueError:
                log.warning("Rules item write refused for version %s", version["id"])
                clear_item_step(scope)
                await reply_rich(
                    msg,
                    t("rules.editor.unexpected", locale, plain=True),
                    log_label="rules editor version changed",
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            clear_item_step(scope)
            return await self.items(ctx)

        await reply_rich(
            msg,
            t("rules.editor.unexpected", locale, plain=True),
            log_label="rules editor unexpected text",
            parse_mode=None,
        )
        return WAITING_EDITOR_MENU

    async def preview(self, ctx: Ctx) -> int:
        """Preview the public menu built from the current draft categories."""
        query = ctx.callback_query
        if query is not None:
            await query.answer()
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        categories = await db.rules_db.list_categories(int(opened[0]["id"]))
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            t("rules.menu.preview", locale),
            rules_btn.draft_preview_btn(categories, locale),
        )
        return WAITING_EDITOR_MENU

    @staticmethod
    def _section_title(title: str) -> str:
        return title.split(":", 1)[-1].strip() if ":" in title else title

    async def preview_category(self, ctx: Ctx) -> int:
        """Preview the sections of one draft category."""
        query = ctx.callback_query
        if query is None or not _cb_text(ctx):
            return WAITING_EDITOR_MENU
        await query.answer()
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        key = _cb_text(ctx).split(":", 1)[-1]
        scope = flow_scope(ctx)
        scope["rules_preview_category"] = key
        rows = await db.rules_db.list_items(int(opened[1]["id"]), key)
        sections = list(
            dict.fromkeys(self._section_title(str(row["title"])) for row in rows)
        )
        categories = await db.rules_db.list_categories(int(opened[0]["id"]))
        category = next(
            (cat for cat in categories if str(cat["category_key"]) == key), None
        )
        label = str(category.get("title") or key) if category else key
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            rules_msg.category_editor_panel(
                {
                    "title": label,
                    "description": str((category or {}).get("description") or ""),
                },
                locale,
            ),
            rules_btn.draft_preview_sections_btn(sections, locale),
        )
        return WAITING_EDITOR_MENU

    async def preview_section(self, ctx: Ctx) -> int:
        """Preview the items of one draft section."""
        query = ctx.callback_query
        if query is None or not _cb_text(ctx):
            return WAITING_EDITOR_MENU
        await query.answer()
        scope = flow_scope(ctx)
        key = str(scope.get("rules_preview_category") or "")
        try:
            index = int(_cb_text(ctx).split(":", 1)[-1])
        except ValueError:
            return WAITING_EDITOR_MENU
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        rows = await db.rules_db.list_items(int(opened[1]["id"]), key)
        sections = list(
            dict.fromkeys(self._section_title(str(row["title"])) for row in rows)
        )
        if index >= len(sections):
            return WAITING_EDITOR_MENU
        section = sections[index]
        items = [
            row for row in rows if self._section_title(str(row["title"])) == section
        ]
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            rules_msg.rich_section_page(key, section, items, locale)["html"],
            rules_btn.draft_preview_sections_btn(sections, locale),
        )
        return WAITING_EDITOR_MENU

    async def preview_page(self, ctx: Ctx) -> int:
        """Handle a legacy preview-page tap by reopening the current preview."""
        query = ctx.callback_query
        if query is not None:
            await query.answer()
        return await self.preview(ctx)

    @staticmethod
    async def _locale(ctx: Ctx) -> str:
        return await locale_for_update(ctx)


rules_draft_editor = RulesDraftEditor()
