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
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.buttons.menus import open_pm_btn
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich, safe_edit_cb
from tcbot.modules.helper.messages import rules as rules_msg
from tcbot.modules.helper.pipelines.rules_publish import publish_rules
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER, build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)

_TCRULES_CMDS = build_prefixed_filters("tcrules")

# * One interactive state owns every editor callback and text step. The
# * pending step itself lives in the flow scope, so a typo in the old five
# * state layout could never strand a prompt with no reachable handler.
WAITING_EDITOR_MENU = 0
WAITING_CONFIRM_DISCARD = 5

_TITLE_MAX: int = 200
_BODY_MAX: int = 3500
_URL_MAX: int = 500


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


_EDITOR_SCOPE_KEYS = (
    "rules_set",
    "rules_version",
    "rules_step",
    "rules_item_title",
    "rules_item_body",
    "rules_category",
    "rules_category_key",
)


def _clear_item_step(scope: dict[str, Any]) -> None:
    """Forget a completed text step so a later chat message cannot repeat it."""
    for key in ("rules_step", "rules_item_title", "rules_item_body"):
        scope.pop(key, None)


def _clear_editor_scope(scope: dict[str, Any]) -> None:
    """Drop every editor key so a later session starts clean."""
    for key in _EDITOR_SCOPE_KEYS:
        scope.pop(key, None)


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
        await reply_rich(
            cast("Any", msg),
            replies.refuse_permission(await locale_for_update(update), plain=True),
            log_label="rules editor refusal",
            parse_mode=None,
        )


# * Telegram caps callback_data at 64 bytes. The longest category callback is
# * "rules_cat_rename:" (17 bytes) plus a numeric collision suffix, so the
# * slug must leave room for both.
_SLUG_MAX = 40


def _slug(title: str) -> str:
    """Derive a stable category slug from a display title."""
    base = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return base[:_SLUG_MAX] or "category"


