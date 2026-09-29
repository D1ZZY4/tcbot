# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Comprehensive user-profile view (/check command and drill-down callbacks)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.checking.checkme import _RL_CMD_LIMIT, _RL_PERIOD_S
from tcbot.modules.helper import decorators, extraction, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import ack_and_render, safe_reply
from tcbot.modules.helper.workflows.check_flow import Check
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

_RL_CHECK_CB_LIMIT: int = 20


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a comprehensive profile (identity + bans + warns + kicks + mutes + appeals)."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    user = update.effective_user
    args = parse_cmd_args(msg.text)
    # * Read-only view: a typed target always beats the quoted message,
    # * so /check shows who was asked about, never who was quoted. When
    # * the arg resolves to nobody, the reply target still stands.
    target_id, target_fname = await extraction.extract_target(
        update, args, ctx.bot, prefer_explicit=True
    )
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="check resolve-fail",
            parse_mode=None,
        )
        return

    # * Refresh cache with whatever we just resolved so future renders
    # * have a real name. Skip when the resolved name is a bare numeric ID
    # * (extract_target fell back to str(target_id) because bot.get_chat
    # * returned nothing) -- in that case we let Check.profile do the
    # * heavy lifting via _resolve_user_info (which tries get_chat_member
    # * on each connected group) and we trust its lookup result.
    if (
        target_fname
        and not target_fname.startswith("User ")
        and not target_fname.lstrip("-").isdigit()
    ):
        try:
            await db.users_cache.upsert_user(target_id, None, target_fname)
        except Exception as exc:
            log.debug("users_cache upsert failed for %d: %s", target_id, exc)

    text, kb = await Check.profile(
        ctx.bot,
        target_id,
        executor_id=user.id if user is not None else None,
        locale=locale,
    )
    await safe_reply(
        msg, text, log_label=f"check for target={target_id}", reply_markup=kb
    )


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the top-level profile summary for the checked user."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        target_id = int(q.data.split(":", 1)[1])
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    tapper = update.effective_user
    locale = await locale_for_update(update)
    await ack_and_render(
        q,
        Check.profile(
            ctx.bot,
            target_id,
            executor_id=tapper.id if tapper is not None else None,
            locale=locale,
        ),
    )


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of federation bans for the checked user."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        _, target_id_str, page_str = q.data.split(":")
        target_id = int(target_id_str)
        page = int(page_str)
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.bans_list(target_id, page, locale))


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_ban_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the full detail view for a single federation ban record."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        _, target_id_str, ban_id = q.data.split(":", 2)
        target_id = int(target_id_str)
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.ban_detail(target_id, ban_id, locale))


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_warns(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the per-group warning summary for the checked user."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        target_id = int(q.data.split(":", 1)[1])
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.warns_by_group(target_id, locale))


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_warn_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of warnings for the checked user in a specific group."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        _, target_id_str, chat_id_str, page_str = q.data.split(":")
        target_id = int(target_id_str)
        chat_id = int(chat_id_str)
        page = int(page_str)
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)
    await ack_and_render(
        q,
        Check.warns_in_group(target_id, chat_id, page, locale),
    )


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_kicks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of kick records for the checked user."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        _, target_id_str, page_str = q.data.split(":")
        target_id = int(target_id_str)
        page = int(page_str)
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.kicks_list(target_id, page, locale))


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_mutes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of mute records for the checked user."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        _, target_id_str, page_str = q.data.split(":")
        target_id = int(target_id_str)
        page = int(page_str)
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.mutes_list(target_id, page, locale))


@decorators.ratelimiter(limit=_RL_CHECK_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_check_appeals(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render a paginated list of appeal records for the checked user."""
    q = update.callback_query
    if q is None:
        return
    if q.data is None:
        await q.answer()
        return
    try:
        _, target_id_str, page_str = q.data.split(":")
        target_id = int(target_id_str)
        page = int(page_str)
    except ValueError:
        await q.answer()
        return
    except IndexError:
        await q.answer()
        return
    locale = await locale_for_update(update)
    await ack_and_render(q, Check.appeals_list(target_id, page, locale))
