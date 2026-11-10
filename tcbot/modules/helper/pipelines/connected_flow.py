# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group connection flow: join prompt, permission check, enforcement replay."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from telegram import (
    Bot,
    ChatMember,
    ChatPermissions,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import messages
from tcbot.modules.helper.keyboards import connect_join_kb
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_edit_cb, send_log
from tcbot.utils.dispatch import (
    count_transient_errors,
    drain_tasks,
    fan_out,
    gather_bounded,
    throw_if_cancelled,
)
from tcbot.utils.formatter import bold, code
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT, monotonic

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

    from tcbot.database.documents import ActiveMuteDoc

log = get_logger(__name__)

# ────────────────────────── Admin harvest ───────────────────────── #


_REQUIRED_PERMS: tuple[str, ...] = (
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
)
_REPLAY_CAP: int = 500
# * Telegram admits 20 requests a minute per group, so a long ban or mute
# * list cannot be enforced in one pass. The replay runs until this budget
# * is spent and reports the remainder as not applied; the enforcement
# * sweep repairs the rest. Without the budget a large list kept the
# * connect handler running for a quarter of an hour.
_REPLAY_BUDGET_S: float = 20.0
# * Enforcement actions issued per round. The deadline is checked between
# * rounds, so the round size bounds how long the budget can be overrun.
_REPLAY_ROUND: int = 8
_harvest_tasks: set[asyncio.Task[None]] = set()


async def drain_harvest_tasks() -> None:
    """Await in-flight admin-harvest tasks at shutdown."""
    await drain_tasks(_harvest_tasks, label="admin harvest")


async def _harvest_admin_identities(chat_id: int, admins: list[ChatMember]) -> None:
    """Persist identity data for every admin using change-detection writes."""
    coros = []
    for member in admins:
        user = getattr(member, "user", None)
        if user is None or user.is_bot or not user.first_name:
            continue
        coros.append(
            db.users_cache.harvest_user_identity(
                user.id, user.username, user.first_name, user.last_name
            )
        )
    if not coros:
        return
    results = await gather_bounded(coros)
    errors = sum(1 for r in results if isinstance(r, BaseException))
    if errors:
        log.debug(
            "Admin identity harvest for chat=%d: %d/%d writes failed",
            chat_id,
            errors,
            len(coros),
        )
    else:
        log.debug(
            "Admin identity harvest for chat=%d: %d identities cached",
            chat_id,
            len(coros),
        )


# ─────────────────────── Bot-added handling ─────────────────────── #