class RulesEditor:
    """Owns the editor dialog for one staff member's rules draft."""

    async def _locale(self, update: Update) -> str:
        return await locale_for_update(update)

    async def _set_and_draft(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Ensure a community set and open its working draft."""
        # * A capability can be revoked while the editor conversation stays
        # * open. Every path that reaches this draft-opening write must
        # * re-check, not just the panel entry point.
        if not await editor_allowed(update):
            await refuse_editor(update)
            return None
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
        items = await db.rules_db.list_items(int(version["id"]))
        has_content = bool(items)
        text = await rules_msg.editor_panel(
            set_doc, version, locale, has_content=has_content, item_count=len(items)
        )
        markup = rules_btn.editor_panel_btn(locale, has_content=has_content)
        await self._edit_or_reply(update, text, markup)
        return WAITING_EDITOR_MENU

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Enter the editor from /tcrules in the moderator's private chat."""
        msg = update.effective_message
        if msg is None:
            return ConversationHandler.END
        chat = update.effective_chat
        if chat is not None and chat.type != "private":
            locale = await self._locale(update)
            await reply_rich(
                msg,
                t("rules.editor.open_pm", locale, plain=True),
                parse_mode=None,
                reply_markup=open_pm_btn(ctx.bot.username or "", "tcrules", locale),
            )
            return ConversationHandler.END
        return await self.panel(update, ctx)

    async def cat_action(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle rename, reorder, and delete actions on a category."""
        q = update.callback_query
        if q is None or q.data is None:
            return WAITING_EDITOR_MENU
        if not await editor_allowed(update):
            await refuse_editor(update)
            return WAITING_EDITOR_MENU
        await q.answer()
        action, key = q.data.split(":", 1)
        opened = await self._set_and_draft(update, ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, _version = opened
        set_id = int(set_doc["id"])
        scope = flow_scope(ctx, update)
        if action == "rules_cat_rename":
            scope["rules_category_key"] = key
            scope["rules_step"] = "rename_category"
            # * A callback prompt edits the tapped message; a fresh reply
            # * would strand the category keyboard above a new question.
            await self._edit_or_reply(
                update,
                t("rules.editor.ask_rename", await self._locale(update), plain=True),
                rules_btn.prompt_btn("rules_categories", await self._locale(update)),
            )
            return WAITING_EDITOR_MENU
        if action == "rules_cat_up":
            await db.rules_db.move_category(set_id, key, -1)
        elif action == "rules_cat_down":
            await db.rules_db.move_category(set_id, key, 1)
        elif action == "rules_cat_del":
            await db.rules_db.delete_category(set_id, key)
        return await self.categories(update, ctx)

    async def category_items(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Select a category and list the items of the open draft in it."""
        q = update.callback_query
        if q is None or q.data is None:
            return WAITING_EDITOR_MENU
        if not await editor_allowed(update):
            await refuse_editor(update)
            return WAITING_EDITOR_MENU
        await q.answer()
        key = q.data.split(":", 1)[1]
        opened = await self._set_and_draft(update, ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, _version = opened
        categories = await db.rules_db.list_categories(int(set_doc["id"]))
        match = next(
            (cat for cat in categories if str(cat["category_key"]) == key), None
        )
        if match is None:
            return await self.categories(update, ctx)
        flow_scope(ctx, update)["rules_category"] = match
        return await self.items(update, ctx)

    async def settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Show publication and acknowledgement status of the rule set."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        opened = await self._set_and_draft(update, ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, version = opened
        set_id = int(set_doc["id"])
        items = await db.rules_db.all_items(int(version["id"]))
        counts = await db.rules_db.status_counts(set_id)
        published = await db.rules_db.published_version(set_id)
        acks = (
            await db.rules_db.acknowledgement_count(int(published["id"]))
            if published
            else 0
        )
        text = t(
            "rules.editor.status",
            await self._locale(update),
            synced=counts.get("synced", 0),
            failed=counts.get("failed", 0),
            missing=counts.get("missing", 0),
            retired=counts.get("retired", 0),
            acks=acks,
        )
        await self._edit_or_reply(
            update,
            text,
            rules_btn.editor_panel_btn(
                await self._locale(update), has_content=bool(items)
            ),
        )
        return WAITING_EDITOR_MENU

    async def publish(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Publish the open draft and reconcile the channel immediately."""
        q = update.callback_query
        if q is None:
            return WAITING_EDITOR_MENU
        if not await editor_allowed(update):
            await refuse_editor(update)
            return WAITING_EDITOR_MENU
        await q.answer()
        locale = await self._locale(update)
        opened = await self._set_and_draft(update, ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, version = opened
        items = await db.rules_db.all_items(int(version["id"]))
        if not items:
            # * An empty draft has nothing to publish. Guide the reader into
            # * the editor instead of surfacing a technical publish error.
            await self._edit_or_reply(
                update,
                t("rules.publish.empty", locale),
                rules_btn.editor_panel_btn(locale, has_content=False),
            )
            return WAITING_EDITOR_MENU
        user_id = update.effective_user.id if update.effective_user else 0
        try:
            result = await publish_rules(
                int(set_doc["id"]),
                int(version["id"]),
                user_id,
                ctx.bot,
            )
        except Exception as exc:
            await self._edit_or_reply(
                update,
                t("rules.publish.error", locale, error=str(exc)),
                rules_btn.editor_panel_btn(locale, has_content=True),
            )
            return WAITING_EDITOR_MENU
        # * The cached version is still marked draft after publish. Refresh it
        # * from the database so the next mutation opens a fresh draft instead
        # * of appending rows to the now immutable published version.
        try:
            published = await db.rules_db.published_version(int(set_doc["id"]))
        except Exception as exc:
            log.warning(
                "Published-version refresh failed for set=%d: %s",
                int(set_doc["id"]),
                exc,
            )
            published = None
        if published is not None:
            scope = flow_scope(ctx, update)
            scope["rules_version"] = published
        await self._edit_or_reply(
            update,
            t(
                "rules.publish.result",
                locale,
                synced=result["synced"],
                failed=len(result["failed"]),
            ),
            rules_btn.editor_panel_btn(locale, has_content=True),
        )
        return WAITING_EDITOR_MENU

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
                await reply_rich(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            category = await db.rules_db.add_category(
                int(scope["rules_set"]["id"]), _slug(text), text
            )
            scope["rules_category"] = category
            _clear_item_step(scope)
            return await self.categories(update, ctx)

        if step == "rename_category":
            if not text or len(text) > _TITLE_MAX:
                await reply_rich(
                    msg,
                    t("rules.editor.bad_title", locale, limit=_TITLE_MAX, plain=True),
                    parse_mode=None,
                )
                return WAITING_EDITOR_MENU
            await db.rules_db.rename_category(
                int(scope["rules_set"]["id"]),
                str(scope.get("rules_category_key") or ""),
                text,
            )
            scope.pop("rules_step", None)
            return await self.categories(update, ctx)

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
            if text and (
                len(text) > _URL_MAX or not text.startswith(("https://", "http://"))
            ):
                await reply_rich(
                    msg, t("rules.editor.bad_url", locale, plain=True), parse_mode=None
                )
                return WAITING_EDITOR_MENU
            await db.rules_db.add_item(
                int(scope["rules_version"]["id"]),
                str(scope["rules_category"]["category_key"]),
                str(scope["rules_item_title"]),
                str(scope["rules_item_body"]),
                text or None,
            )
            _clear_item_step(scope)
            return await self.items(update, ctx)

        # * Typing while simply viewing the panel is unexpected input, not a
        # * request to leave. Keep the conversation and its draft alive.
        await reply_rich(
            msg,
            t("rules.editor.unexpected", locale, plain=True),
            log_label="rules editor unexpected text",
            parse_mode=None,
        )
        return WAITING_EDITOR_MENU

    async def categories(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """List the categories of the open draft, creating the draft if needed."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        opened = await self._set_and_draft(update, ctx)
        if opened is None:
            return ConversationHandler.END
        set_doc, _version = opened
        set_id = int(set_doc["id"])
        categories = await db.rules_db.list_categories(set_id)
        locale = await self._locale(update)
        text = rules_msg.category_list(categories, locale)
        markup = rules_btn.categories_btn(categories, locale)
        await self._edit_or_reply(update, text, markup)
        return WAITING_EDITOR_MENU

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
        markup = rules_btn.items_btn(items, locale)
        await self._edit_or_reply(update, text, markup)
        return WAITING_EDITOR_MENU

    async def ask_category_title(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Ask the staff member for a new category title."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        flow_scope(ctx, update)["rules_step"] = "category_title"
        locale = await self._locale(update)
        await self._edit_or_reply(
            update,
            t("rules.editor.ask_category", locale, plain=True),
            rules_btn.prompt_btn("rules_panel", locale),
        )
        return WAITING_EDITOR_MENU

    async def ask_item_title(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Ask for a new item title in the selected category."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        scope = flow_scope(ctx, update)
        scope["rules_step"] = "item_title"
        locale = await self._locale(update)
        await self._edit_or_reply(
            update,
            t("rules.editor.ask_title", locale, plain=True),
            rules_btn.prompt_btn("rules_categories", locale),
        )
        return WAITING_EDITOR_MENU

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
        # * Keep the editor open: Back returns to the main panel, Close exits.
        await self._edit_or_reply(update, text, rules_btn.preview_btn(locale))
        return WAITING_EDITOR_MENU

    async def ask_discard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Ask for confirmation before removing the draft."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        locale = await self._locale(update)
        await self._edit_or_reply(
            update,
            t("rules.editor.confirm_discard", locale),
            rules_btn.confirm_btn("rules_discard_yes", "rules_discard_no", locale),
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
        _clear_editor_scope(scope)
        locale = await self._locale(update)
        await self._edit_or_reply(update, t("rules.editor.discarded", locale), None)
        return ConversationHandler.END

    async def cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        """Leave the editor without changing the draft."""
        q = update.callback_query
        if q is not None:
            await q.answer()
        _clear_editor_scope(flow_scope(ctx, update))
        locale = await self._locale(update)
        await self._edit_or_reply(update, t("rules.editor.cancelled", locale), None)
        return ConversationHandler.END

    async def ignore_foreign_cancel(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Answer a moderation picker Cancel without closing the editor.

        That callback belongs to a ban or reason flow. A stale tap must not
        end an unrelated rules session, so the editor stays open.
        """
        q = update.callback_query
        if q is not None:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("foreign picker cancel answer failed: %s", exc)
        return WAITING_EDITOR_MENU

    async def _edit_or_reply(self, update: Update, text: str, markup: Any) -> None:
        """Edit the invoking message, or reply when no callback is present."""
        q = update.callback_query
        if q is not None:
            await safe_edit_cb(q, text, parse_mode=None, reply_markup=markup)
            return
        msg = update.effective_message
        if msg is not None:
            await reply_rich(msg, text, reply_markup=markup)


rules_editor = RulesEditor()


def build_rules_conv() -> ConversationHandler:
    """Build the single-state editor conversation used by ``/tcrules``.

    Every panel callback and text step lives in one state. The pending step
    is owned by the flow scope, so a button always has a reachable handler
    and a typed answer always returns to the same menu.
    """
    # * The group's Open in PM button uses a deep link. Registering it as an
    # * entry point starts the editor conversation, so its buttons keep working
    # * after the reader follows the link.
    _TCRULES_START = filters.ChatType.PRIVATE & filters.Regex(r"^/start\s+tcrules$")
    return ConversationHandler(
        entry_points=[
            MessageHandler(_TCRULES_CMDS, rules_editor.start),
            MessageHandler(_TCRULES_START, rules_editor.start),
        ],
        states={
            WAITING_EDITOR_MENU: [
                CallbackQueryHandler(rules_editor.panel, pattern=r"^rules_panel$"),
                CallbackQueryHandler(
                    rules_editor.categories, pattern=r"^rules_edit_draft$"
                ),
                CallbackQueryHandler(rules_editor.preview, pattern=r"^rules_preview$"),
                CallbackQueryHandler(
                    rules_editor.settings, pattern=r"^rules_settings$"
                ),
                CallbackQueryHandler(
                    rules_editor.ask_discard, pattern=r"^rules_discard$"
                ),
                CallbackQueryHandler(
                    rules_editor.cat_action,
                    pattern=r"^rules_cat_(rename|up|down|del):.+",
                ),
                CallbackQueryHandler(
                    rules_editor.category_items, pattern=r"^rules_cat:.+"
                ),
                CallbackQueryHandler(
                    rules_editor.categories, pattern=r"^rules_categories$"
                ),
                CallbackQueryHandler(
                    rules_editor.ask_category_title, pattern=r"^rules_cat_add$"
                ),
                CallbackQueryHandler(
                    rules_editor.ask_item_title, pattern=r"^rules_item_add$"
                ),
                CallbackQueryHandler(rules_editor.publish, pattern=r"^rules_publish$"),
                MessageHandler(
                    filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, rules_editor.on_text
                ),
            ],
            WAITING_CONFIRM_DISCARD: [
                CallbackQueryHandler(
                    rules_editor.discard, pattern=r"^rules_discard_yes$"
                ),
                CallbackQueryHandler(
                    rules_editor.cancel, pattern=r"^rules_discard_no$"
                ),
                # * The confirmation keyboard still shows Back and Close.
                # * Close is global; Back must return to the panel from here.
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
