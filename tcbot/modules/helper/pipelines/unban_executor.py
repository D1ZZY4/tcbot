# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Unban executor - invoked directly by the unban command."""

from __future__ import annotations

import asyncio

from tcbot import cfg
from tcbot import database as db
from tcbot.database import documents as docs
from tcbot.modules.helper import guards, identity, messages
from tcbot.modules.helper.buttons import mention_button
from tcbot.modules.helper.context import Ctx, display_name
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import reply_rich, send_log
from tcbot.modules.helper.pipelines import moderation_enforcement
from tcbot.modules.helper.pipelines.demote_actions import demote_before_unban
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


# ───────────────────────── Unban executor ───────────────────────── #


async def execute_unban(
    ctx: Ctx,
    target_id: int,
    target_fname: str,
    *,
    pre_ban: docs.BanDoc | None = None,
) -> None:
    """Lift a federation ban through the durable enforcement ledger.

    Fetches the active ban (unless ``pre_ban`` is supplied), loads the group
    list first (abort with the record intact when it cannot be loaded, so a
    retry re-drives the full scope), then revokes the ban and queues its
    per-group run in one transaction. The run is delivered immediately when
    this process can claim it; the scheduled worker finishes any target that
    fails. Replies inline if no active ban is found.

    When ``pre_ban`` is provided by the caller the function skips the ``get_active_ban``
    DB round-trip entirely, saving one network hop on the hot path. Pass ``None`` (the
    default) to let this function fetch the record itself.
    """
    msg = ctx.effective_message
    admin = ctx.effective_user
    locale = await locale_for_update(ctx)

    # ! CRITICAL: this is the last gate before a federation-wide unban. An
    # * anonymous admin has no accountable executor for the fail-closed role
    # * demote and rank checks below, so refuse instead of skipping them.
    if admin is None or identity.is_anon_admin(admin):
        log.warning(
            "Unban refused for user=%d: anonymous admin has no identity", target_id
        )
        if msg is not None:
            await reply_rich(
                msg,
                t("common.refuse.anon_admin", locale, plain=True),
                log_label="Unban anonymous-admin refusal",
                parse_mode=None,
            )
        return

    # * Use the caller-supplied record when available; fall back to a DB fetch.
    # * A failed read fails closed with a retry reply: treating an outage
    # * as "no active ban" would refuse a legitimate unban with no recourse.
    ban: docs.BanDoc | None
    if pre_ban is not None:
        ban = pre_ban
    else:
        try:
            ban = await db.bans_db.get_active_ban(target_id)
        except Exception:
            log.exception("get_active_ban failed during unban of %d", target_id)
            if msg is not None:
                await reply_rich(
                    msg,
                    t(
                        "unbanning.note.read_fail",
                        locale,
                        user=Safe(user_ref(target_id, target_fname)),
                    ),
                    log_label="Unban read-fail",
                )
            return

    if not ban:
        if msg is not None:
            await reply_rich(
                msg,
                t(
                    "unbanning.note.no_record",
                    locale,
                    user=Safe(user_ref(target_id, target_fname)),
                ),
                log_label=f"Unban no-record for user {target_id}",
            )
        return

    ban_id = ban.get("ban_id", "")

    # * Fetch groups BEFORE deactivating: if the list cannot be loaded we
    # * must abort with the ban record intact so a retry re-drives the full
    # * fan-out. Deactivating first and then discovering an empty list
    # * leaves chats unbanned-nowhere with no record to retry from (the
    # * next /tcunban would report "no active ban" while chats still ban
    # * the user). Mirrors execute_mute's groups-first fail-closed order.
    # * Costs one sequential read, but active_groups is L1-cached (30 s).
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during unban of %d", target_id)
        if msg is not None:
            await reply_rich(
                msg,
                t(
                    "unbanning.note.groups_fail",
                    locale,
                    user=Safe(user_ref(target_id, target_fname)),
                ),
                log_label="Unban groups-fail",
            )
        return

    # * Revoke the decision and queue the delivery in one transaction.
    # * The run is the authoritative work item: if the process dies during
    # * the fan-out, the scheduled worker still has every group to retry,
    # * even though the ban record is already revoked.
    # * Include primary groups not already in the connected list
    # * (single merge owner in groups_db).
    groups = db.groups_db.with_primary_groups(groups, (cfg.main_group,))
    chat_ids = [
        int(grp.get("chat_id", 0)) for grp in groups if int(grp.get("chat_id", 0) or 0)
    ]
    # * The group load is a network round trip between the command's entry
    # * checks and the revocation. A target can be promoted or granted a role
    # * in that window, so the entry-time staff verdict is not authoritative.
    # * Unban clears every federation ban, and a banned-everywhere user cannot
    # * rejoin to trigger greeting-time demote, so a staff holder left with a
    # * role after the unban would keep federation rank indefinitely.
    try:
        live_role = await db.users_roles.get_effective_role(target_id, fresh=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Live role re-read failed during unban of %d", target_id)
        live_role = None
        role_read_failed = True
    else:
        role_read_failed = False
    if role_read_failed:
        if msg is not None:
            await reply_rich(
                msg,
                t(
                    "unbanning.note.read_fail",
                    locale,
                    user=Safe(user_ref(target_id, target_fname)),
                ),
                log_label="Unban role-read-fail",
            )
        return
    # * Check the executor against the target BEFORE removing the target's
    # * role. Demoting first would erase the rank that makes the action
    # * impermissible, letting an under-ranked executor unbans a peer.
    refusal = await guards.enforcement_refusal(
        admin.id,
        target_id,
        min_role="developer",
        action="Unban",
        locale=locale,
    )
    if refusal is not None:
        if msg is not None:
            await reply_rich(
                msg,
                refusal,
                log_label="Unban rank-refusal",
                parse_mode=None,
            )
        return
    if live_role in db.users_roles.STAFF_ROLES:
        gate = await demote_before_unban(
            ctx.bot,
            target_id,
            target_fname,
            live_role,
            admin.id,
            display_name(admin),
            trigger="unban",
        )
        if not gate.may_proceed:
            if msg is not None:
                await reply_rich(
                    msg,
                    t(
                        "demote.abort.body",
                        locale,
                        user=Safe(user_ref(target_id, target_fname)),
                        target_role=live_role,
                        action="unban",
                    ),
                    log_label=f"Unban demote-{gate.value}",
                )
            return
    try:
        revoked, run_id = await db.bans_db.revoke_ban_and_queue_unban(
            target_id,
            admin.id,
            chat_ids,
            review_chat_id=cfg.main_group or None,
            review_message_id=int(ban.get("review_message_id") or 0) or None,
        )
    except asyncio.CancelledError:
        # ! CRITICAL: a cancelled revocation must propagate instead of being
        # ! reported as a DB failure; shutdown must not render as a verdict.
        raise
    except Exception:
        log.exception(
            "revoke_ban_and_queue_unban failed for user=%d; aborting unban to "
            "avoid split-brain state",
            target_id,
        )
        if msg is not None:
            await reply_rich(
                msg,
                t(
                    "unbanning.note.db_fail",
                    locale,
                    user=Safe(user_ref(target_id, target_fname)),
                ),
                log_label="Unban DB-fail",
            )
        return
    if revoked == 0 or run_id is None:
        # * Another process revoked the ban between the read and the write.
        # * Reporting "no record" is idempotent and does not claim a new
        # * change that this call did not make.
        if msg is not None:
            await reply_rich(
                msg,
                t(
                    "unbanning.note.no_record",
                    locale,
                    user=Safe(user_ref(target_id, target_fname)),
                ),
                log_label=f"Unban no-record for user {target_id}",
            )
        return

    # * The card edit was queued inside the revocation transaction, so a
    # * crash after the commit still closes the card through the worker.
    # * Deliver now on the fast path. A claim failure means the scheduled
    # * worker already owns the run, so the summary reports it as queued.
    try:
        await moderation_enforcement.deliver_queued_run(ctx.bot, run_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Unban delivery failed for run %s; it stays queued", run_id)

    try:
        report = await db.enforcement_ledger.run_report(run_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Unban run report failed for run %s", run_id)
        report = None
    settled = db.enforcement_ledger.report_settled(report)
    failed_targets = db.enforcement_ledger.failed_report_targets(report)
    delivery = db.enforcement_ledger.delivery_outcome(report, len(groups))
    total = delivery.total
    failed = delivery.failed
    landed = delivery.applied
    if not settled or delivery.pending > 0:
        # * A settled run can still have a shortfall: a requested group that
        # * left the federation leaves no target row. The queued wording is
        # * the honest one there, because the group is replayed on reconnect.
        unban_note = t(
            "unbanning.note.queued",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
        )
    elif failed:
        sample = ", ".join(
            str(target.get("title") or target.get("chat_id") or "")
            for target in failed_targets[:5]
        )
        unban_note = t(
            "unbanning.note.partial",
            locale,
            done=landed,
            total=total,
            sample=sample,
            more=" ..." if len(failed_targets) > 5 else "",
        )
    else:
        unban_note = t("unbanning.note.full", locale, total=total)

    log_text = messages.unban_log(
        target_id,
        target_fname,
        admin.id,
        display_name(admin),
        ban_id,
    )

    # * send log; reply only if we have an effective_message.
    if msg is not None:
        log_r, reply_r = await asyncio.gather(
            send_log(
                ctx.bot,
                log_text,
            ),
            reply_rich(
                msg,
                messages.replies.outcome_card(
                    t("unbanning.summary.title", locale, plain=True),
                    [
                        (
                            t("checking.ban_info.table.user", locale, plain=True),
                            mention_button(target_id, target_fname),
                        ),
                        (
                            t("common.outcome.result", locale, plain=True),
                            Safe(unban_note),
                        ),
                    ],
                    locale,
                ),
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((log_r, reply_r))
        if isinstance(reply_r, BaseException):
            log.debug("Unban reply failed for user %d: %s", target_id, reply_r)
    else:
        log_r = await send_log(
            ctx.bot,
            log_text,
        )
    if isinstance(log_r, BaseException):
        log.error("Unban log send failed for user %d: %s", target_id, log_r)


__all__ = ["execute_unban"]
