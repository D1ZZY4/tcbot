# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation-wide mute executor."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram import Bot, ChatPermissions, Update

from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg, replies
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.parse_link import message_link
from tcbot.modules.helper.workflows import muting_flow as _flow
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.muting_flow.duration import fmt_duration
from tcbot.modules.helper.workflows.proof_flow import upload_proof
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    throw_if_cancelled,
)
from tcbot.utils.formatter import bold, user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from datetime import timedelta

log = get_logger(__name__)


async def _execute_mute(bot: Bot, update: Update, meta: dict[str, Any]) -> None:
    """Apply a federation-wide mute across all connected groups and edit the prompt to a summary."""
    # * Defensive .get(): _exec_mute copies whatever mute_* keys survived in
    # * user_data, so a stale or partially-cleared state must end here with
    # * no side effect instead of raising KeyError into the error handler.
    target_id = meta.get("mute_target_id")
    admin_id = meta.get("mute_admin_id")
    if not target_id or not admin_id:
        log.warning("_execute_mute called with incomplete mute state; aborting")
        return
    target_fname = meta.get("mute_target_fname") or str(target_id)
    locale = await _flow.locale_for_update(update)
    reason_text = meta.get("mute_reason") or replies.no_reason(locale, plain=True)
    duration: timedelta | None = meta.get("mute_duration")
    proof_msgs = meta.get("mute_proof_msgs")
    prompt_chat = meta.get("mute_prompt_chat")
    prompt_id = meta.get("mute_prompt_id")
    dur_str = fmt_duration(duration, locale)

    until = utc_now() + duration if duration else None
    perms = ChatPermissions(can_send_messages=False)
    duration_secs = int(duration.total_seconds()) if duration else None
    admin_fname = meta.get("mute_admin_fname", "Admin")

    # * Guard up front: without the origin chat there is no audit row to
    # * write and no summary target, so bail before any side effect.
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        log.warning("_execute_mute called without effective_chat")
        return

    # * Fail closed like the ban flow and the warn auto-ban: a groups-fetch
    # * outage aborts before anything is touched.
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("_execute_mute: active_groups failed for target=%d", target_id)
        try:
            await bot.edit_message_text(
                t(
                    "muting.note.groups_fail",
                    locale,
                    user=Safe(user_ref(target_id, target_fname)),
                ),
                chat_id=prompt_chat,
                message_id=prompt_id,
                parse_mode="MarkdownV2",
            )
        except Exception as exc:
            log.debug("_execute_mute groups-fail edit failed: %s", exc)
        return
    # * Connected groups plus primaries (single merge owner in groups_db).
    groups = db.groups_db.with_primary_groups(
        groups, (_flow.cfg.main_group, _flow.cfg.exec_group)
    )

    # * Persist the mute record before touching any group. Enforcing chats
    # * without an active_mutes row leaves an un-unmutable split brain:
    # * /tcunmute guards on get_active_mute and would refuse, forcing a
    # * manual per-group unrestrict. A failed write aborts with no group
    # * touched; the moderator retries once the database recovers.
    # * Sequential, not gather: set_active_mute is authoritative and log_mute
    # * is the audit trail. Writing the enforcement first lets us UNDO it
    # * (delete the active record) when the audit write fails, so a retry
    # * can converge to a consistent state.
    active_r: BaseException | None = None
    # * Deliberately broad: any write failure fails closed so a partially
    # * committed mute never silently continues. Cancellation is not a write
    # * failure: it re-raises so shutdown never renders as a database outage
    # * and never triggers the rollback below.
    try:
        await db.mutes_db.set_active_mute(target_id, until=until)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        active_r = exc
    log_r: BaseException | None = None
    if active_r is None:
        try:
            await db.mutes_db.log_mute(
                target_id,
                chat_id,
                reason_text,
                admin_id,
                duration_secs=duration_secs,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            log_r = exc

    if log_r is not None or active_r is not None:
        # * Undo the committed half so the next attempt starts clean.
        if active_r is None:
            try:
                await db.mutes_db.clear_active_mute(target_id)
            except asyncio.CancelledError:
                raise
            except BaseException:
                log.exception("Failed to delete active mute for %d", target_id)
        log.error(
            "_execute_mute: mute DB write failed for target=%d (log=%s active=%s)",
            target_id,
            log_r,
            active_r,
        )
        try:
            await bot.edit_message_text(
                t(
                    "muting.note.db_fail",
                    locale,
                    user=Safe(user_ref(target_id, target_fname)),
                ),
                chat_id=prompt_chat,
                message_id=prompt_id,
                parse_mode="MarkdownV2",
            )
        except Exception as exc:
            log.debug("_execute_mute DB-fail edit failed: %s", exc)
        return
    # * The entry auto-demote ran before the reason/proof window, so
    # * re-demote here to close the TOCTOU gap before the restrict fan-out.
    # * Best-effort like the entry-point demote; entry authorization already
    # * failed closed, so a lookup failure logs loudly and proceeds.
    await Demote.redemote_before_fanout(
        bot,
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        trigger="mute",
    )
    restrict_coros = [
        bot.restrict_chat_member(
            grp.get("chat_id", 0),
            target_id,
            permissions=perms,
            until_date=until,
        )
        for grp in groups
    ]
    # * Restrict enforcement and proof upload run concurrently: the summary
    # * below needs both results, but neither depends on the other, so
    # * awaiting them serially would add a full proof-channel round trip to
    # * every mute with evidence.
    proof_link: str | None = None
    if proof_msgs:
        pc, pt = _flow.cfg.proofs
        proof_caption = parse_logmsg.proof_caption_new(
            target_id, admin_id, admin_fname, utc_now()
        )
        fanout_results, upload_result = await asyncio.gather(
            fan_out(restrict_coros),
            upload_proof(bot, proof_msgs, proof_caption, pc, pt),
            return_exceptions=True,
        )
        if isinstance(fanout_results, BaseException):
            raise fanout_results
        results = fanout_results
        throw_if_cancelled((upload_result,))
        if isinstance(upload_result, BaseException):
            log.warning("Mute proof upload skipped for target=%d", target_id)
            proof_msg_id = None
        else:
            proof_msg_id = upload_result
        if proof_msg_id:
            proof_link = message_link(pc, proof_msg_id, pt)
    else:
        results = await fan_out(restrict_coros)
    failed = count_transient_errors(results)
    if failed:
        log.error(
            "Mute fan-out had %d/%d transient failures for target=%d",
            failed,
            len(groups),
            target_id,
        )

    proof_kb = keyboards.action_proof_kb(target_id, proof_link, locale)
    summary = t(
        "muting.summary.body",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        dur=Safe(bold(dur_str)),
        reason=reason_text,
        done=len(groups) - failed,
        total=len(groups),
    )

    lc, lt = _flow.cfg.logs
    log_text = parse_logmsg.mute_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        reason_text,
        dur_str,
    )

    # * The audit row and the active-mute record already landed before the
    # * fan-out above, so only Telegram deliveries remain here.
    log_send_r, edit_r = await asyncio.gather(
        bot.send_message(
            lc,
            log_text,
            parse_mode="MarkdownV2",
            message_thread_id=lt,
            reply_markup=proof_kb,
        ),
        bot.edit_message_text(
            summary,
            chat_id=prompt_chat,
            message_id=prompt_id,
            parse_mode="MarkdownV2",
            reply_markup=proof_kb,
        ),
        return_exceptions=True,
    )
    if isinstance(log_send_r, BaseException):
        log.error("Mute log send failed: %s", log_send_r)
    if isinstance(edit_r, BaseException):
        msg = update.effective_message
        if msg:
            await safe_reply(
                msg, summary, log_label="Mute summary fallback", reply_markup=proof_kb
            )
