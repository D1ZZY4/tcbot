# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Owner-only Connect and Cancel decision for the group join prompt."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from telegram import Bot, ChatMember, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import messages
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    answer_ack,
    answer_alert,
    cb_error_edit,
    safe_edit_cb,
    send_log,
)
from tcbot.modules.helper.pipelines.connect_common import welcome_permission_note
from tcbot.modules.helper.pipelines.connect_verify import handle_verify_step
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)


class ConnectionDecisionMixin:
    """Connect / Cancel button step for the join prompt."""

    join_callback: str
    cancel_callback: str
    verify_callback: str

    if TYPE_CHECKING:

        async def complete_join(
            self,
            chat_id: int,
            chat_title: str,
            owner_id: int,
            owner_fname: str,
            bot: Bot,
        ) -> bool:
            """Replay decisions into the new group."""
            ...

        def check_perms(self, member: ChatMember) -> bool:
            """Check the bot's required admin rights."""
            ...

        def verify_prompt(self, step: int, locale: str | None = None) -> str:
            """One verification page."""
            ...

        def verify_keyboard(
            self, step: int, locale: str | None = None
        ) -> InlineKeyboardMarkup:
            """Keyboard of one verification page."""
            ...

        def already_connected_message(self, locale: str | None = None) -> str:
            """Notice for an already connected group."""
            ...

        def connected_blind_message(self, locale: str | None = None) -> str:
            """Warning for an incomplete replay."""
            ...

        def connected_message(self, locale: str | None = None) -> str:
            """Success notice."""
            ...

        def connecting_message(self, locale: str | None = None) -> str:
            """Progress notice."""
            ...

        def declined_message(self, locale: str | None = None) -> str:
            """Notice after a Cancel tap."""
            ...

        def perms_required_message(self, locale: str | None = None) -> str:
            """Notice when admin rights are missing."""
            ...

    async def on_verify_step(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Advance the About verification pages shown before connecting."""
        await handle_verify_step(self, update, ctx)

    async def on_join_decision(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle Connect / Cancel button callbacks on the join prompt."""
        q = update.callback_query
        chat = update.effective_chat
        user = update.effective_user
        if q is None:
            return
        if chat is None or user is None:
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Join decision answer failed with no chat/user: %s", exc)
            return
        if cfg.is_primary_group(chat.id) or cfg.is_infrastructure_chat(chat.id):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Join decision infrastructure answer failed: %s", exc)
            return
        locale = await locale_for_update(update)
        try:
            membership = await asyncio.wait_for(
                ctx.bot.get_chat_member(chat.id, user.id),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Join decision role check failed: %s", exc)
            await answer_alert(
                q, t("connecting.state.role_check_failed", locale, plain=True)
            )
            return
        # * The prompt is one shared message, so a refusal must not remove
        # * its keyboard: any member could otherwise destroy the owner's
        # * only Connect button. An alert keeps the prompt live.
        if membership.status != ChatMemberStatus.OWNER:
            await answer_alert(q, t("connecting.state.owner_only", locale, plain=True))
            return
        await answer_ack(q)
        action = q.data
        if action == self.join_callback:
            try:
                bot_member = await asyncio.wait_for(
                    ctx.bot.get_chat_member(chat.id, ctx.bot.id),
                    timeout=TELEGRAM_LOOKUP_TIMEOUT,
                )
            except Exception as exc:
                log.debug("Join decision permission check failed: %s", exc)
                await cb_error_edit(
                    q,
                    t("connecting.state.bot_perms_verify", locale, plain=True),
                    log_label="Join decision perms-verify",
                    parse_mode=None,
                )
                return
            if not self.check_perms(bot_member):
                prompt_msg_id = q.message.message_id if q.message else 0
                try:
                    await db.groups_db.add_pending(
                        chat.id, chat.title or "", user.id, prompt_msg_id
                    )
                except Exception:
                    log.exception("add_pending failed for chat %d", chat.id)
                    await cb_error_edit(
                        q,
                        t("connecting.state.complete_join", locale, plain=True),
                        log_label="Join decision db-error",
                        parse_mode=None,
                    )
                    return
                await cb_error_edit(
                    q,
                    self.perms_required_message(locale),
                    log_label="Join decision perms-required",
                    parse_mode=None,
                )
                return
            try:
                already_connected = await db.groups_db.is_connected(chat.id, fresh=True)
            except Exception:
                log.exception("is_connected failed for chat %d", chat.id)
                with contextlib.suppress(Exception):
                    await safe_edit_cb(
                        q,
                        t("connecting.state.complete_join", locale, plain=True),
                        reply_markup=None,
                        parse_mode=None,
                    )
                return
            if already_connected:
                await cb_error_edit(
                    q,
                    self.already_connected_message(locale),
                    log_label="Join decision already-connected",
                    parse_mode=None,
                )
                return
            with contextlib.suppress(Exception):
                await safe_edit_cb(
                    q, self.connecting_message(locale), reply_markup=None
                )
            try:
                blind = await self.complete_join(
                    chat.id, chat.title or "", user.id, user.first_name, ctx.bot
                )
            except Exception:
                log.exception("complete_join failed for chat %d", chat.id)
                with contextlib.suppress(Exception):
                    await safe_edit_cb(
                        q,
                        t("connecting.state.complete_join", locale, plain=True),
                        reply_markup=None,
                        parse_mode=None,
                    )
                return
            welcome_note = await welcome_permission_note(ctx.bot, chat.id, locale)
            with contextlib.suppress(Exception):
                await safe_edit_cb(
                    q,
                    (
                        self.connected_blind_message(locale)
                        if blind
                        else self.connected_message(locale)
                    )
                    + welcome_note,
                    reply_markup=None,
                )
        elif action == self.cancel_callback:
            # * The callback data is a static literal, so a keyboard that
            # survived a failed edit (or a duplicate tap) can arrive after the
            # group was already connected. Leaving then would drop a live
            # federation group while its database row stays active. Require a
            # still-pending request and a disconnected group before acting.
            try:
                pending = await db.groups_db.get_pending(chat.id)
                still_connected = await db.groups_db.is_connected(chat.id, fresh=True)
            except Exception:
                log.exception("cancel guard lookup failed for chat %d", chat.id)
                return
            if pending is None or still_connected:
                log.info(
                    "Ignoring stale connect cancel for chat=%d (pending=%s, connected=%s)",
                    chat.id,
                    pending is not None,
                    still_connected,
                )
                return
            try:
                await db.groups_db.remove_pending(chat.id)
            except Exception:
                log.exception("remove_pending failed for chat %d on cancel", chat.id)
            cancel_results = await asyncio.gather(
                safe_edit_cb(q, self.declined_message(locale), reply_markup=None),
                send_log(
                    ctx.bot,
                    messages.group_connection_rejected_log(
                        chat.id,
                        chat.title or "Unknown",
                        user.id,
                        user.first_name,
                    ),
                ),
                ctx.bot.leave_chat(chat.id),
                return_exceptions=True,
            )
            throw_if_cancelled(cancel_results)
            for label, result in zip(
                ("card edit", "rejection log", "leave"), cancel_results, strict=True
            ):
                if isinstance(result, BaseException):
                    log.warning(
                        "Join cancellation (%s) failed for chat=%d: %s",
                        label,
                        chat.id,
                        result,
                    )
