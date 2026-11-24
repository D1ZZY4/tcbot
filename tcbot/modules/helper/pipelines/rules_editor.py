# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Main menu of the rules editor and the conversation that owns it."""

from __future__ import annotations

from pyrogram import filters

from tcbot import database as db
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.buttons.menus import open_pm_btn
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.handlers import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
)
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import reply_rich
from tcbot.modules.helper.pipelines.rules_editor_draft import rules_draft_editor
from tcbot.modules.helper.pipelines.rules_editor_steps import (
    _TCRULES_CMDS,
    WAITING_CONFIRM_DISCARD,
    WAITING_EDITOR_MENU,
    WAITING_MARKDOWN,
    clear_editor_scope,
    content_locale,
    edit_or_reply,
    editor_allowed,
    refuse_editor,
    set_and_draft,
)
from tcbot.modules.helper.pipelines.rules_publish import publish_rules
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import canonical_locale, display_name, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

log = get_logger(__name__)


class RulesEditor:
    """Owns the main menu of one staff member's rules editor."""

    @staticmethod
    async def _locale(ctx: Ctx) -> str:
        return await locale_for_update(ctx)

    async def panel(self, ctx: Ctx) -> int:
        """Show the editor panel, opening a draft when none exists."""
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return ConversationHandler.END
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, version = opened
        chosen = content_locale(ctx)
        locale = await self._locale(ctx)
        rows = await db.rules_db.list_items(int(version["id"]))
        await edit_or_reply(
            ctx,
            t(
                "rules.editor.panel",
                locale,
                name=str(set_doc.get("name") or "Community Rules"),
                status=str(set_doc.get("status") or "draft"),
                count=len(rows),
            )
            + "\n"
            + t("rules.editor.language", locale, language=display_name(chosen, None)),
            rules_btn.editor_sections_btn(rows, locale),
        )
        return WAITING_EDITOR_MENU

    async def start(self, ctx: Ctx) -> int:
        """Enter the editor from /tcrules in the moderator's private chat."""
        msg = ctx.effective_message
        if msg is None:
            return ConversationHandler.END
        chat = ctx.effective_chat
        if chat is not None and getattr(chat.type, "value", chat.type) != "private":
            locale = await self._locale(ctx)
            bot_username = (await ctx.bot_identity()).username or ""
            await reply_rich(
                msg,
                t("rules.editor.open_pm", locale, plain=True),
                parse_mode=None,
                reply_markup=open_pm_btn(bot_username, "tcrules", locale),
            )
            return ConversationHandler.END
        return await self.choose_language(ctx)

    async def choose_language(self, ctx: Ctx) -> int:
        """Open the content-language picker built from available catalogs."""
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return WAITING_EDITOR_MENU
        return await self._render_language_picker(ctx)

    async def _render_language_picker(self, ctx: Ctx) -> int:
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            t("rules.editor.choose_language", locale),
            rules_btn.rules_language_btn(content_locale(ctx), locale),
        )
        return WAITING_EDITOR_MENU

    async def set_language(self, ctx: Ctx) -> int:
        """Switch the rule-set language and reopen that locale's draft."""
        q = ctx.callback_query
        if q is None or q.data is None:
            return WAITING_EDITOR_MENU
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return WAITING_EDITOR_MENU
        chosen = canonical_locale(q.data.split(":", 1)[-1])
        if chosen is None:
            await q.answer()
            return await self._render_language_picker(ctx)
        scope = flow_scope(ctx)
        scope["rules_content_locale"] = chosen
        scope.pop("rules_version", None)
        return await self.panel(ctx)

    async def publish(self, ctx: Ctx) -> int:
        """Publish the open draft and reconcile the channel immediately."""
        q = ctx.callback_query
        if q is None:
            return WAITING_EDITOR_MENU
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return WAITING_EDITOR_MENU
        await q.answer()
        locale = await self._locale(ctx)
        opened = await set_and_draft(ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, version = opened
        chosen = content_locale(ctx)
        items = await db.rules_db.all_items(int(version["id"]))
        if not items:
            await edit_or_reply(
                ctx,
                t("rules.publish.empty", locale),
                rules_btn.editor_panel_btn(locale, has_content=False),
            )
            return WAITING_EDITOR_MENU
        user_id = ctx.effective_user.id if ctx.effective_user else 0
        try:
            result = await publish_rules(
                int(set_doc["id"]), int(version["id"]), user_id, ctx.bot, chosen
            )
        except Exception as exc:
            # * A channel failure can happen after promote_version committed.
            # * Refresh the snapshot so the next step opens a fresh draft.
            try:
                published = await db.rules_db.published_version(
                    int(set_doc["id"]), chosen
                )
            except Exception:
                log.warning("Published-version refresh failed after publish error")
                published = None
            if published is not None:
                flow_scope(ctx)["rules_version"] = published
            await edit_or_reply(
                ctx,
                t("rules.publish.error", locale, error=str(exc)),
                rules_btn.editor_panel_btn(
                    locale, has_content=True, content_locale=chosen
                ),
            )
            return WAITING_EDITOR_MENU
        try:
            published = await db.rules_db.published_version(int(set_doc["id"]), chosen)
        except Exception as exc:
            log.warning(
                "Published-version refresh failed for set=%d: %s",
                int(set_doc["id"]),
                exc,
            )
            published = None
        if published is not None:
            flow_scope(ctx)["rules_version"] = published
        await edit_or_reply(
            ctx,
            t(
                "rules.publish.result",
                locale,
                synced=result["synced"],
                failed=len(result["failed"]),
            ),
            rules_btn.editor_panel_btn(locale, has_content=True, content_locale=chosen),
        )
        return WAITING_EDITOR_MENU

    async def ask_discard(self, ctx: Ctx) -> int:
        """Ask for confirmation before removing the draft."""
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        locale = await self._locale(ctx)
        await edit_or_reply(
            ctx,
            t("rules.editor.confirm_discard", locale),
            rules_btn.confirm_btn("rules_discard_yes", "rules_discard_no", locale),
        )
        return WAITING_CONFIRM_DISCARD

    async def discard(self, ctx: Ctx) -> int:
        """Delete the draft; the channel and published version are untouched."""
        if not await editor_allowed(ctx):
            await refuse_editor(ctx)
            return ConversationHandler.END
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx)
        version_id = scope.get("rules_version", {}).get("id")
        if version_id is not None:
            await db.rules_db.discard_draft(int(version_id))
        clear_editor_scope(scope)
        await edit_or_reply(
            ctx, t("rules.editor.discarded", await self._locale(ctx)), None
        )
        return ConversationHandler.END

    async def cancel(self, ctx: Ctx) -> int:
        """Leave the editor without changing the draft."""
        q = ctx.callback_query
        if q is not None:
            await q.answer()
        clear_editor_scope(flow_scope(ctx))
        await edit_or_reply(
            ctx, t("rules.editor.cancelled", await self._locale(ctx)), None
        )
        return ConversationHandler.END

    async def ignore_foreign_cancel(self, ctx: Ctx) -> int:
        """Answer a moderation picker Cancel without closing the editor."""
        q = ctx.callback_query
        if q is not None:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("foreign picker cancel answer failed: %s", exc)
        return WAITING_EDITOR_MENU


