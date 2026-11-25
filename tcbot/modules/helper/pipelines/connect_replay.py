# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Enforcement replay performed when a group joins the federation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pyrogram import Client
from pyrogram.enums import ChatMembersFilter
from pyrogram.types import ChatPermissions

from tcbot import database as db
from tcbot.modules.helper import messages
from tcbot.modules.helper.messages import send_log
from tcbot.modules.helper.pipelines.connect_common import (
    harvest_admin_identities,
    harvest_tasks,
)
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    gather_bounded,
    is_benign_telegram_error,
    throw_if_cancelled,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from tcbot.database.documents import ActiveMuteDoc

log = get_logger(__name__)


async def _chat_admins(bot: Client, chat_id: int) -> list:
    """Collect the chat's administrators from Kurigram's async generator."""
    return [
        member
        async for member in bot.get_chat_members(
            chat_id, filter=ChatMembersFilter.ADMINISTRATORS
        )
    ]


_REPLAY_CAP: int = 500
# * Telegram admits 20 requests a minute per group, so a long ban or mute
# * list cannot be enforced in one pass. The replay runs until this budget
# * is spent; the unapplied remainder is queued as durable enforcement work.
_REPLAY_BUDGET_S: float = 20.0
# * Enforcement actions issued per round. The deadline is checked between
# * rounds, so the round size bounds how long the budget can be overrun.
_REPLAY_ROUND: int = 8
# * The queue write is the only durability boundary for the unapplied
# * remainder. A transient failure is worth a short retry; exhausting it
# * must surface the failure instead of leaving an active group silently
# * missing federation decisions.
_REPLAY_QUEUE_ATTEMPTS: int = 3
_REPLAY_QUEUE_BACKOFF: float = 0.2


async def _protected_user_ids(user_ids: list[int]) -> set[int]:
    """Return the users who hold the protected Owner role at replay time.

    A stored decision can outlive the role its target held when it was filed.
    Replaying it into a new group must not ban or mute a now-protected Owner.
    A failed role read refuses the connect, matching the decision-read guard.
    """
    ids = sorted({uid for uid in user_ids if uid > 0})
    if not ids:
        return set()
    results = await gather_bounded(
        [db.users_roles.is_owner(uid, fresh=True) for uid in ids],
        max_concurrent=10,
    )
    throw_if_cancelled(results)
    protected: set[int] = set()
    for uid, result in zip(ids, results, strict=True):
        if isinstance(result, BaseException):
            raise RuntimeError(
                f"cannot verify protected role for user {uid} during connect replay"
            ) from result
        if result:
            protected.add(uid)
    return protected