class ConnectionAddedMixin:
    """Bot-added member-update step: removal, demotion, and join fast paths."""

    if TYPE_CHECKING:

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
            """Check whether member holds every required permission."""
            ...

        def connected_blind_message(self, locale: str | None = None) -> str:
            """Blind-replay warning."""
            ...

        def connected_message(self, locale: str | None = None) -> str:
            """Success message."""
            ...

        def connecting_message(self, locale: str | None = None) -> str:
            """Progress message."""
            ...

        def join_keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
            """Connect / Cancel keyboard."""
            ...

        def join_prompt(self, locale: str | None = None) -> str:
            """Build the initial prompt."""
            ...

    async def on_bot_added(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle every change to the bot own member status in any chat."""
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
        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            conn_results = await asyncio.gather(
                db.groups_db.is_connected(chat.id, fresh=True),
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
                    await send_log(
                        ctx.bot,
                        messages.group_bot_removed_log(
                            chat.id, chat.title or "Unknown"
                        ),
                    )
                except Exception:
                    log.exception("Bot removed log failed for %d", chat.id)
            log.info("Bot removed from %d; group deactivated", chat.id)
            return
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
                    await send_log(
                        ctx.bot,
                        warning_text,
                    )
                except Exception as exc:
                    log.warning(
                        "Failed to send admin-rights-lost warning for chat=%d: %s",
                        chat.id,
                        exc,
                    )
            return
        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
            if cfg.is_primary_group(chat.id):
                return
            pending, is_already_connected = await asyncio.gather(
                db.groups_db.get_pending(chat.id),
                db.groups_db.is_connected(chat.id, fresh=True),
                return_exceptions=True,
            )
            throw_if_cancelled((pending, is_already_connected))
            if isinstance(pending, BaseException):
                log.warning(
                    "get_pending check failed on bot-added for %d: %s",
                    chat.id,
                    pending,
                )
                return
            if isinstance(is_already_connected, BaseException):
                log.warning(
                    "is_connected check failed on bot-added for %d: %s",
                    chat.id,
                    is_already_connected,
                )
                return
            if pending and new_status == ChatMemberStatus.ADMINISTRATOR:
                if self.check_perms(cmc.new_chat_member):
                    owner_fname = await db.users_cache.get_first_name(
                        pending.get("owner_id", 0), "Owner"
                    )
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


# ────────────────────────── Join decision ───────────────────────── #


class ConnectionDecisionMixin:
    """Connect / Cancel button step for the join prompt."""

    join_callback: str
    cancel_callback: str

    if TYPE_CHECKING:

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
            """Check whether member holds every required permission."""
            ...

        def already_connected_message(self, locale: str | None = None) -> str:
            """Notice when already connected."""
            ...

        def connected_blind_message(self, locale: str | None = None) -> str:
            """Blind-replay warning."""
            ...

        def connected_message(self, locale: str | None = None) -> str:
            """Success message."""
            ...

        def connecting_message(self, locale: str | None = None) -> str:
            """Progress message."""
            ...

        def declined_message(self, locale: str | None = None) -> str:
            """Notice when the owner declines."""
            ...

        def perms_required_message(self, locale: str | None = None) -> str:
            """Notice when the bot lacks admin permissions."""
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
        if cfg.is_primary_group(chat.id):
            try:
                await q.answer()
            except Exception as exc:
                log.debug("Join decision primary-group answer failed: %s", exc)
            return
        locale = await locale_for_update(update)
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
                await safe_edit_cb(
                    q,
                    t("connecting.state.bot_perms_verify", locale, plain=True),
                    parse_mode=None,
                    reply_markup=None,
                    log_level="debug",
                    log_label="Join decision perms-verify",
                    catch_all=True,
                )
                return
            if not self.check_perms(bot_member):
                prompt_msg_id = q.message.message_id if q.message else 0
                try:
                    await db.groups_db.add_pending(
                        chat.id,
                        chat.title or "",
                        user.id,
                        prompt_msg_id,
                    )
                except Exception:
                    log.exception("add_pending failed for chat %d", chat.id)
                    await safe_edit_cb(
                        q,
                        t("connecting.state.complete_join", locale, plain=True),
                        parse_mode=None,
                        reply_markup=None,
                        log_level="debug",
                        log_label="Join decision db-error",
                        catch_all=True,
                    )
                    return
                await safe_edit_cb(
                    q,
                    self.perms_required_message(locale),
                    parse_mode=None,
                    reply_markup=None,
                    log_level="debug",
                    log_label="Join decision perms-required",
                    catch_all=True,
                )
                return
            try:
                already_connected = await db.groups_db.is_connected(chat.id, fresh=True)
            except Exception:
                log.exception("is_connected failed for chat %d", chat.id)
                with contextlib.suppress(Exception):
                    await q.edit_message_text(
                        t("connecting.state.complete_join", locale, plain=True),
                        reply_markup=None,
                    )
                return
            if already_connected:
                await safe_edit_cb(
                    q,
                    self.already_connected_message(locale),
                    parse_mode=None,
                    reply_markup=None,
                    log_level="debug",
                    log_label="Join decision already-connected",
                    catch_all=True,
                )
                return
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
            try:
                await db.groups_db.remove_pending(chat.id)
            except Exception:
                log.exception("remove_pending failed for chat %d on cancel", chat.id)
            cancel_results = await asyncio.gather(
                q.edit_message_text(self.declined_message(locale), reply_markup=None),
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


# ─────────────────────── Connection builder ─────────────────────── #


@dataclass(frozen=True)
class BuildConnection(ConnectionAddedMixin, ConnectionDecisionMixin):
    """Configurable group-connection flow builder."""

    community_name: str
    required_perms: tuple[str, ...] = field(default=_REQUIRED_PERMS, kw_only=True)
    join_callback: str = field(default="tc_join", kw_only=True)
    cancel_callback: str = field(default="tc_cancel", kw_only=True)

    def join_prompt(self, locale: str | None = None) -> str:
        """Return the initial prompt sent when the bot is first added."""
        return t(
            "connecting.state.join_prompt",
            locale,
            community=self.community_name,
            plain=True,
        )

    def connected_message(self, locale: str | None = None) -> str:
        """Shown on a successful connection."""
        return t(
            "connecting.state.connected",
            locale,
            community=self.community_name,
            plain=True,
        )

    def connected_blind_message(self, locale: str | None = None) -> str:
        """Blind-replay warning shown instead of the success message."""
        return t(
            "connecting.state.connected_blind",
            locale,
            community=self.community_name,
            plain=True,
        )

    def declined_message(self, locale: str | None = None) -> str:
        """Shown when the owner taps Cancel."""
        return t("connecting.state.declined", locale, plain=True)

    def already_connected_message(self, locale: str | None = None) -> str:
        """Shown when the group is already part of the federation."""
        return t(
            "connecting.state.already_connected",
            locale,
            community=self.community_name,
            plain=True,
        )

    def connecting_message(self, locale: str | None = None) -> str:
        """Progress state edited into the prompt before the replay."""
        return t("connecting.state.connecting", locale, plain=True)

    def perms_required_message(self, locale: str | None = None) -> str:
        """Shown when the bot lacks the required admin permissions."""
        return t("connecting.state.perms_required", locale, plain=True)

    def join_keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
        """Connect / Cancel keyboard for the join prompt."""
        return connect_join_kb(self.join_callback, self.cancel_callback, locale=locale)

    def check_perms(self, member: ChatMember) -> bool:
        """Return True when member holds every permission in required_perms."""
        return all(getattr(member, p, False) for p in self.required_perms)

    @staticmethod
    async def _replay_bans(
        bot: Bot, chat_id: int, ban_uids: list[int], deadline: float
    ) -> tuple[int, int]:
        """Fan out every active federation ban into the new group.

        Returns ``(applied, skipped)``. The per-chat Telegram limit admits
        20 requests a minute, so a long list cannot be enforced in one
        pass: the replay stops at *deadline* and reports the remainder.
        """
        pending = list(ban_uids)
        applied = 0
        while pending and monotonic() < deadline:
            chunk = pending[:_REPLAY_ROUND]
            results = await fan_out(
                [bot.ban_chat_member(chat_id, uid) for uid in chunk]
            )
            applied += len(results) - count_transient_errors(results)
            pending = pending[len(chunk) :]
        return applied, len(pending)

    @staticmethod
    async def _replay_mutes(
        bot: Bot, chat_id: int, mute_docs: list[ActiveMuteDoc], deadline: float
    ) -> tuple[int, int]:
        """Fan out every active federation mute into the new group.

        Returns ``(applied, skipped)``; see :meth:`_replay_bans` for the
        deadline contract.
        """
        _mute_perms = ChatPermissions(can_send_messages=False)
        pending = list(mute_docs)
        applied = 0
        while pending and monotonic() < deadline:
            chunk = pending[:_REPLAY_ROUND]
            results = await fan_out(
                [
                    bot.restrict_chat_member(
                        chat_id,
                        int(doc.get("user_id", 0)),
                        permissions=_mute_perms,
                        until_date=doc.get("until_date"),
                    )
                    for doc in chunk
                ]
            )
            applied += len(results) - count_transient_errors(results)
            pending = pending[len(chunk) :]
        return applied, len(pending)

    async def complete_join(
        self,
        chat_id: int,
        chat_title: str,
        owner_id: int,
        owner_fname: str,
        bot: Bot,
    ) -> bool:
        """Connect the group and replay active bans and mutes. Returns blind flag."""
        (
            chat_result,
            ban_uids,
            mute_docs,
            admins_result,
            add_group_r,
        ) = await asyncio.gather(
            asyncio.wait_for(bot.get_chat(chat_id), timeout=TELEGRAM_LOOKUP_TIMEOUT),
            db.bans_db.active_ban_user_ids(),
            db.mutes_db.active_mute_docs(),
            asyncio.wait_for(
                bot.get_chat_administrators(chat_id), timeout=TELEGRAM_LOOKUP_TIMEOUT
            ),
            db.groups_db.add_group(chat_id, chat_title, owner_id),
            return_exceptions=True,
        )
        throw_if_cancelled(
            (chat_result, ban_uids, mute_docs, admins_result, add_group_r)
        )
        admins_list = (
            list(admins_result) if not isinstance(admins_result, BaseException) else []
        )
        if isinstance(add_group_r, BaseException):
            raise RuntimeError(f"add_group failed for chat {chat_id}") from add_group_r
        try:
            await db.groups_db.remove_pending(chat_id)
        except Exception:
            log.exception("remove_pending failed for chat %d after connect", chat_id)
        chat_username: str | None = (
            getattr(chat_result, "username", None)
            if not isinstance(chat_result, BaseException)
            else None
        )
        if isinstance(ban_uids, BaseException):
            log.error(
                "active_ban_user_ids failed for new chat %d: %s", chat_id, ban_uids
            )
            ban_uids = []
            replay_blind = True
        else:
            replay_blind = False
        # * The replay is bounded: Telegram paces same-chat requests, so a
        # * long enforcement list would otherwise keep the connect handler
        # * running far past any reasonable request window.
        deadline = monotonic() + _REPLAY_BUDGET_S
        if isinstance(mute_docs, BaseException):
            log.error("active_mute_docs failed for new chat %d: %s", chat_id, mute_docs)
            mute_docs = []
            replay_blind = True
        if len(ban_uids) > _REPLAY_CAP:
            log.warning(
                "Connect replay truncated to %d/%d bans for chat %d",
                _REPLAY_CAP,
                len(ban_uids),
                chat_id,
            )
            ban_uids = ban_uids[:_REPLAY_CAP]
            replay_blind = True
        if len(mute_docs) > _REPLAY_CAP:
            log.warning(
                "Connect replay truncated to %d/%d mutes for chat %d",
                _REPLAY_CAP,
                len(mute_docs),
                chat_id,
            )
            mute_docs = mute_docs[:_REPLAY_CAP]
            replay_blind = True
        if not isinstance(admins_result, BaseException) and admins_result:
            try:
                task = asyncio.get_running_loop().create_task(
                    _harvest_admin_identities(chat_id, admins_list)
                )
                _harvest_tasks.add(task)
                task.add_done_callback(_harvest_tasks.discard)
            except RuntimeError:
                log.debug("Harvest task skipped: no running event loop.")
        applied_bans, skipped_bans = await self._replay_bans(
            bot, chat_id, ban_uids, deadline
        )
        applied_mutes, skipped_mutes = await self._replay_mutes(
            bot, chat_id, mute_docs, deadline
        )
        if skipped_bans or skipped_mutes:
            # * The replay stopped at the budget, so the new group is not
            # * fully enforced yet. The operator is told to re-sync, and
            # * the enforcement sweep repairs the remainder.
            log.warning(
                "Connect replay for chat %d stopped at the time budget: "
                "%d ban(s) and %d mute(s) not applied.",
                chat_id,
                skipped_bans,
                skipped_mutes,
            )
            replay_blind = True
        try:
            await send_log(
                bot,
                messages.group_connected_log(
                    chat_id, chat_title, owner_id, owner_fname, chat_username
                ),
            )
        except Exception:
            log.exception("Group connect log failed")
        log.info(
            "Group %d ('%s') connected. %d bans and %d mutes applied.",
            chat_id,
            chat_title,
            applied_bans,
            applied_mutes,
        )
        if replay_blind:
            log.error(
                "Group %d connected BLIND: enforcement replay ran without ban/mute data.",
                chat_id,
            )
        return replay_blind


connection = BuildConnection(cfg.community_name)