rules_editor = RulesEditor()


def build_rules_conv() -> ConversationHandler:
    """Build the single-state editor conversation used by ``/tcrules``."""
    _TCRULES_START = filters.private & filters.regex(r"^/start\s+tcrules$")
    return ConversationHandler(
        entry_points=[
            MessageHandler(_TCRULES_CMDS, rules_editor.start),
            MessageHandler(_TCRULES_START, rules_editor.start),
        ],
        states={
            WAITING_EDITOR_MENU: [
                CallbackQueryHandler(rules_editor.panel, pattern=r"^rules_panel$"),
                CallbackQueryHandler(
                    rules_draft_editor.categories, pattern=r"^rules_edit_draft$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.preview, pattern=r"^rules_preview$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.preview_page,
                    pattern=r"^rules_preview_page:\d+$",
                ),
                CallbackQueryHandler(
                    rules_draft_editor.preview_category,
                    pattern=r"^rules_preview_cat:.+$",
                ),
                CallbackQueryHandler(
                    rules_draft_editor.preview_section,
                    pattern=r"^rules_preview_sec:\d+$",
                ),
                CallbackQueryHandler(
                    rules_draft_editor.items_page, pattern=r"^rules_items_page:\d+$"
                ),
                CallbackQueryHandler(
                    rules_editor.choose_language, pattern=r"^rules_lang$"
                ),
                CallbackQueryHandler(
                    rules_editor.set_language, pattern=r"^rules_lang_set:.+$"
                ),
                CallbackQueryHandler(
                    rules_editor.ask_discard, pattern=r"^rules_discard$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.cat_action,
                    pattern=r"^rules_cat_(rename|up|down|del):.+",
                ),
                CallbackQueryHandler(
                    rules_draft_editor.category_items, pattern=r"^rules_cat:.+"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.categories, pattern=r"^rules_categories$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.ask_category_title, pattern=r"^rules_cat_add$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.ask_item_title, pattern=r"^rules_item_add$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.ask_markdown, pattern=r"^rules_upload$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.sections, pattern=r"^rules_sections$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.edit_section,
                    pattern=r"^rules_section_edit:\d+$",
                ),
                CallbackQueryHandler(
                    rules_draft_editor.apply_format, pattern=r"^rules_fmt:.+$"
                ),
                CallbackQueryHandler(
                    rules_draft_editor.ask_section_title,
                    pattern=r"^rules_section_title$",
                ),
                CallbackQueryHandler(rules_editor.publish, pattern=r"^rules_publish$"),
                MessageHandler(
                    filters.text & ~ALL_PREFIXES_CMD_FILTER, rules_draft_editor.on_text
                ),
            ],
            WAITING_MARKDOWN: [
                MessageHandler(filters.document, rules_draft_editor.on_markdown),
                MessageHandler(
                    filters.text & ~ALL_PREFIXES_CMD_FILTER, rules_draft_editor.on_text
                ),
                CallbackQueryHandler(rules_editor.panel, pattern=r"^rules_panel$"),
                CallbackQueryHandler(
                    rules_editor.choose_language, pattern=r"^rules_lang$"
                ),
            ],
            WAITING_CONFIRM_DISCARD: [
                CallbackQueryHandler(
                    rules_editor.discard, pattern=r"^rules_discard_yes$"
                ),
                CallbackQueryHandler(
                    rules_editor.cancel, pattern=r"^rules_discard_no$"
                ),
                CallbackQueryHandler(rules_editor.panel, pattern=r"^rules_panel$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(
                rules_editor.ignore_foreign_cancel, pattern=r"^rules_step:cancel$"
            )
        ],
        per_message=False,
    )