class ConnectionReplayMixin:
    """Replay active moderation decisions into a newly connected group."""

    @staticmethod
    async def _replay_bans(
        bot: Client, chat_id: int, ban_uids: list[int], deadline: float
    ) -> tuple[int, list[int]]:
        """Fan out every active federation ban into the new group."""
        pending = list(ban_uids)
        applied = 0
        failed: list[int] = []
        while pending and monotonic() < deadline:
            chunk = pending[:_REPLAY_ROUND]
            results = await fan_out(
                [bot.ban_chat_member(chat_id, uid) for uid in chunk]
            )
            applied += len(results) - count_transient_errors(results)
            failed.extend(
                uid
                for uid, result in zip(chunk, results, strict=True)
                if isinstance(result, BaseException)
                and not is_benign_telegram_error(result)
            )
            pending = pending[len(chunk) :]
        return applied, pending + failed

    @staticmethod
    async def _replay_mutes(
        bot: Client, chat_id: int, mute_docs: list[ActiveMuteDoc], deadline: float
    ) -> tuple[int, list[ActiveMuteDoc]]:
        """Fan out every active federation mute into the new group."""
        _mute_perms = ChatPermissions(can_send_messages=False)
        pending = list(mute_docs)
        applied = 0
        failed: list[ActiveMuteDoc] = []
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
            failed.extend(
                doc
                for doc, result in zip(chunk, results, strict=True)
                if isinstance(result, BaseException)
                and not is_benign_telegram_error(result)
            )
            pending = pending[len(chunk) :]
        return applied, pending + failed

    async def complete_join(
        self,
        chat_id: int,
        chat_title: str,
        owner_id: int,
        owner_fname: str,
        bot: Client,
    ) -> bool:
        """Connect the group and replay active bans and mutes. Returns blind flag."""
        chat_result, ban_uids, mute_docs, admins_result = await asyncio.gather(
            asyncio.wait_for(bot.get_chat(chat_id), timeout=TELEGRAM_LOOKUP_TIMEOUT),
            db.bans_db.active_ban_user_ids(),
            db.mutes_db.active_mute_docs(),
            asyncio.wait_for(
                _chat_admins(bot, chat_id), timeout=TELEGRAM_LOOKUP_TIMEOUT
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((chat_result, ban_uids, mute_docs, admins_result))
        # ! CRITICAL: never activate a group while the decision store is
        # ! unreadable. An empty list here means "unknown", not "no bans", and
        # ! activating would leave already-present members unrestricted with no
        # ! durable run to repair them. All callers surface this failure.
        if isinstance(ban_uids, BaseException):
            raise RuntimeError(
                f"cannot read federation decisions for chat {chat_id}"
            ) from ban_uids
        if isinstance(mute_docs, BaseException):
            raise RuntimeError(
                f"cannot read federation decisions for chat {chat_id}"
            ) from mute_docs
        protected = await _protected_user_ids(
            list(ban_uids) + [int(doc.get("user_id", 0)) for doc in mute_docs]
        )
        if protected:
            log.warning(
                "Connect replay skips %d protected Owner decision(s) for chat %d",
                len(protected),
                chat_id,
            )
            ban_uids = [uid for uid in ban_uids if uid not in protected]
            mute_docs = [
                doc for doc in mute_docs if int(doc.get("user_id", 0)) not in protected
            ]
        add_group_r = await db.groups_db.add_group(chat_id, chat_title, owner_id)
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
        admins_list = (
            list(admins_result) if not isinstance(admins_result, BaseException) else []
        )
        replay_blind = False
        deadline = monotonic() + _REPLAY_BUDGET_S
        pending_ban_uids: list[int] = []
        pending_mute_docs: list[ActiveMuteDoc] = []
        if len(ban_uids) > _REPLAY_CAP:
            log.warning(
                "Connect replay truncated to %d/%d bans for chat %d",
                _REPLAY_CAP,
                len(ban_uids),
                chat_id,
            )
            pending_ban_uids = ban_uids[_REPLAY_CAP:]
            ban_uids = ban_uids[:_REPLAY_CAP]
            replay_blind = True
        if len(mute_docs) > _REPLAY_CAP:
            log.warning(
                "Connect replay truncated to %d/%d mutes for chat %d",
                _REPLAY_CAP,
                len(mute_docs),
                chat_id,
            )
            pending_mute_docs = mute_docs[_REPLAY_CAP:]
            mute_docs = mute_docs[:_REPLAY_CAP]
            replay_blind = True
        if not isinstance(admins_result, BaseException) and admins_result:
            harvest_tasks.spawn(harvest_admin_identities(chat_id, admins_list))
        applied_bans, unapplied_bans = await self._replay_bans(
            bot, chat_id, ban_uids, deadline
        )
        applied_mutes, unapplied_mutes = await self._replay_mutes(
            bot, chat_id, mute_docs, deadline
        )
        pending_ban_uids.extend(unapplied_bans)
        pending_mute_docs.extend(unapplied_mutes)
        pending_user_ids = list(
            dict.fromkeys(
                pending_ban_uids
                + [int(doc.get("user_id", 0)) for doc in pending_mute_docs]
            )
        )
        if pending_user_ids:
            queued = 0
            for attempt in range(_REPLAY_QUEUE_ATTEMPTS):
                try:
                    queued = await db.enforcement_db.queue_connect_replay(
                        chat_id, pending_user_ids, owner_id
                    )
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if attempt == _REPLAY_QUEUE_ATTEMPTS - 1:
                        # ! CRITICAL: the group is already active, so a lost
                        # queue write leaves active decisions unenforced with
                        # no durable record. Surface the failure and undo the
                        # activation so a retry replays from the start.
                        log.exception(
                            "Connect replay queue failed for chat %d after %d "
                            "attempt(s); %d pending user(s): %s",
                            chat_id,
                            attempt + 1,
                            len(pending_user_ids),
                            pending_user_ids,
                        )
                        try:
                            await db.groups_db.deactivate_group(chat_id)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            log.exception(
                                "Rollback of failed connection for chat %d failed",
                                chat_id,
                            )
                        raise RuntimeError(
                            f"connect replay queue failed for chat {chat_id} "
                            f"with {len(pending_user_ids)} pending user(s)"
                        ) from exc
                    await asyncio.sleep(_REPLAY_QUEUE_BACKOFF * (attempt + 1))
            if queued:
                log.warning(
                    "Connect replay for chat %d left %d decision(s); "
                    "queued %d enforcement run(s) to finish them.",
                    chat_id,
                    len(pending_user_ids),
                    queued,
                )
            replay_blind = True
        if pending_ban_uids or pending_mute_docs:
            log.warning(
                "Connect replay for chat %d left %d ban(s) and %d mute(s) unapplied.",
                chat_id,
                len(pending_ban_uids),
                len(pending_mute_docs),
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
                "Group %d connected with an incomplete enforcement replay.", chat_id
            )
        return replay_blind
