# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation unban command entry point: validates permissions and delegates to unban_actions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from tcbot import database as db
from tcbot.modules.helper import decorators, extraction, guards, identity
from tcbot.modules.helper.context import Ctx, chat_id_of, display_name
from tcbot.modules.helper.guards import resolve_and_check
from tcbot.modules.helper.handlers import MessageHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich
from tcbot.modules.helper.pipelines.demote_actions import demote_before_unban
from tcbot.modules.helper.pipelines.unban_actions import execute_unban
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from tcbot.database.documents import BanDoc

log = get_logger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Unban"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("unbanning.help.overview", locale),
        commands=t("unbanning.help.commands.body", locale),
        who=replies.perm_dev_above(locale, plain=False),
        where=replies.context_bot_or_group(locale),
        what=t("unbanning.help.what.body", locale),
        examples=t("unbanning.help.examples.body", locale),
    )


__help__: replies.HelpEntry = get_help()

# ────────────────────── Staff cleanup resolution ───────────────────── #


def _cleanup_role(target_role: str | None, ident: identity.Identity) -> str | None:
    """Return the staff role the unban must demote, whichever read saw it.

    The classification and the rank check are separate fresh reads, so a
    promotion between them makes one of them staff and the other role-less.
    Either match proves a staff holder, and the fail-closed demote must run
    for that role instead of being skipped because the rank check won.
    """
    if target_role in db.users_roles.STAFF_ROLES:
        return target_role
    if ident.kind in db.users_roles.STAFF_ROLES:
        return ident.kind
    return None


# ──────────────────── Command Unban </tcunban> ──────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.mod_only
@decorators.log_execution
async def cmd_unban(ctx: Ctx) -> None:
    """Lift the federation ban on a target user after identity and refusal checks.

    Speculatively pre-fetches the active ban record in parallel with identity
    classification so that ``execute_unban`` skips a redundant DB round-trip when
    the refusal check passes.
    """
    locale = await locale_for_update(ctx)
    msg = ctx.effective_message
    admin = ctx.effective_user
    if msg is None or admin is None:
        return
    if not await guards.require_federation_origin(
        msg,
        chat_id=chat_id_of(msg.chat),
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=True,
        log_label="cmd_unban origin",
    ):
        return
    args = parse_cmd_args(msg.text)
    target_id, target_fname = await extraction.extract_target(ctx, args, ctx.bot)
    if not target_id:
        await reply_rich(
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
    # * unbanning an Owner or Admin -- unbanning a higher-ranked target would
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
        # * gather(return_exceptions=True) captured this as a value, so there
        # * is no active exception for log.exception to report.
        log.error("identity.classify failed in cmd_unban: %s", ident, exc_info=ident)
        await reply_rich(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="unban classify-fail",
            parse_mode=None,
        )
        return
    if isinstance(pre_ban, BaseException):
        log.error(
            "get_active_ban speculative pre-fetch failed for user=%d: %s",
            target_id,
            pre_ban,
        )
        pre_ban = None
    if isinstance(role_result, BaseException):
        log.error(
            "resolve_and_check failed in cmd_unban: %s",
            role_result,
            exc_info=role_result,
        )
        await reply_rich(
            msg,
            replies.err_role_verify(locale, plain=True),
            log_label="unban rank-check-fail",
            parse_mode=None,
        )
        return
    if role_result == (None, None):
        # * resolve_and_check already replied and rejected (insufficient rank
        # * or target outranks executor); end the handler.
        return

    staff_roles = db.users_roles.STAFF_ROLES
    refusal = identity.refuse_message("unban", ident, locale)
    # * Hard identity refusals (self, bot, telegram, anon_admin, owner)
    # * always block, regardless of federation role.
    if refusal is not None and ident.kind not in staff_roles:
        await reply_rich(msg, refusal, log_label="unban refusal")
        return

    # * Federation staff-ness comes from the fail-closed role read
    # * (resolve_and_check), not from identity.classify. Keying the staff
    # * branch off the classification kind would skip the
    # * demote-before-unban cleanup below.
    target_role = role_result[1] if isinstance(role_result, tuple) else None
    is_staff_target = target_role in staff_roles or (
        refusal is not None and ident.kind in staff_roles
    )

    if is_staff_target:
        # * Staff targets are never federation-bannable, so "nothing to undo"
        # * is normally the right reply. Exception: the target was re-promoted
        # * while banned (race or manual grant); then the active ban blocks
        # * cleanup and greeting-time demote never runs (a banned-everywhere
        # * user cannot rejoin to trigger it). Demote first, then fall through
        # * to execute_unban. The speculative pre-fetch above may have failed,
        # * so re-read; a failed re-read keeps the refusal rather than
        # * demoting a staff member with no proven ban.
        # * Reconstruct a refusal when classify degraded (refusal is None) so
        # * the "nothing to undo" reply below stays a real message. The
        # * classification and the role read are two separate fresh reads,
        # * so they can disagree when the target is promoted between them.
        if refusal is None and target_role in staff_roles:
            refusal = identity.refuse_role(
                "unban",
                target_role,
                target_id,
                target_fname or str(target_id),
                locale,
            )
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
            await reply_rich(msg, refusal or "", log_label="unban refusal")
            return
        # * The classification and the role read are two separate fresh
        # * reads. When they disagree on a promotion, either one proves a
        # * staff holder, so the fail-closed demote must not be skipped just
        # * because the rank check saw the target as role-less.
        effective_staff_role = _cleanup_role(target_role, ident)
        if effective_staff_role is not None:
            # * Fail closed: the shared gate blocks the unban when the demote
            # * raised, or when it cleared no row while the role still
            # * resolves (a split-brain). A staff holder must never keep
            # * rank after the ban lifts.
            gate = await demote_before_unban(
                ctx.bot,
                target_id,
                target_fname or str(target_id),
                effective_staff_role,
                admin.id,
                display_name(admin),
            )
            if not gate.may_proceed:
                await reply_rich(
                    msg,
                    t(
                        "demote.abort.body",
                        locale,
                        user=Safe(user_ref(target_id, target_fname or str(target_id))),
                        target_role=effective_staff_role,
                        action="unban",
                    ),
                    log_label=f"unban demote-{gate.value}",
                )
                return

    try:
        await execute_unban(
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
        await reply_rich(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="unban DB-fail",
            parse_mode=None,
        )


# ──────────────────────────── Handlers ──────────────────────────── #

_UNBAN_CMDS = build_prefixed_filters("tcunban") | build_prefixed_filters("tcunb")

__handlers__ = [MessageHandler(_UNBAN_CMDS, cmd_unban)]
