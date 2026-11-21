# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Conversation editor for community rules.

The editor keeps one draft per rule set and locale. Every mutation happens
on that draft, so a published version stays immutable and a failed edit can
never change what members already agreed to. The flow owns only the dialog:
persistence lives in ``rules_db`` and rendering in ``messages.rules``.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, cast

from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import database as db
from tcbot.modules.helper.keyboards import rules as rules_kb
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, safe_edit_cb, safe_reply
from tcbot.modules.helper.messages import rules as rules_msg
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)

WAITING_CATEGORY_TITLE = 1
WAITING_ITEM_TITLE = 2
WAITING_ITEM_BODY = 3
WAITING_ITEM_URL = 4
WAITING_CONFIRM_DISCARD = 5

_TITLE_MAX: int = 200
_BODY_MAX: int = 3500
_URL_MAX: int = 500
_SLUG_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


async def editor_allowed(update: Update) -> bool:
    """Re-check the editor capability on every editor surface.

    A capability can be revoked while a panel or a dialog stays open, so
    every mutation re-reads the permission instead of trusting the command
    that opened the editor. A lookup failure rejects.
    """
    uid = update.effective_user.id if update.effective_user else 0
    try:
        return await db.users_roles.has_permission(uid, "rules.manage")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("rules.manage lookup failed for %d: %s", uid, exc)
        return False


async def refuse_editor(update: Update) -> None:
    """Answer the callback and explain why an editor action was refused."""
    query = update.callback_query
    if query is not None:
        try:
            await query.answer()
        except Exception as exc:
            log.debug("editor refusal answer failed: %s", exc)
    msg = query.message if query is not None else update.effective_message
    if msg is not None:
        await safe_reply(
            cast("Any", msg),
            replies.refuse_permission(await locale_for_update(update), plain=True),
            log_label="rules editor refusal",
            parse_mode=None,
        )


def _slug(title: str) -> str:
    """Derive a stable category slug from a display title."""
    base = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return base[:60] or "category"


