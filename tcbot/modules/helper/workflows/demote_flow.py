# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralised demotion logic: manual via /tcdemote and auto-demote on ban/kick."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.error import Forbidden

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.locale import effective_locale, locale_for_user
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.dispatch import is_benign_telegram_error
from tcbot.utils.formatter import bold, mention
from tcbot.utils.i18n import Safe, t

if TYPE_CHECKING:
    from telegram import Bot, Message

log = logging.getLogger(__name__)


# ────────────────────────── Demote class ────────────────────────── #


class Demote:
    """All federation-demotion logic.

    * ``execute(trigger=None)`` runs the manual /tcdemote path.
    * ``execute(trigger="ban")`` / ``"kick"`` / ``"mute"`` runs the auto-demote
      path used by the ban, kick, and mute flows before the actual action.
    * ``redemote_before_fanout(trigger=...)`` re-checks the live role right
      before enforcement, closing the proof-collection TOCTOU window.
    """

    @staticmethod
    async def remove_role(target_id: int, target_role: str) -> bool:
        """Remove the user's role from the correct collection."""
        if target_role == "admin":
            return await db.users_roles.remove_admin(target_id)
        return await db.users_roles.remove_role(target_id)

    @classmethod
    async def execute(
        cls,
        bot: Bot,
        target_id: int,
        target_fname: str,
        target_role: str,
        executor_id: int,
        executor_fname: str,
        *,
        trigger: str | None = None,
    ) -> bool:
        """Remove the role, post a federation log, and DM the target.

        Returns True if the role was actually removed.
        """
        removed = await cls.remove_role(target_id, target_role)
        if not removed:
            # * No row in the expected collection: normally already-gone
            # * (safe to proceed), but loud so a stale-cache wrong-collection
            # * case leaves a trace instead of silent role retention.
            log.warning(
                "Demote found no %s row for target=%d; proceeding",
                target_role,
                target_id,
            )
            return False

        lc, lt = cfg.logs
        log_text = parse_logmsg.demoted(
            target_id,
            target_fname,
            target_role,
            executor_id,
            executor_fname,
            trigger=trigger,
        )

        role_label = db.users_roles.ROLE_LABEL.get(
            target_role, target_role.capitalize()
        )
        target_locale = await locale_for_user(target_id)
        if trigger is None:
            user_msg = t(
                "demote.dm.manual",
                target_locale,
                role=Safe(bold(role_label)),
                community=cfg.community_name,
                name=executor_fname,
            )
        else:
            if trigger == "ban":
                verb = "banned"
            elif trigger == "mute":
                verb = "muted"
            else:
                verb = "kicked"
            user_msg = t(
                "demote.dm.auto",
                target_locale,
                role=Safe(bold(role_label)),
                community=cfg.community_name,
                verb=verb,
            )

        log_result, dm_result = await asyncio.gather(
            bot.send_message(
                lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
            ),
            bot.send_message(target_id, user_msg, parse_mode="MarkdownV2"),
            return_exceptions=True,
        )
        if isinstance(log_result, BaseException):
            # * Error-level so a silent audit gap ships to LOG_ERRORS; the
            # * role itself was already removed, so this never blocks the caller.
            log.error("Demote log send failed for target=%d: %s", target_id, log_result)
        if isinstance(dm_result, BaseException):
            if isinstance(dm_result, Forbidden) or is_benign_telegram_error(dm_result):
                # * Expected when the target never started the bot, blocked
                # * it, or deleted the account ("Chat not found"): info-level
                # * only, mirroring the ban-flow PM handling. Error-level here
                # * would ship a no-action-needed report to LOG_ERRORS.
                log.info(
                    "Cannot DM demoted user %d "
                    "(never started the bot or blocked it): %s",
                    target_id,
                    dm_result,
                )
            else:
                log.warning(
                    "Demote DM send failed for target=%d: %s", target_id, dm_result
                )
        return True

    @classmethod
    async def redemote_before_fanout(
        cls,
        bot: Bot,
        target_id: int,
        target_fname: str,
        executor_id: int,
        executor_fname: str,
        *,
        trigger: str,
    ) -> None:
        """Best-effort TOCTOU re-demote immediately before a moderation fan-out.

        Shared by the ban/kick/mute executors, whose pre-fan-out blocks were
        identical apart from the trigger noun. The entry-point auto-demote ran
        before the reason/proof collection window, so a concurrent promotion
        during that window would otherwise survive into enforcement. Re-reads
        the live effective role and runs :meth:`execute` when the target holds
        one; every failure path logs loudly and the caller always proceeds,
        because the moderation record above already exists and enforcement is
        the priority. Entry authorization already failed closed, so this
        re-check is defense-in-depth state repair, never a gate.
        """
        try:
            pre_fanout_role = await db.users_roles.get_effective_role(target_id)
        except Exception:
            log.exception(
                "Pre-fanout role lookup failed for target %d; "
                "proceeding with %s anyway",
                target_id,
                trigger,
            )
            return
        if not pre_fanout_role:
            return
        try:
            await cls.execute(
                bot,
                target_id,
                target_fname,
                pre_fanout_role,
                executor_id,
                executor_fname,
                trigger=trigger,
            )
            log.info(
                "Re-demoted target %d (role=%s) before %s fan-out; "
                "proof-collection TOCTOU window closed",
                target_id,
                pre_fanout_role,
                trigger,
            )
        except Exception:
            log.exception(
                "Re-demote before %s fan-out failed for target %d (role=%s); "
                "proceeding anyway",
                trigger,
                target_id,
                pre_fanout_role,
            )

    @classmethod
    async def auto_demote_or_abort(
        cls,
        msg: Message,
        bot: Bot,
        target_id: int,
        target_display: str,
        target_role: str,
        executor_id: int,
        executor_fname: str,
        *,
        trigger: str,
    ) -> bool:
        """Auto-demote a role-holding target, or reply and signal abort.

        Shared by the ban/kick/mute entry handlers, whose demote-fail blocks
        were byte-identical apart from the action noun. Runs
        :meth:`execute` and returns ``True`` when the caller may proceed.
        When the demote raises, logs the failure, tells the executor to
        demote manually, and returns ``False`` so the caller ends the
        conversation without enforcing: a banned/muted/kicked user must
        never keep a federation role.
        """
        try:
            await cls.execute(
                bot,
                target_id,
                target_display,
                target_role,
                executor_id,
                executor_fname,
                trigger=trigger,
            )
        except Exception:
            log.exception(
                "Auto-demote before %s failed for target=%d role=%s",
                trigger,
                target_id,
                target_role,
            )
            chat = msg.chat
            mod_locale = await effective_locale(
                getattr(chat, "type", None), executor_id, getattr(chat, "id", 0)
            )
            await safe_reply(
                msg,
                t(
                    "demote.abort.body",
                    mod_locale,
                    user=Safe(mention(target_id, target_display)),
                    target_role=target_role,
                    action=trigger,
                ),
                log_label="auto-demote-fail",
            )
            return False
        return True
