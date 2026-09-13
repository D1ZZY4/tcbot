# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation unban command entry point: validates permissions and delegates to unban_flow."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

from telegram.ext import ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import decorators, extraction, identity, replies
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.unban_flow import execute_unban
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import mention
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

    from tcbot.database.documents import BanDoc

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 5


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Unban"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("unbanning.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("unbanning.help.commands.body", locale),
        ),
        replies.who_section(replies.perm_dev_above(locale, plain=False), locale),
        replies.where_section(replies.context_exec_or_group(locale), locale),
        (
            replies.sec_what(locale),
            t("unbanning.help.what.body", locale),
        ),
        replies.target_section(locale),
        (
            replies.sec_examples(locale),
            t("unbanning.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────── Command Unban </tcunban> ──────────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.mod_only
@decorators.log_execution
async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Lift the federation ban on a target user after identity and refusal checks.

    Speculatively pre-fetches the active ban record in parallel with identity
    classification so that ``execute_unban`` skips a redundant DB round-trip when
    the refusal check passes.
    """
    locale = await locale_for_update(update)
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return
    args = parse_cmd_args(msg.text)
    target_id, target_fname = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label="unban no-target",
            parse_mode=None,
        )
        return

    # * Classify, pre-fetch the active ban record, and run the
    # * executor-vs-target rank check in parallel. All three depend only on
    # * already-resolved IDs so there is no need to wait for them sequentially.
    # * return_exceptions=True prevents a DB failure from aborting the others.
    # * The rank check (min_role="developer") prevents a low-rank mod from
    # * unbanning a Founder or Admin -- unbanning a higher-ranked target would
    # * silently invert the role-vs-state invariant because unban also clears
    # * all active bans for the user, which is irreversible.
    ident, pre_ban, role_result = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_fname or str(target_id)),
        db.bans_db.get_active_ban(target_id),
        resolve_and_check(msg, admin.id, target_id, min_role="developer"),
        return_exceptions=True,
    )
    throw_if_cancelled((ident, pre_ban, role_result))
    if isinstance(ident, BaseException):
        log.exception("identity.classify failed in cmd_unban: %s", ident)
        return
    if isinstance(pre_ban, BaseException):
        log.error(
            "get_active_ban speculative pre-fetch failed for user=%d: %s",
            target_id,
            pre_ban,
        )
        pre_ban = None
    if isinstance(role_result, BaseException):
        log.exception("resolve_and_check failed in cmd_unban: %s", role_result)
        return
    if role_result == (None, None):
        # * resolve_and_check already replied and rejected (insufficient rank
        # * or target outranks executor); end the handler.
        return

    refusal = identity.refuse_message("unban", ident, locale)
    if refusal is not None and ident.kind not in ("admin", "developer", "tester"):
        await safe_reply(msg, refusal, log_label="unban refusal")
        return

    if refusal is not None:
        # * Staff targets are never federation-bannable, so "nothing to undo"
        # * is normally the right reply. Exception: the target was re-promoted
        # * while banned (race or manual grant); then the active ban blocks
        # * cleanup and greeting-time demote never runs (a banned-everywhere
        # * user cannot rejoin to trigger it). Demote first, then fall through
        # * to execute_unban. The speculative pre-fetch above may have failed,
        # * so re-read; a failed re-read keeps the refusal rather than
        # * demoting a staff member with no proven ban.
        target_role = role_result[1]
        ban_record = pre_ban
        if ban_record is None:
            try:
                ban_record = await db.bans_db.get_active_ban(target_id)
            except Exception:
                log.exception(
                    "unban staff re-read failed for target=%d; keeping refusal",
                    target_id,
                )
                ban_record = None
        if ban_record is None:
            await safe_reply(msg, refusal, log_label="unban refusal")
            return
        if target_role:
            try:
                await Demote.execute(
                    ctx.bot,
                    target_id,
                    target_fname or str(target_id),
                    target_role,
                    admin.id,
                    admin.first_name,
                    trigger=None,
                )
            except Exception:
                log.exception(
                    "Demote before unban-cleanup failed for target=%d role=%s",
                    target_id,
                    target_role,
                )
                await safe_reply(
                    msg,
                    t(
                        "demote.abort.body",
                        locale,
                        user=Safe(mention(target_id, target_fname or str(target_id))),
                        target_role=target_role,
                        action="unban",
                    ),
                    log_label="unban demote-fail",
                )
                return

    try:
        await execute_unban(
            update,
            ctx,
            target_id,
            target_fname or str(target_id),
            pre_ban=cast("BanDoc | None", pre_ban),
        )
    except Exception:
        # * Fail closed with a retry reply instead of crashing out silently:
        # * the re-fetch inside execute_unban is unguarded when the
        # * speculative pre-fetch above failed, so an outage would
        # * otherwise end with no operator feedback.
        log.exception("execute_unban failed for target=%s", target_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="unban DB-fail",
            parse_mode=None,
        )


# ──────────────────────────── Handlers ──────────────────────────── #

_UNBAN_CMDS = build_prefixed_filters("tcunban") | build_prefixed_filters("tcunb")

__handlers__ = [MessageHandler(_UNBAN_CMDS, cmd_unban)]
