# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federated-tier authorization decorators."""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any

from telegram.ext import ContextTypes

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

from tcbot import database as db
from tcbot.modules.helper import replies
from tcbot.modules.helper.identity import ANONYMOUS_BOT_ID
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


# * `ANONYMOUS_BOT_ID` is defined in `tcbot.modules.helper.identity` as the
# * single source of truth for the GroupAnonymousBot placeholder. Re-exported
# * under the historical name `_ANON_BOT_ID` so existing in-module references
# * stay valid; new code should import from `identity` directly.
_ANON_BOT_ID = ANONYMOUS_BOT_ID

# * User-facing refusal prose lives in common.toml [refuse] (replies.py
# * owners); each auth tier below names its replies function so refusals
# * render in the viewer's locale instead of hardcoded English.
_REFUSAL_BY_LABEL: dict[str, Any] = {
    "owner_only": replies.refuse_owner_only,
    "staff_only": replies.refuse_staff_only,
    "mod_only": replies.refuse_mod_only,
    "basic_mod_only": replies.refuse_basic_mod_only,
}


def _is_anon_admin(update: Update) -> bool:
    """Return True when the effective user is the anonymous admin placeholder bot."""
    u = update.effective_user
    return u is not None and u.id == _ANON_BOT_ID


def _auth_only(*, label: str, refusal: str, min_role: str | None) -> Callable:
    """Build one of the four federated-tier authorization decorators.

    ``min_role`` names the lowest ``users_roles`` rank that passes; when it is
    ``None`` only the Founder (owner id) is authorized. ``refusal`` names the
    tier key in ``_REFUSAL_BY_LABEL`` rendered in the viewer's locale.
    """

    def _decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            """Allow the call only when the invoking user passes the tier check."""
            locale = await locale_for_update(update)
            if _is_anon_admin(update):
                if update.effective_message:
                    await safe_reply(
                        update.effective_message,
                        replies.refuse_anon_admin(locale, plain=True),
                        log_label=f"{label} anon-admin",
                        parse_mode=None,
                    )
                return None
            uid = update.effective_user.id if update.effective_user else None
            if uid:
                # * Fail closed with a retry reply on DB outage instead of
                # * letting the lookup failure propagate with no user feedback.
                # * Cancellation still propagates.
                try:
                    if min_role is None:
                        # * Served from the cached owner ID (300 s TTL) so
                        # * repeated Founder checks cost zero MongoDB round
                        # * trips on cache hits.
                        authorized = (await db.users_roles.get_owner_id()) == uid
                    else:
                        # * Served from the cached effective role (60 s TTL)
                        # * instead of two uncached reads.
                        authorized = db.users_roles.role_rank(
                            await db.users_roles.get_effective_role(uid)
                        ) >= db.users_roles.role_rank(min_role)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("%s role lookup failed for %s: %s", label, uid, exc)
                    if update.effective_message:
                        await safe_reply(
                            update.effective_message,
                            replies.refuse_role_lookup(locale, plain=True),
                            log_label=f"{label} lookup-fail",
                            parse_mode=None,
                        )
                    return None
                if authorized:
                    return await func(update, ctx)
            if update.effective_message:
                await safe_reply(
                    update.effective_message,
                    _REFUSAL_BY_LABEL[refusal](locale, plain=True),
                    log_label=f"{label} refusal",
                    parse_mode=None,
                )
            return None

        return _wrapper

    return _decorator


owner_only = _auth_only(label="owner_only", refusal="owner_only", min_role=None)
staff_only = _auth_only(label="staff_only", refusal="staff_only", min_role="admin")
mod_only = _auth_only(label="mod_only", refusal="mod_only", min_role="developer")
basic_mod_only = _auth_only(
    label="basic_mod_only",
    refusal="basic_mod_only",
    min_role="tester",
)
