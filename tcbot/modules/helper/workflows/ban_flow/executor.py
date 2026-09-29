# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban executor: proof upload, record write, and federation fan-out."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import telegram.error
from telegram import Message

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg, replies
from tcbot.modules.helper.parse_link import message_link

# * Locale and registry resolve through the package namespace, keeping one
# * live binding for every submodule and caller.
from tcbot.modules.helper.workflows import ban_flow as _flow
from tcbot.modules.helper.workflows.ban_flow.persist import (
    _execute_ban_update,
    _execute_new_ban,
)
from tcbot.modules.helper.workflows.demote_flow import Demote
from tcbot.modules.helper.workflows.proof_flow import upload_proof
from tcbot.utils.dispatch import (
    count_transient_errors,
    fan_out,
    is_benign_telegram_error,
    throw_if_cancelled,
)
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)


async def _execute_ban(bot: Bot, msgs: list[Message], meta: dict[str, Any]) -> None:
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    locale: str | None = meta.get("ban_locale")
    reason: str = meta.get("ban_reason", replies.no_reason(locale, plain=True))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    prompt_msg_id: int = meta.get("ban_prompt_msg_id", 0)
    prompt_chat_id: int = meta.get("ban_prompt_chat_id", 0)
    target_locale = await _flow.locale_for_user(target_id)

    now = utc_now()
    proof_chat, proof_thread = cfg.proofs

    # * Pre-fetch active groups immediately so the DB round trip overlaps
    # * with the get_active_ban call and the proof-upload I/O that follows.
    _groups_task: asyncio.Task[list] = asyncio.create_task(db.groups_db.active_groups())

    try:
        existing = await db.bans_db.get_active_ban(target_id)
        is_update = existing is not None
        bot_username = bot.username or ""
        ban_id = (
            str(existing.get("ban_id", "")) if is_update else db.bans_db.make_ban_id()
        )

        if is_update:
            # * Suppress stale duplicate active bans, keeping only the record
            # * updated below. Duplicates arise from races or from a re-ban
            # * that missed the prior active record before inserting.
            extras = await db.bans_db.deactivate_extra_active_bans(
                target_id, existing.get("ban_id", "")
            )
            if extras > 0:
                log.warning(
                    "Suppressed %d duplicate active ban(s) for user %d before update",
                    extras,
                    target_id,
                )

        if is_update:
            prev_proof_msg_id = existing.get("proof_message_id")
            prev_proof_link = (
                message_link(proof_chat, prev_proof_msg_id, proof_thread)
                if prev_proof_msg_id
                else None
            )
            caption = parse_logmsg.proof_caption_update(
                target_id,
                admin_id,
                admin_fname,
                existing.get("timestamp", now),
                prev_proof_link,
            )
        else:
            prev_proof_link = None
            caption = parse_logmsg.proof_caption_new(
                target_id, admin_id, admin_fname, now
            )

        proof_msg_id = await upload_proof(bot, msgs, caption, proof_chat, proof_thread)
        proof_link = (
            message_link(proof_chat, proof_msg_id, proof_thread)
            if proof_msg_id
            else None
        )

        logs_chat, logs_thread = cfg.logs

        if is_update:
            log_msg_id, db_ok = await _execute_ban_update(
                bot,
                existing,
                meta,
                proof_msg_id,
                proof_link,
                prev_proof_link,
                logs_chat,
                logs_thread,
            )
        else:
            # * Single canonical ban_id: generated once above and reused for
            # * the DB record, the PM appeal link, and set_log_message_id.
            log_msg_id, db_ok = await _execute_new_ban(
                bot, meta, proof_msg_id, proof_link, now, logs_chat, logs_thread, ban_id
            )
    except asyncio.CancelledError:
        if not _groups_task.done():
            _groups_task.cancel()
        await asyncio.gather(_groups_task, return_exceptions=True)
        raise
    except Exception:
        if not _groups_task.done():
            _groups_task.cancel()
        await asyncio.gather(_groups_task, return_exceptions=True)
        raise

    # * Fail closed like execute_unban and the warn auto-ban path: enforcing
    # * chats without a bans record leaves an un-appealable split brain
    # * (get_active_ban returns None, so /tcunban and appeal submit cannot
    # * find it). No group is touched below; the operator retries via /tcban
    # * once the database recovers.
    if not db_ok:
        _db_fail_text = t(
            "banning.db_fail.body",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
        )
        if prompt_msg_id and prompt_chat_id:
            try:
                await bot.edit_message_text(
                    _db_fail_text,
                    chat_id=prompt_chat_id,
                    message_id=prompt_msg_id,
                    parse_mode="MarkdownV2",
                    reply_markup=None,
                )
            except Exception as exc:
                log.debug("Ban DB-fail prompt edit failed: %s", exc)
        else:
            log.warning(
                "Ban DB write failed for target=%d with no prompt to update",
                target_id,
            )
        try:
            await _groups_task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Discarding pre-fetched groups after DB failure: %s", exc)
        return

    # * set_log_message_id and the pre-fetched active_groups run together:
    # * _groups_task has been running since the top of this function.
    if log_msg_id:
        set_log_result, groups = await asyncio.gather(
            db.bans_db.set_log_message_id(ban_id, log_msg_id),
            _groups_task,
            return_exceptions=True,
        )
        if isinstance(set_log_result, BaseException):
            if isinstance(set_log_result, asyncio.CancelledError):
                raise set_log_result
            log.error(
                "set_log_message_id failed for ban_id=%s: %s", ban_id, set_log_result
            )
        # ! CRITICAL: a cancelled groups fetch must propagate, not shrink
        # ! enforcement to primaries-only mid-shutdown with a success summary.
        if isinstance(groups, asyncio.CancelledError):
            raise groups
        if isinstance(groups, BaseException):
            log.error("active_groups failed during ban of %d: %s", target_id, groups)
            groups = []
            groups_fetch_failed = True
        else:
            groups_fetch_failed = False
    else:
        try:
            groups = await _groups_task
        except Exception:
            log.exception("active_groups failed during ban of %d", target_id)
            groups = []
            groups_fetch_failed = True
        else:
            groups_fetch_failed = False

    # * Re-demote right up to the fan-out to close the TOCTOU gap left by the
    # * entry-point demote before the proof-collection window. Best-effort:
    # * the ban record above is already written, so enforcement proceeds
    # * regardless. The role read is L1/L2-cached, so this adds no DB trip.
    await Demote.redemote_before_fanout(
        bot,
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        trigger="ban",
    )
    groups = db.groups_db.with_primary_groups(groups, (cfg.main_group, cfg.exec_group))
    results = await fan_out(
        [bot.ban_chat_member(grp["chat_id"], target_id) for grp in groups]
    )
    # * Benign Telegram refusals (user not in chat, chat gone, bot demoted)
    # * are logged but excluded from the operator-facing failed count.
    failed_groups = [
        (grp, r)
        for grp, r in zip(groups, results, strict=False)
        if isinstance(r, BaseException)
    ]
    transient_groups = [
        (grp, r) for grp, r in failed_groups if not is_benign_telegram_error(r)
    ]
    failed = count_transient_errors(results)
    for grp, exc in failed_groups:
        log.warning(
            "Ban enforcement failed for user=%d in group=%s (%d): %s",
            target_id,
            grp.get("title", ""),
            grp["chat_id"],
            exc,
        )
    log.info(
        "Ban enforced: target=%d applied=%d/%d",
        target_id,
        len(groups) - failed,
        len(groups),
    )
    if failed:
        # * Error-level so the failure ships to LOG_ERRORS automatically;
        # * per-group warnings above stay console-only.
        log.error(
            "Ban fan-out had %d/%d transient failures for target=%d; "
            "see warnings above and retry manually where needed",
            failed,
            len(groups),
            target_id,
        )

    applied_line = replies.applied_summary(
        locale,
        "banning.applied",
        total=len(groups),
        failed=failed,
        transient=transient_groups,
    )
    if groups_fetch_failed:
        applied_line += t("banning.applied.scope_warn", locale)

    # * PM content, user upsert, and the prompt edit are independent: no
    # * output of one feeds another.
    _pm_text = t(
        "banning.pm.body",
        target_locale,
        community=cfg.community_name,
        reason=reason,
    )
    _pm_kb = keyboards.appeal_button_kb(bot_username, ban_id, target_locale)

    # * Summary edit, user cache, and banned-user PM fire together for the
    # * same reason: independent operations sharing one round trip.
    summary = t(
        "banning.summary.body",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        reason=reason,
        applied=Safe(applied_line),
    )
    if prompt_msg_id and prompt_chat_id:
        # * The text edit keeps the old keyboard when the parameter is
        # * omitted, so strip it explicitly: the conversation ends here and
        # * the buttons would otherwise spin forever on tap.
        edit_result, upsert_result, pm_result, markup_result = await asyncio.gather(
            bot.edit_message_text(
                summary,
                chat_id=prompt_chat_id,
                message_id=prompt_msg_id,
                parse_mode="MarkdownV2",
            ),
            db.users_cache.upsert_user(target_id, None, target_fname),
            bot.send_message(
                target_id, _pm_text, parse_mode="MarkdownV2", reply_markup=_pm_kb
            ),
            bot.edit_message_reply_markup(
                chat_id=prompt_chat_id, message_id=prompt_msg_id
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((edit_result, upsert_result, pm_result, markup_result))
        if isinstance(markup_result, BaseException):
            log.debug("Ban summary markup clear failed: %s", markup_result)
        if isinstance(edit_result, BaseException):
            log.debug("Ban summary prompt edit failed: %s", edit_result)
            # * Fall back to a fresh reply like the kick/mute executors: the
            # * moderator tapped Done and deserves the outcome even when the
            # * prompt was deleted out from under the edit.
            try:
                await bot.send_message(
                    prompt_chat_id,
                    summary,
                    parse_mode="MarkdownV2",
                )
            except Exception as exc:
                log.debug("Ban summary fallback send failed: %s", exc)
        if isinstance(upsert_result, BaseException):
            log.error("upsert_user failed for target=%d: %s", target_id, upsert_result)
    else:
        upsert_result, pm_result = await asyncio.gather(
            db.users_cache.upsert_user(target_id, None, target_fname),
            bot.send_message(
                target_id, _pm_text, parse_mode="MarkdownV2", reply_markup=_pm_kb
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((upsert_result, pm_result))
        if isinstance(upsert_result, BaseException):
            log.error(
                "upsert_user (no-prompt path) failed for target=%d: %s",
                target_id,
                upsert_result,
            )
    if isinstance(pm_result, telegram.error.Forbidden):
        log.info(
            "Cannot DM banned user %d: user has not started the bot or has blocked it",
            target_id,
        )
    elif isinstance(pm_result, BaseException):
        log.warning("Failed to send ban PM to user %d: %s", target_id, pm_result)