class RulesEditor:
    """Owns the editor dialog for one staff member's rules draft."""

    async def _locale(self, update: Update) -> str:
        return await locale_for_update(update)

    async def _set_and_draft(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Ensure a community set and open its working draft."""
        scope = flow_scope(ctx, update)
        set_doc = scope.get("rules_set")
        if set_doc is None:
            set_doc = await db.rules_db.get_or_create_community_set()
            scope["rules_set"] = set_doc
        version = scope.get("rules_version")
        if version is None or version.get("status") != "draft":
            version = await db.rules_db.open_draft(
                int(set_doc["id"]),
                update.effective_user.id if update.effective_user else 0,
            )
            scope["rules_version"] = version
        return set_doc, version

    async def panel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Show the editor panel, opening a draft when none exists."""
        if not await editor_allowed(update):
            await refuse_editor(update)
            return ConversationHandler.END
        q = update.callback_query
        if q is not None:
            await q.answer()
        opened = await self._set_and_draft(update, ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, version = opened
        locale = await self._locale(update)
        text = await rules_msg.editor_panel(set_doc, version, locale)
        markup = rules_kb.editor_panel_kb(locale)
        if q is not None:
            await q.edit_message_text(
                text, parse_mode="MarkdownV2", reply_markup=markup
            )
        else:
            msg = update.effective_message
            if msg is not None:
                await safe_reply(msg, text, reply_markup=markup)
        return ConversationHandler.END

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Route a typed answer to the pending editor step."""
        msg = update.effective_message
        user = update.effective_user
        if msg is None or user is None or not msg.text:
            return ConversationHandler.END
        if not await editor_allowed(update):
            await refuse_editor(update)
            return ConversationHandler.END
        scope = flow_scope(ctx, update)
        step = scope.get("rules_step")
        text = msg.text.strip()
        locale = await self._locale(update)

        if step == "category_title":
            if not text or len(text) > _TITLE_MAX:
                await safe_reply(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_CATEGORY_TITLE
            category = await db.rules_db.add_category(
                int(scope["rules_set"]["id"]), _slug(text), text
            )
            scope["rules_category"] = category
            return await self.categories(update, ctx)

        if step == "rename_category":
            if not text or len(text) > _TITLE_MAX:
                await safe_reply(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_CATEGORY_TITLE
            await db.rules_db.rename_category(
                int(scope["rules_set"]["id"]),
                str(scope.get("rules_category_key") or ""),
                text,
            )
            scope.pop("rules_step", None)
            return await self.categories(update, ctx)

        if step == "item_title":
            if not text or len(text) > _TITLE_MAX:
                await safe_reply(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_ITEM_TITLE
            scope["rules_item_title"] = text
            scope["rules_step"] = "item_body"
            await safe_reply(
                msg, t("rules.editor.ask_body", locale, plain=True), parse_mode=None
            )
            return WAITING_ITEM_BODY

        if step == "item_body":
            if not text or len(text) > _BODY_MAX:
                await safe_reply(
                    msg,
                    t("rules.editor.bad_body", locale, limit=_BODY_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_ITEM_BODY
            scope["rules_item_body"] = text
            scope["rules_step"] = "item_url"
            await safe_reply(
                msg, t("rules.editor.ask_url", locale, plain=True), parse_mode=None
            )
            return WAITING_ITEM_URL

        if step == "item_url":
            if text and (
                len(text) > _URL_MAX or not text.startswith(("https://", "http://"))
            ):
                await safe_reply(
                    msg, t("rules.editor.bad_url", locale, plain=True), parse_mode=None
                )
                return WAITING_ITEM_URL
            await db.rules_db.add_item(
                int(scope["rules_version"]["id"]),
                str(scope["rules_category"]["category_key"]),
                str(scope["rules_item_title"]),
                str(scope["rules_item_body"]),
                text or None,
            )
            return await self.items(update, ctx)

        return ConversationHandler.END

    async def categories(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """List the categories of the open draft."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx, update)
        set_id = int(scope["rules_set"]["id"])
        categories = await db.rules_db.list_categories(set_id)
        locale = await self._locale(update)
        text = rules_msg.category_list(categories, locale)
        markup = rules_kb.categories_kb(categories, locale)
        await self._edit_or_reply(update, text, markup)
        return ConversationHandler.END

    async def items(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """List the items of the selected draft category."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx, update)
        version_id = int(scope["rules_version"]["id"])
        category = scope.get("rules_category")
        category_key = str(category["category_key"]) if category else None
        items = await db.rules_db.list_items(version_id, category_key)
        locale = await self._locale(update)
        text = rules_msg.item_list(items, locale)
        markup = rules_kb.items_kb(items, locale)
        await self._edit_or_reply(update, text, markup)
        return ConversationHandler.END

    async def ask_category_title(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Ask the staff member for a new category title."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        flow_scope(ctx, update)["rules_step"] = "category_title"
        msg = update.effective_message
        if msg is not None:
            await safe_reply(
                msg,
                t("rules.editor.ask_category", await self._locale(update), plain=True),
                parse_mode=None,
            )
        return WAITING_CATEGORY_TITLE

    async def ask_item_title(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Ask for a new item title in the selected category."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx, update)
        scope["rules_step"] = "item_title"
        msg = update.effective_message
        if msg is not None:
            await safe_reply(
                msg,
                t("rules.editor.ask_title", await self._locale(update), plain=True),
                parse_mode=None,
            )
        return WAITING_ITEM_TITLE

    async def preview(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Render the draft exactly as the channel will see it."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx, update)
        version_id = int(scope["rules_version"]["id"])
        items = await db.rules_db.list_items(version_id)
        locale = await self._locale(update)
        text = await rules_msg.preview(items, locale)
        await self._edit_or_reply(update, text, None)
        return ConversationHandler.END

    async def ask_discard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Ask for confirmation before removing the draft."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        locale = await self._locale(update)
        await self._edit_or_reply(
            update,
            t("rules.editor.confirm_discard", locale),
            rules_kb.confirm_kb("rules_discard_yes", "rules_discard_no", locale),
        )
        return WAITING_CONFIRM_DISCARD

    async def discard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Delete the draft; the channel and published version are untouched."""
        if not await editor_allowed(update):
            await refuse_editor(update)
            return ConversationHandler.END
        q = update.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx, update)
        version_id = scope.get("rules_version", {}).get("id")
        if version_id is not None:
            await db.rules_db.discard_draft(int(version_id))
        scope.pop("rules_version", None)
        locale = await self._locale(update)
        await self._edit_or_reply(update, t("rules.editor.discarded", locale), None)
        return ConversationHandler.END

    async def cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Leave the editor without changing the draft."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        locale = await self._locale(update)
        await self._edit_or_reply(update, t("rules.editor.cancelled", locale), None)
        return ConversationHandler.END

    async def _edit_or_reply(self, update: Update, text: str, markup: Any) -> None:
        """Edit the invoking message, or reply when no callback is present."""
        q = update.callback_query
        if q is not None:
            await safe_edit_cb(q, text, parse_mode="MarkdownV2", reply_markup=markup)
            return
        msg = update.effective_message
        if msg is not None:
            await safe_reply(msg, text, reply_markup=markup)


rules_editor = RulesEditor()


def build_rules_conv() -> ConversationHandler:
    """Build the rules editor conversation used by ``/tcrules``.

    The panel callbacks enter the same states as the text steps, so a
    moderator can move between lists and input without leaving the flow.
    """
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(rules_editor.panel, pattern=r"^rules_edit_draft$"),
        ],
        states={
            WAITING_CATEGORY_TITLE: [
                MessageHandler(
                    filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, rules_editor.on_text
                )
            ],
            WAITING_ITEM_TITLE: [
                MessageHandler(
                    filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, rules_editor.on_text
                )
            ],
            WAITING_ITEM_BODY: [
                MessageHandler(
                    filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, rules_editor.on_text
                )
            ],
            WAITING_ITEM_URL: [
                MessageHandler(
                    filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, rules_editor.on_text
                )
            ],
            WAITING_CONFIRM_DISCARD: [
                CallbackQueryHandler(
                    rules_editor.discard, pattern=r"^rules_discard_yes$"
                ),
                CallbackQueryHandler(
                    rules_editor.cancel, pattern=r"^rules_discard_no$"
                ),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(rules_editor.cancel, pattern=r"^rules_step:cancel$")
        ],
        per_message=False,
    )
