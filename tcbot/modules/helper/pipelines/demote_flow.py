# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralised demotion logic: manual via /tcdemote and demote before ban/kick."""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import TYPE_CHECKING

from telegram.error import Forbidden

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import messages
from tcbot.modules.helper.locale import locale_for_user
from tcbot.modules.helper.messages import send_log
from tcbot.utils.dispatch import is_benign_telegram_error, throw_if_cancelled
from tcbot.utils.formatter import bold
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)


class UnbanGate(Enum):
    """Outcome of the demote-before-unban gate.

    ``PROCEED`` lets the unban run. The blocking states keep a staff holder
    from keeping rank after the ban lifts.
    """

    PROCEED = "proceed"
    DEMOTE_FAILED = "demote_failed"
    ROLE_SURVIVED = "role_survived"

    @property
    def may_proceed(self) -> bool:
        """True when the caller may continue with the unban."""
        return self is UnbanGate.PROCEED


# ────────────────────────── Demote class ────────────────────────── #


class Demote:
    """All federation-demotion logic.

    * ``execute(trigger=None)`` runs the manual /tcdemote path.
    * ``execute(trigger="ban")`` / ``"kick"`` / ``"mute"`` runs the
      demote-before-enforcement path used by the ban, kick, and mute flows
      before the actual action.
    * ``execute(trigger="warn")`` runs the warn-threshold exemption, which
      demotes a staff holder instead of banning them.

    The two enforcement gates around it differ on purpose:
    :func:`demote_before_enforcement` proceeds after a failure, and
    :func:`demote_before_unban` blocks.
    """

    @staticmethod
    async def remove_role(target_id: int, target_role: str) -> bool:
        """Remove the user's role from every role collection.

        Always clears both ``tc_admins`` and ``tc_roles``: a stale row in
        the other collection would otherwise resurrect privilege on the
        next demote (effective role prefers Admin, hiding the stale row
        until ``remove_admin`` reveals it). True when any row was cleared.
        """
        cleared_admin, cleared_role = await asyncio.gather(
            db.users_roles.remove_admin(target_id),
            db.users_roles.remove_role(target_id),
        )
        return cleared_admin or cleared_role

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

        Returns True when a role row was actually removed. A role that was
        already gone returns False without raising: the caller decides
        whether that is a no-op (the manual demote reports it) or a
        split-brain it must re-check (the unban gate does).

        ``trigger`` selects the DM wording only. The enforcement path is
        best effort by design: the moderation record already exists when
        it runs, so a failure must never block the action. The unban path
        enforces the fail-closed rule itself in :func:`demote_before_unban`.
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

        log_text = messages.demoted(
            target_id,
            target_fname,
            target_role,
            executor_id,
            executor_fname,
        )

        role_label = db.users_roles.role_label(target_role)
        target_locale = await locale_for_user(target_id)
        if trigger is None:
            user_msg = t(
                "demote.dm.manual",
                target_locale,
                role=Safe(bold(role_label)),
                community=cfg.community_name,
                name=executor_fname,
            )
        elif trigger == "warn":
            # * The warn threshold demotes a staff holder instead of
            # * banning them, so the wording must not claim a ban that
            # * never happened.
            user_msg = t(
                "demote.dm.warn",
                target_locale,
                role=Safe(bold(role_label)),
                community=cfg.community_name,
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
            send_log(
                bot,
                log_text,
            ),
            bot.send_message(target_id, user_msg, parse_mode="MarkdownV2"),
            return_exceptions=True,
        )
        throw_if_cancelled((log_result, dm_result))
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


# ───────────────────────── Shared demote gates ──────────────────────── #


async def demote_before_enforcement(
    bot: Bot,
    target_id: int,
    target_fname: str,
    *,
    trigger: str,
    executor_id: int = 0,
    executor_fname: str = "",
) -> str | None:
    """Best-effort demote of a role-holding target before enforcement.

    Returns the demoted role, or None when the target held no role or the
    demote failed. Never raises: the moderation record already exists and
    enforcement is the side effect, so a lookup or demote failure is logged
    loudly and the target is treated as non-staff.

    Single owner for the ban, kick, mute, and join-enforcement pre-fanout
    demote, so the rule cannot drift between the four copies that used to
    carry it. ``executor_id`` stays 0 for join enforcement, where no
    moderator triggered the action.
    """
    try:
        target_role = await db.users_roles.get_effective_role(target_id, fresh=True)
    except Exception:
        log.exception(
            "Pre-%s role lookup failed for target %d; proceeding anyway",
            trigger,
            target_id,
        )
        return None
    if not target_role:
        return None
    try:
        await Demote.execute(
            bot,
            target_id,
            target_fname or str(target_id),
            target_role,
            executor_id,
            executor_fname,
            trigger=trigger,
        )
    except Exception:
        log.exception(
            "Demote before %s fan-out failed for target %d (role=%s); proceeding anyway",
            trigger,
            target_id,
            target_role,
        )
        return None
    log.info(
        "Demoted target %d (role=%s) before %s fan-out; "
        "proof-collection TOCTOU window closed",
        target_id,
        target_role,
        trigger,
    )
    return target_role


async def demote_before_unban(
    bot: Bot,
    target_id: int,
    target_fname: str,
    target_role: str,
    executor_id: int,
    executor_fname: str,
) -> UnbanGate:
    """Remove a federation role before an unban; fail closed on failure.

    Returns :attr:`UnbanGate.PROCEED` when the caller may unban. Unlike
    :func:`demote_before_enforcement` this gate fails closed: a demote that
    raises, or a demote that cleared no row while the role still resolves,
    blocks the unban so a staff holder never keeps rank after the ban
    lifts. Single owner for the /tcunban and appeal-approve paths.
    """
    try:
        removed = await Demote.execute(
            bot,
            target_id,
            target_fname,
            target_role,
            executor_id,
            executor_fname,
            trigger=None,
        )
    except Exception:
        log.exception(
            "Demote before unban failed for target=%d role=%s",
            target_id,
            target_role,
        )
        return UnbanGate.DEMOTE_FAILED
    if removed:
        return UnbanGate.PROCEED
    # * No row was cleared: normally the role is already gone, so the unban
    # * may proceed. A split-brain where the role still resolves must not.
    try:
        live_role = await db.users_roles.get_effective_role(target_id, fresh=True)
    except Exception:
        log.exception(
            "Live role re-read failed after no-op demote for target=%d", target_id
        )
        live_role = target_role
    if live_role in db.users_roles.STAFF_ROLES:
        log.warning(
            "Unban blocked: demote was a no-op but target=%d still holds role=%s",
            target_id,
            live_role,
        )
        return UnbanGate.ROLE_SURVIVED
    return UnbanGate.PROCEED
