# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""``/tcstats`` command entrypoint plus shared callback guards."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.stats_flow import Stats
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update

log = get_logger(__name__)

_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 8
_RL_CB_LIMIT: int = 15


async def _require_founder_list(
    q: CallbackQuery, user_id: int | None, update: Update
) -> bool:
    """Return True when the tapper may open the Users list; alert-denies otherwise.

    Owner-or-Founder only: the list carries every cached user ID. Both checks
    are cached reads served in parallel, so the spinner clears in one round
    trip. Lookup outages fail closed with a retry alert; cancellation
    propagates via the bare gather below.
    """
    locale = await locale_for_update(update)
    if user_id is None:
        try:
            await q.answer(
                replies.perm_founder_only(locale, plain=True), show_alert=True
            )
        except Exception as exc:
            log.debug("stats users deny-answer failed: %s", exc)
        return False
    try:
        owner_r, role_r = await asyncio.gather(
            db.users_roles.is_owner(user_id),
            db.users_roles.get_effective_role(user_id),
        )
    except Exception as exc:
        log.warning("stats users access check failed for %d: %s", user_id, exc)
        try:
            await q.answer(
                t("stats.error.access_retry", locale, plain=True), show_alert=True
            )
        except Exception as answer_exc:
            log.debug("stats users retry-answer failed: %s", answer_exc)
        return False
    if owner_r is not True and role_r != "founder":
        try:
            await q.answer(
                replies.perm_founder_only(locale, plain=True), show_alert=True
            )
        except Exception as exc:
            log.debug("stats users deny-answer failed: %s", exc)
        return False
    return True


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the federation overview message."""
    msg = update.effective_message
    if msg is None:
        return
    user = update.effective_user
    text, kb = await Stats.main(
        viewer_id=user.id if user is not None else None,
        locale=await locale_for_update(update),
    )
    await safe_reply(msg, text, log_label="cmd_stats", reply_markup=kb)


def _parse_item_callback(
    q: CallbackQuery,
) -> tuple[int, int, str | None] | None:
    """Parse ``prefix:page:idx[:stable]`` item callbacks.

    Four-part callbacks carry the stable entity ID so detail views can
    reject a record shifted by a concurrent list mutation. Three-part
    callbacks from older keyboards keep working without the check.
    """
    try:
        parts = (q.data or "").split(":")
        if len(parts) == 4:
            _, page_str, idx_str, stable = parts
        else:
            _, page_str, idx_str = parts
            stable = None
        return int(page_str), int(idx_str), stable
    except ValueError:
        return None
    except IndexError:
        return None
