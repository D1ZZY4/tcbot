# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Sync command handler: reconcile enforcement state across groups."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot.modules import syncing
from tcbot.modules.helper import decorators, extraction, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #

_RL_PERIOD_BULK_S: int = 300
_RL_SYNC_LIMIT: int = 2


# ─────────────────── Command Sync </tcsync> ─────────────────── #


@decorators.ratelimiter(limit=_RL_SYNC_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.mod_only
@decorators.log_execution
async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reconcile enforcement state across connected groups, bounded per run."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    args = parse_cmd_args(msg.text)

    try:
        status = await msg.reply_text(t("syncing.status.sending", locale, plain=True))
    except Exception as exc:
        log.debug("sync status reply failed: %s", exc)
        status = None

    try:
        if args:
            try:
                target_id, _ = await extraction.extract_target(update, args, ctx.bot)
            except Exception:
                log.exception("extract_target failed during sync")
                target_id = None
            if not target_id:
                raise ValueError("unresolvable")
            counts = await syncing.verify_user(ctx.bot, target_id)
            text = syncing._render_summary(
                counts,
                target=t("syncing.target.user", locale, id=target_id, plain=True),
                locale=locale,
            )
        else:
            counts = await syncing.run_ban_sync(ctx.bot)
            text = syncing._render_summary(
                counts,
                target=t("syncing.target.sweep", locale, plain=True),
                locale=locale,
            )
    except ValueError:
        text = replies.err_cannot_resolve(locale, plain=False)
    except Exception:
        log.exception("sync run failed")
        text = replies.err_groups_load_failed(locale, plain=False)

    if status is not None:
        try:
            await status.edit_text(text, parse_mode="MarkdownV2")
            return
        except Exception as exc:
            log.debug("sync status edit failed: %s", exc)
    await safe_reply(msg, text, log_label="sync summary")
