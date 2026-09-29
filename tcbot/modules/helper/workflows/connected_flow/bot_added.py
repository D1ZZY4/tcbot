# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bot-added event step of the group connection flow."""

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
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot, ChatMember, InlineKeyboardMarkup, Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)


class ConnectionAddedMixin:
    """Bot-added member-update step: removal, demotion, and join fast paths.

    Combined into ``BuildConnection``; text factories, permission checks,
    and ``complete_join`` referenced on ``self`` come from that subclass.
    """

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

        def connected_blind_message(self, locale: str | None = None) -> str:
            """Blind-replay warning shown instead of the success message."""
            ...

        def connected_message(self, locale: str | None = None) -> str:
            """Success message for a completed connection."""
            ...

        def connecting_message(self, locale: str | None = None) -> str:
            """Progress message shown during the enforcement replay."""
            ...

        def join_keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
            """Connect / Cancel keyboard for the join prompt."""
            ...

        def join_prompt(self, locale: str | None = None) -> str:
            """Build the initial prompt sent when the bot joins a group."""
            ...

    async def on_bot_added(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle every change to the bot's own member status in any chat."""
        cmc = update.my_chat_member
        if not cmc:
            return

        chat = cmc.chat
        if chat.type not in ("group", "supergroup"):
            return
        locale = await locale_for_update(update)

        new_status = cmc.new_chat_member.status
        old_status = cmc.old_chat_member.status if cmc.old_chat_member else None
        by_user = cmc.from_user
        lc, lt = cfg.logs

        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            # * is_connected, deactivate, and remove_pending all run in parallel
            conn_results = await asyncio.gather(
                db.groups_db.is_connected(chat.id),
                db.groups_db.deactivate_group(chat.id),
                db.groups_db.remove_pending(chat.id),
                return_exceptions=True,
            )
            throw_if_cancelled(conn_results)
            was_connected = conn_results[0]
            if isinstance(was_connected, BaseException):
                log.debug(
                    "is_connected check failed on bot removal from %d: %s",
                    chat.id,
                    was_connected,
                )
                was_connected = False
            if was_connected:
                try:
                    await ctx.bot.send_message(
                        lc,
                        parse_logmsg.group_bot_removed_log(
                            chat.id, chat.title or "Unknown"
                        ),
                        parse_mode="MarkdownV2",
                        message_thread_id=lt,
                    )
                except Exception:
                    log.exception("Bot removed log failed for %d", chat.id)
            log.info("Bot removed from %d; group deactivated", chat.id)
            return

        # Demotion: bot lost admin rights (was administrator, now member or restricted).
        # The group is NOT deactivated because permissions may be restored shortly, but
        # a warning is sent to the mod channel so staff are aware of the enforcement gap.
        # Primary groups (MAIN_GROUP, EXTEND_GROUP) are excluded from this warning since
        # they are managed separately and are not in the federated_groups collection.
        if (
            new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)
            and old_status == ChatMemberStatus.ADMINISTRATOR
        ):
            if not cfg.is_primary_group(chat.id):
                warning_text = (
                    f"Bot was demoted in group"
                    f" {bold(chat.title or str(chat.id))}"
                    f" \\(id: {code(str(chat.id))}\\)\\."
                    " Federation bans cannot be enforced there until"
                    " admin rights are restored\\."
                )
                try:
                    await ctx.bot.send_message(
                        lc,
                        warning_text,
                        parse_mode="MarkdownV2",
                        message_thread_id=lt,
                    )
                except Exception as exc:
                    log.warning(
                        "Failed to send admin-rights-lost warning for chat=%d: %s",
                        chat.id,
                        exc,
                    )
            return

        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
            # * Primary groups must never enter the federation join flow: no
            # * prompt, no pending row. They are required enforcement
            # * destinations, not connectable members.
            if cfg.is_primary_group(chat.id):
                return
            # * Speculatively pre-fetch both reads in parallel; is_already_connected
            # * is only consumed if the pending+ADMINISTRATOR fast path is not taken.
            pending, is_already_connected = await asyncio.gather(
                db.groups_db.get_pending(chat.id),
                db.groups_db.is_connected(chat.id),
                return_exceptions=True,
            )
            throw_if_cancelled((pending, is_already_connected))
            if isinstance(pending, BaseException):
                pending = None
            if isinstance(is_already_connected, BaseException):
                is_already_connected = False

            if pending and new_status == ChatMemberStatus.ADMINISTRATOR:
                if self.check_perms(cmc.new_chat_member):
                    owner_fname = await db.users_cache.get_first_name(
                        pending.get("owner_id", 0), "Owner"
                    )
                    # * complete_join (applies bans/mutes, sends log) is the
                    # * authoritative state write; run it first so we only
                    # * edit the join prompt to "connected" when the DB write
                    # * actually succeeded. Editing the prompt optimistically
                    # * in parallel was a bug: a complete_join failure would
                    # * leave the owner with a false confirmation while the
                    # * group remained absent from federated_groups.
                    # * Show progress first: the replay below can take
                    # * minutes on large federations. Stripping the buttons
                    # * also closes the double-tap window. Best-effort: the
                    # * final edit still lands when this one fails.
                    with contextlib.suppress(Exception):
                        await ctx.bot.edit_message_text(
                            self.connecting_message(locale),
                            chat_id=chat.id,
                            message_id=pending.get("message_id", 0),
                            reply_markup=None,
                        )
                    try:
                        blind = await self.complete_join(
                            chat.id,
                            chat.title or "",
                            pending.get("owner_id", 0),
                            owner_fname,
                            ctx.bot,
                        )
                    except Exception:
                        log.exception(
                            "complete_join failed in on_bot_added for chat %d",
                            chat.id,
                        )
                        # * Mirror on_join_decision: never leave the prompt
                        # * stuck on "connecting" with its buttons stripped.
                        with contextlib.suppress(Exception):
                            await ctx.bot.edit_message_text(
                                t("connecting.state.complete_join", locale, plain=True),
                                chat_id=chat.id,
                                message_id=pending.get("message_id", 0),
                                reply_markup=None,
                            )
                        return
                    try:
                        await ctx.bot.edit_message_text(
                            self.connected_blind_message(locale)
                            if blind
                            else self.connected_message(locale),
                            chat_id=chat.id,
                            message_id=pending.get("message_id", 0),
                            reply_markup=None,
                        )
                    except Exception as exc:
                        log.debug("Failed to edit pending connect prompt: %s", exc)
                return

            if is_already_connected:
                return

            if pending:
                return

            # * from_user is None when an anonymous admin adds the bot.
            # * We cannot store a valid owner_id in that case, so skip silently.
            if not by_user:
                log.info(
                    "Bot added to %d by anonymous admin; skipping join prompt",
                    chat.id,
                )
                return

            try:
                prompt = await ctx.bot.send_message(
                    chat.id,
                    self.join_prompt(locale),
                    reply_markup=self.join_keyboard(locale),
                )
                await db.groups_db.add_pending(
                    chat.id,
                    chat.title or "",
                    by_user.id,
                    prompt.message_id,
                )
            except Exception:
                log.exception("Join prompt send failed for %d", chat.id)
