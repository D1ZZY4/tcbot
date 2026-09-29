# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Join-decision callback step of the group connection flow."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from telegram.constants import ChatMemberStatus

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.locale import locale_for_update
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Bot, ChatMember, Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)


class ConnectionDecisionMixin:
    """Connect / Cancel button step for the join prompt.

    Combined into ``BuildConnection``; text factories, permission checks,
    and ``complete_join`` referenced on ``self`` come from that subclass.
    """

    join_callback: str
    cancel_callback: str

    if TYPE_CHECKING:
        # * Combined into BuildConnection at runtime; stubs keep pyright
        # * honest about the surface this handler consumes from self.
        async def complete_join(
            self,
            chat_id: int,
            chat_title: str,
            owner_id: int,
            owner_fname: str,
            bot: Bot,
        ) -> bool:
            """Enforce existing bans and mutes onto a new group."""
            ...

        def check_perms(self, member: ChatMember) -> bool:
            """Check whether member holds every required bot permission."""
            ...

        def already_connected_message(self, locale: str | None = None) -> str:
            """Notice shown when the group is already connected."""
            ...

        def connected_blind_message(self, locale: str | None = None) -> str:
            """Blind-replay warning shown instead of the success message."""
            ...

        def connected_message(self, locale: str | None = None) -> str:
            """Success message for a completed connection."""
            ...

        def connecting_message(self, locale: str | None = None) -> str:
            """Progress message shown during the enforcement replay."""
            ...

        def declined_message(self, locale: str | None = None) -> str:
            """Notice shown when the owner declines the join."""
            ...

        def perms_required_message(self, locale: str | None = None) -> str:
            """Notice shown when the bot lacks admin permissions."""
            ...

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
        lc, lt = cfg.logs
        locale = await locale_for_update(update)

        # * Gather q.answer() + member check in parallel so the spinner
        # * disappears immediately regardless of Telegram API latency.
        member_res, ans_res = await asyncio.gather(
            asyncio.wait_for(
                ctx.bot.get_chat_member(chat.id, user.id),
                timeout=TELEGRAM_LOOKUP_TIMEOUT,
            ),
            q.answer(),
            return_exceptions=True,
        )
        throw_if_cancelled((member_res, ans_res))
        msg = update.effective_message
        if isinstance(member_res, BaseException):
            log.debug("Join decision role check failed: %s", member_res)
            coros: list = [q.edit_message_reply_markup(None)]
            if msg:
                coros.append(
                    msg.reply_text(
                        t("connecting.state.role_check_failed", locale, plain=True)
                    )
                )
            await asyncio.gather(*coros, return_exceptions=True)
            return

        if member_res.status != ChatMemberStatus.OWNER:
            coros = [q.edit_message_reply_markup(None)]
            if msg:
                coros.append(
                    msg.reply_text(t("connecting.state.owner_only", locale, plain=True))
                )
            await asyncio.gather(*coros, return_exceptions=True)
            return

        action = q.data

        if action == self.join_callback:
            try:
                bot_member = await asyncio.wait_for(
                    ctx.bot.get_chat_member(chat.id, ctx.bot.id),
                    timeout=TELEGRAM_LOOKUP_TIMEOUT,
                )
            except Exception as exc:
                log.debug("Join decision permission check failed: %s", exc)
                try:
                    await q.edit_message_text(
                        t("connecting.state.bot_perms_verify", locale, plain=True),
                        reply_markup=None,
                    )
                except Exception as exc2:
                    log.debug("Join decision perms-verify edit failed: %s", exc2)
                return

            if not self.check_perms(bot_member):
                prompt_msg_id = q.message.message_id if q.message else 0
                # * Persist the pending row before overwriting the prompt: if
                # * add_pending fails there is nothing to approve later, so
                # * report the error instead of showing perms-required.
                try:
                    await db.groups_db.add_pending(
                        chat.id,
                        chat.title or "",
                        user.id,
                        prompt_msg_id,
                    )
                except Exception:
                    log.exception("add_pending failed for chat %d", chat.id)
                    try:
                        await q.edit_message_text(
                            t("connecting.state.complete_join", locale, plain=True),
                            reply_markup=None,
                        )
                    except Exception as exc:
                        log.debug("Join decision db-error edit failed: %s", exc)
                    return
                try:
                    await q.edit_message_text(
                        self.perms_required_message(locale), reply_markup=None
                    )
                except Exception as exc:
                    log.debug("Join decision perms-required edit failed: %s", exc)
                return

            # * Guarded like every neighbouring DB call: an outage here must
            # * report the error instead of leaving the prompt hanging.
            try:
                already_connected = await db.groups_db.is_connected(chat.id)
            except Exception:
                log.exception("is_connected failed for chat %d", chat.id)
                with contextlib.suppress(Exception):
                    await q.edit_message_text(
                        t("connecting.state.complete_join", locale, plain=True),
                        reply_markup=None,
                    )
                return
            if already_connected:
                try:
                    await q.edit_message_text(
                        self.already_connected_message(locale), reply_markup=None
                    )
                except Exception as exc:
                    log.debug("Join decision already-connected edit failed: %s", exc)
                return

            # * complete_join must succeed before showing the success message.
            # * Running both in a gather was a bug: if complete_join raised, the group
            # * was never persisted but the owner saw "connected" anyway.
            # * Show progress first (same rationale as the on_bot_added path
            # * above): the ban/mute replay can take minutes, and stripping
            # * the buttons closes the double-tap window.
            with contextlib.suppress(Exception):
                await q.edit_message_text(
                    self.connecting_message(locale), reply_markup=None
                )
            try:
                blind = await self.complete_join(
                    chat.id, chat.title or "", user.id, user.first_name, ctx.bot
                )
            except Exception:
                log.exception("complete_join failed for chat %d", chat.id)
                with contextlib.suppress(Exception):
                    await q.edit_message_text(
                        t("connecting.state.complete_join", locale, plain=True),
                        reply_markup=None,
                    )
                return
            with contextlib.suppress(Exception):
                await q.edit_message_text(
                    self.connected_blind_message(locale)
                    if blind
                    else self.connected_message(locale),
                    reply_markup=None,
                )

        elif action == self.cancel_callback:
            # * Remove the pending row first: if it survives while the bot
            # * leaves, the next on_bot_added sees a stale pending and drops
            # * the join silently (deadlock with no prompt).
            try:
                await db.groups_db.remove_pending(chat.id)
            except Exception:
                log.exception("remove_pending failed for chat %d on cancel", chat.id)
            await asyncio.gather(
                q.edit_message_text(self.declined_message(locale), reply_markup=None),
                ctx.bot.send_message(
                    lc,
                    parse_logmsg.group_connection_rejected_log(
                        chat.id,
                        chat.title or "Unknown",
                        user.id,
                        user.first_name,
                    ),
                    parse_mode="MarkdownV2",
                    message_thread_id=lt,
                ),
                ctx.bot.leave_chat(chat.id),
                return_exceptions=True,
            )
