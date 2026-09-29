# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group connection builder: prompts, permission checks, enforcement replay."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from telegram import (
    Bot,
    ChatMember,
    ChatPermissions,
    InlineKeyboardMarkup,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.keyboards import connect_join_kb
from tcbot.modules.helper.workflows.connected_flow.bot_added import (
    ConnectionAddedMixin,
)
from tcbot.modules.helper.workflows.connected_flow.harvest import (
    _harvest_admin_identities,
    _harvest_tasks,
)
from tcbot.modules.helper.workflows.connected_flow.join_decision import (
    ConnectionDecisionMixin,
)
from tcbot.modules.helper.workflows.connected_flow.shared import (
    _REPLAY_CAP,
    _REQUIRED_PERMS,
)
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
)
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from tcbot.database.documents import ActiveMuteDoc

log = get_logger(__name__)


@dataclass(frozen=True)
class BuildConnection(ConnectionAddedMixin, ConnectionDecisionMixin):
    """Configurable group-connection flow builder."""

    community_name: str
    required_perms: tuple[str, ...] = field(default=_REQUIRED_PERMS, kw_only=True)
    join_callback: str = field(default="tc_join", kw_only=True)
    cancel_callback: str = field(default="tc_cancel", kw_only=True)

    # ── Text factories ─────────────────────────────────────────────────────

    def join_prompt(self, locale: str | None = None) -> str:
        """Return the initial prompt to send when the bot is first added to a group."""
        return t(
            "connecting.state.join_prompt",
            locale,
            community=self.community_name,
            plain=True,
        )

    def connected_message(self, locale: str | None = None) -> str:
        """Shown (or edited into the prompt) on a successful connection."""
        return t(
            "connecting.state.connected",
            locale,
            community=self.community_name,
            plain=True,
        )

    def connected_blind_message(self, locale: str | None = None) -> str:
        """Blind-replay warning shown instead of the success message.

        Used when the enforcement replay ran without ban/mute data, so
        the owner knows to re-sync.
        """
        return t(
            "connecting.state.connected_blind",
            locale,
            community=self.community_name,
            plain=True,
        )

    def declined_message(self, locale: str | None = None) -> str:
        """Shown when the owner taps Cancel on the join prompt."""
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
        """Progress state edited into the prompt before the ban/mute replay.

        The replay fans every active ban/mute into the new group, which
        takes minutes on large federations; without this the owner stares
        at a dead prompt with live buttons for the whole duration.
        """
        return t("connecting.state.connecting", locale, plain=True)

    def perms_required_message(self, locale: str | None = None) -> str:
        """Shown when the bot lacks the required admin permissions."""
        return t("connecting.state.perms_required", locale, plain=True)

    # ── Keyboard factory ───────────────────────────────────────────────────

    def join_keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
        """Connect / Cancel inline keyboard attached to the join prompt.

        Markup lives in :func:`keyboards.connect_join_kb`; this stays as a
        thin delegating step so existing call sites keep working.
        """
        return connect_join_kb(self.join_callback, self.cancel_callback, locale=locale)

    # ── Permission check ───────────────────────────────────────────────────

    def check_perms(self, member: ChatMember) -> bool:
        """Return True when member holds every permission in required_perms."""
        return all(getattr(member, p, False) for p in self.required_perms)

    # ── Connection executor ────────────────────────────────────────────────

    @staticmethod
    async def _replay_bans(bot: Bot, chat_id: int, ban_uids: list[int]) -> int:
        """Fan out every active federation ban into the new group.

        Returns the applied count. Uses ``count_transient_errors`` (not
        ``count_errors``) so a "user was not in chat" BadRequest does
        not count as a real failure: for a ban-replay, the user not being
        in the chat is the desired end state.
        """
        results = await fan_out([bot.ban_chat_member(chat_id, uid) for uid in ban_uids])
        return len(results) - count_transient_errors(results)

    @staticmethod
    async def _replay_mutes(
        bot: Bot, chat_id: int, mute_docs: list[ActiveMuteDoc]
    ) -> int:
        """Fan out every active federation mute into the new group.

        Returns the applied count. Benign "user not in chat" or "user is
        a bot" refusals do not count as failures: the desired end state
        is that the user is restricted, and they were never in the chat
        to begin with.
        """
        _mute_perms = ChatPermissions(can_send_messages=False)
        mute_results = await fan_out(
            [
                bot.restrict_chat_member(
                    chat_id,
                    int(doc.get("user_id", 0)),
                    permissions=_mute_perms,
                    until_date=doc.get("until_date"),
                )
                for doc in mute_docs
            ]
        )
        return len(mute_results) - count_transient_errors(mute_results)

    async def complete_join(
        self,
        chat_id: int,
        chat_title: str,
        owner_id: int,
        owner_fname: str,
        bot: Bot,
    ) -> bool:
        """Connect the group, apply all active federation bans, and notify LOG_CHANNEL.

        Returns True when the enforcement replay ran blind (ban/mute fetch
        failed) so callers can warn the owner instead of confirming success.
        """
        # * Fetch chat info + active ban IDs + active mute docs + admin list + register group + clear pending.
        # * All Telegram and DB calls fire in parallel; bounded timeouts prevent stalls.
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
        admins_list = (
            list(admins_result) if not isinstance(admins_result, BaseException) else []
        )
        # * add_group is the critical write; if it failed the group is not in the DB.
        # * Re-raise so callers can detect failure and avoid sending a false confirmation.
        if isinstance(add_group_r, BaseException):
            raise RuntimeError(f"add_group failed for chat {chat_id}") from add_group_r
        # * Clear the pending row only after the group record lands. The two
        # * calls ran in parallel before, so an add_group failure still wiped
        # * the pending row and left the owner with no retry path but re-add.
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

        # * Harvest admin identities into the member cache (fire-and-forget, best-effort).
        # * Strong reference kept in _harvest_tasks to prevent GC before completion.
        if not isinstance(admins_result, BaseException) and admins_result:
            try:
                task = asyncio.get_running_loop().create_task(
                    _harvest_admin_identities(chat_id, admins_list)
                )
                _harvest_tasks.add(task)
                task.add_done_callback(_harvest_tasks.discard)
            except RuntimeError:
                log.debug("Harvest task skipped: no running event loop.")

        # * Replay stages run back to back: bans first, then mutes. Each
        # * stage is semaphore-bounded internally via fan_out().
        applied_bans = await self._replay_bans(bot, chat_id, ban_uids)
        applied_mutes = await self._replay_mutes(bot, chat_id, mute_docs)

        lc, lt = cfg.logs
        try:
            await bot.send_message(
                lc,
                parse_logmsg.group_connected_log(
                    chat_id, chat_title, owner_id, owner_fname, chat_username
                ),
                parse_mode="MarkdownV2",
                message_thread_id=lt,
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
            # * A fetch outage above means the replay ran on an empty list:
            # * loud so the next /tcsync (or re-add) closes the gap instead
            # * of the info line above reading as a clean bill of health.
            log.error(
                "Group %d connected BLIND: enforcement replay ran without ban/mute data.",
                chat_id,
            )
        return replay_blind
