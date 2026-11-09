# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralised promotion logic: role assignment and Admin promotion request flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot import database as db
from tcbot.utils.i18n import t

from .aliases import ROLE_ALIASES
from .assign import assign_admin, assign_subrole
from .request import request_admin as _request_admin_fn

if TYPE_CHECKING:
    from telegram import Bot


class Promote:
    """All federation-promotion logic.

    * ``execute(...)`` runs the full role-assignment flow used by /tcpromote
      (both the inline-role and inline-button entry points).
    * ``request_admin(...)`` enqueues a promotion request and notifies the Founder.
    * ``available_roles_for(executor_role)`` lists what roles the executor can assign.
    """

    @staticmethod
    def available_roles_for(executor_role: str) -> list[str]:
        """Return the roles an executor with the given role is allowed to assign."""
        if executor_role == "founder":
            return ["admin", "developer", "tester"]
        if executor_role == "admin":
            return ["developer", "tester"]
        return []

    @staticmethod
    async def _assign_admin(
        bot: Bot,
        admin_id: int,
        admin_fname: str,
        target_id: int,
        target_fname: str,
        current_role: str | None,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        return await assign_admin(
            bot,
            admin_id,
            admin_fname,
            target_id,
            target_fname,
            current_role,
            locale,
        )

    @staticmethod
    async def _assign_subrole(
        bot: Bot,
        admin_id: int,
        admin_fname: str,
        target_id: int,
        target_fname: str,
        current_role: str | None,
        role: str,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        return await assign_subrole(
            bot,
            admin_id,
            admin_fname,
            target_id,
            target_fname,
            current_role,
            role,
            locale,
        )

    @classmethod
    async def request_admin(
        cls,
        bot: Bot,
        admin_id: int,
        target_id: int,
        target_fname: str,
        target_username: str | None = None,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        """Enqueue an Admin promotion request and notify the Founder (DM, then fallback to log)."""
        return await _request_admin_fn(
            bot, admin_id, target_id, target_fname, target_username, locale
        )

    @classmethod
    async def execute(
        cls,
        bot: Bot,
        admin_id: int,
        admin_fname: str,
        executor_role: str,
        target_id: int,
        target_fname: str,
        current_role: str | None,
        role: str,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        """Execute a role assignment. Returns (success, reply_text).

        * Founder can directly assign Admin / Developer / Tester.
        * Admin can directly assign Developer / Tester.
        * Admin requesting Admin promotion creates a queue entry for the Founder.
        """
        if current_role == "founder":
            return False, t("admins.promote.target_is_founder", locale)

        if db.users_roles.role_rank(current_role) >= db.users_roles.role_rank(role):
            label = db.users_roles.ROLE_LABEL.get(
                current_role or "", current_role or ""
            )
            return False, t("admins.promote.holds_role", locale, role=label)

        if role == "admin":
            if executor_role == "founder":
                return await cls._assign_admin(
                    bot,
                    admin_id,
                    admin_fname,
                    target_id,
                    target_fname,
                    current_role,
                    locale,
                )
            # * Admin promoting to Admin → request for Founder to approve.
            return await cls.request_admin(
                bot, admin_id, target_id, target_fname, locale=locale
            )

        if executor_role not in ("founder", "admin"):
            return False, t("admins.promote.no_assign_perms", locale)

        return await cls._assign_subrole(
            bot,
            admin_id,
            admin_fname,
            target_id,
            target_fname,
            current_role,
            role,
            locale,
        )


__all__ = ["ROLE_ALIASES", "Promote"]
