# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Message helpers: safe edits and audit-log builders."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram.error import BadRequest

from tcbot import cfg
from tcbot import database as db
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import code, esc, link, safe_username, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import fmt_dt, utc_now

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from datetime import datetime

    from telegram import Bot, CallbackQuery, InlineKeyboardMarkup, Message

log = get_logger(__name__)

# ─────────────────────────────── Safe edits ──────────────────────────────── #

_IGNORED = {"message is not modified", "message to edit not found", "chat not found"}

_MAX_BROADCAST_PREVIEW_LEN: int = 100


def _log_edit_failure(
    level: str, label: str | None, default_msg: str, exc: BaseException
) -> None:
    """Emit an edit-failure line at ``level`` using the call-site ``label``.

    With a label the message becomes ``"<label> edit failed: %s"`` so
    migrated inline sites keep byte-identical output; without one the
    helper's own default message is used. The exception is passed
    positionally, matching the inline ``log.debug("... edit failed: %s",
    exc)`` sites this consolidates.
    """
    msg = f"{label} edit failed: %s" if label is not None else default_msg
    getattr(log, level)(msg, exc)


async def _edit_via(
    do_edit: Awaitable[object],
    *,
    log_level: str,
    log_label: str | None,
    catch_all: bool,
    default_msg: str,
) -> None:
    """Run one edit coroutine with the shared benign-error policy.

    ``BadRequest`` values naming a harmless state (not modified, not found,
    chat gone) return silently; other ``BadRequest`` values log at
    ``log_level``. Generic ``Exception`` values either propagate or log at
    ``log_level`` depending on ``catch_all``. Cancellation always propagates.
    """
    try:
        await do_edit
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        _log_edit_failure(log_level, log_label, default_msg, e)
    except Exception as exc:
        if not catch_all:
            raise
        _log_edit_failure(log_level, log_label, default_msg, exc)


async def safe_edit(
    msg: Message,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Edit a message via ``msg.edit_text``; swallow harmless not-modified errors.

    ``log_level`` selects the failure log level and ``log_label`` replaces
    the default message prefix, so migrated inline sites keep byte-identical
    output (``"<label> edit failed: %s"``). ``catch_all`` additionally
    swallows generic ``Exception`` failures at ``log_level`` instead of
    propagating them; cancellation always propagates. ``parse_mode``
    defaults to ``"MarkdownV2"``; pass ``None`` for plain text.
    """
    await _edit_via(
        msg.edit_text(text, parse_mode=parse_mode, **kwargs),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="edit failed: %s",
    )


async def safe_edit_cb(
    q: CallbackQuery,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Edit a callback-query message; swallow harmless not-modified errors.

    Use this whenever a user can re-tap a button that lands them on the same
    content (e.g. a section sub-button while already viewing that section).
    The failure parameters behave exactly as in :func:`safe_edit`.
    """
    await _edit_via(
        q.edit_message_text(text, parse_mode=parse_mode, **kwargs),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="callback edit failed: %s",
    )


async def safe_edit_message(
    bot: Bot,
    chat_id: int | None,
    message_id: int | None,
    text: str,
    *,
    log_level: str = "warning",
    log_label: str | None = None,
    catch_all: bool = False,
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Edit a message by chat/message ID via ``bot.edit_message_text``.

    Used for prompts whose chat and message IDs were stored in conversation
    state instead of a live ``Message``/``CallbackQuery`` handle. Failure
    parameters behave exactly as in :func:`safe_edit`.
    """
    await _edit_via(
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=parse_mode,
            **kwargs,
        ),
        log_level=log_level,
        log_label=log_label,
        catch_all=catch_all,
        default_msg="message edit failed: %s",
    )


async def clear_markup_cb(q: CallbackQuery) -> None:
    """Remove the inline keyboard from a callback-query message.

    Editing message text without ``reply_markup`` keeps the old buttons
    (the parameter is omitted from the API call), so ending a flow with
    only an edit would leave dead buttons behind. Call this after the
    edit; "not modified" (already removed) is swallowed like
    :func:`safe_edit_cb`.
    """
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("clear markup failed: %s", e)


async def answer_and_edit(q: CallbackQuery, text: str, **kwargs: Any) -> None:
    """Answer a callback query and edit its message in parallel.

    ``q.answer()`` and the inline edit are independent; gathering them starts
    both at once. The edit goes through :func:`safe_edit_cb`, so benign
    not-modified errors are swallowed like the raw callback sites it replaces.
    Cancellation always propagates instead of reading as success.
    """
    results = await asyncio.gather(
        q.answer(),
        safe_edit_cb(q, text, **kwargs),
        return_exceptions=True,
    )
    throw_if_cancelled(results)


async def ack_and_render(
    q: CallbackQuery, data_coro: Awaitable[tuple[str, InlineKeyboardMarkup | None]]
) -> None:
    """Acknowledge the callback query and run the data coroutine in parallel, then edit.

    ``data_coro`` must be a coroutine that returns ``(text, kb)``. Gathering
    ``q.answer()`` with the DB fetch starts both simultaneously, cutting latency
    versus the old sequential pattern. On a data coroutine failure the query is
    answered but the message is left untouched. Cancellation always propagates.
    """
    ans, result = await asyncio.gather(q.answer(), data_coro, return_exceptions=True)
    throw_if_cancelled((ans, result))
    if isinstance(result, BaseException):
        log.error("ack_and_render data fetch failed: %s", result)
        return
    text, kb = result
    await safe_edit_cb(q, text, reply_markup=kb)


async def safe_reply(
    msg: Message,
    text: str,
    *,
    log_label: str = "reply",
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Send a reply via ``msg.reply_text``; log failures at debug.

    Replaces the recurring 3-line pattern of

        try:
            await msg.reply_text(...)
        except Exception as exc:
            log.debug("...reply failed: %s", exc)

    which is duplicated across the command modules and workflows. The
    ``log_label`` parameter is the human-readable name of the call site
    (e.g. ``"mute summary fallback"``); it appears in the debug log line
    so the operator can identify the source without grepping for the
    function name.

    ``parse_mode`` defaults to ``"MarkdownV2"`` for formatted replies; pass
    ``None`` for plain-text replies (error strings, constants, community
    names) so Telegram performs no entity parsing, exactly like a bare
    ``reply_text`` call without the parameter.

    Failures are logged at ``debug`` (not ``warning``) because a failed
    ``reply_text`` is almost always benign: the user blocked the bot,
    the chat was deleted, or the message thread was closed.
    """
    try:
        await msg.reply_text(text, parse_mode=parse_mode, **kwargs)
    except Exception as exc:
        log.debug("%s reply failed: %s", log_label, exc)


# ───────────────────────── Audit-log builder ────────────────────────── #


class LogBuilder:
    """Fluent builder for Markdown audit-log messages used by the messages log builders."""

    __slots__ = ("_lines",)

    def __init__(self, title: str) -> None:
        """Start a new log message with the given title header.

        The title is escaped so callers can pass raw config or user-facing
        strings without risk of breaking the Markdown markup sent to the log channel.
        """
        self._lines: list[str] = [esc(str(title)), ""]

    def field(
        self,
        label: str,
        value: object,
        *,
        escape: bool = True,
    ) -> LogBuilder:
        """Append a `Label: value` line. The value is escaped by default."""
        v = esc(str(value)) if escape else str(value)
        self._lines.append(f"{label}: {v}")
        return self

    def code_field(self, label: str, value: object) -> LogBuilder:
        """Append a `Label: code(value)` line."""
        self._lines.append(f"{label}: {code(str(value))}")
        return self

    def mention_field(
        self, label: str, user_id: int, name: str, username: str | None = None
    ) -> LogBuilder:
        """Append a `Label: user_ref(user_id, name, username)` line."""
        self._lines.append(f"{label}: {user_ref(user_id, name, username)}")
        return self

    def link_field(self, label: str, text: str, url: str) -> LogBuilder:
        """Append a `Label: [text](url)` line."""
        self._lines.append(f"{label}: {link(text, url)}")
        return self

    def raw(self, text: str) -> LogBuilder:
        """Append a raw Markdown line. Caller is responsible for escaping user input."""
        self._lines.append(text)
        return self

    def section(self) -> LogBuilder:
        """Insert a blank separator line between sections."""
        self._lines.append("")
        return self

    def date(self, ts: datetime | None = None, *, label: str = "Date") -> LogBuilder:
        """Append a `Label: dd-mm-yyyy | HH:MM` line. Defaults to utc_now()."""
        self._lines.append(f"{label}: {fmt_dt(ts if ts is not None else utc_now())}")
        return self

    def build(self) -> str:
        """Return the assembled Markdown message."""
        return "\n".join(self._lines)

    def __str__(self) -> str:
        """Delegate to build so str(builder) works naturally."""
        return self.build()


# ──────────────────────── Moderation logs ─────────────────────── #


def ban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    ban_id: str,
    timestamp: datetime | None = None,
) -> str:
    """Return a new federation-ban audit-log message."""
    return (
        LogBuilder(f"New {cfg.community_name} Ban")
        .mention_field("Admin", admin_id, admin_fname)
        .section()
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
        .field("Reason", reason)
        .section()
        .date(timestamp, label="Commit at")
        .build()
    )


def ban_update_log(
    target_id: int,
    target_fname: str,
    new_admin_id: int,
    new_admin_fname: str,
    old_admin_id: int,
    old_admin_fname: str,
    reason: str,
    ban_id: str,
    original_ts: datetime,
) -> str:
    """Update-ban audit-log message."""
    return (
        LogBuilder(f"Update {cfg.community_name} Ban")
        .mention_field("Admin", new_admin_id, new_admin_fname)
        .mention_field("Previous Admin", old_admin_id, old_admin_fname)
        .section()
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
        .field("Reason", reason)
        .section()
        .date(original_ts, label="Commit at")
        .date(label="Update at")
        .build()
    )


def proof_caption_new(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    timestamp: datetime,
) -> str:
    """Caption used on the initial proof message."""
    return (
        LogBuilder(f"ID: {target_id}")
        .section()
        .mention_field("Admin", admin_id, admin_fname)
        .code_field("Admin ID", admin_id)
        .section()
        .date(timestamp, label="Commit at")
        .build()
    )


def proof_caption_update(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    original_ts: datetime,
    prev_proof_lnk: str | None = None,
) -> str:
    """Caption used when the proof message is updated."""
    b = (
        LogBuilder(f"ID: {target_id}")
        .section()
        .mention_field("Admin", admin_id, admin_fname)
        .code_field("Admin ID", admin_id)
    )
    if prev_proof_lnk:
        b.section().field("Previous", link("Click Here", prev_proof_lnk), escape=False)
    return (
        b.section().date(original_ts, label="Commit at").date(label="Update at").build()
    )


def mute_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    duration_str: str,
) -> str:
    """Federation-mute audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Muted")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Reason", reason)
        .field("Duration", duration_str)
        .section()
        .date()
        .build()
    )


def unmute_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
) -> str:
    """Federation-unmute audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Federation Unmute")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .section()
        .date()
        .build()
    )


def kick_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    chat_id: int,
    chat_title: str,
) -> str:
    """Kick audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Kicked")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Reason", reason)
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def resetwarns_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    removed: int,
    chat_id: int,
    chat_title: str,
) -> str:
    """Reset-warns audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Reset Warns")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Warnings cleared", str(removed))
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def warn_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    count: int,
    warn_limit: int,
    chat_id: int,
    chat_title: str,
) -> str:
    """Warn audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Warn")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Reason", reason)
        .field("Warnings", f"{count}/{warn_limit}")
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def unwarn_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    new_count: int,
    warn_limit: int,
    chat_id: int,
    chat_title: str,
) -> str:
    """Unwarn audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Unwarn")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Warnings now", f"{new_count}/{warn_limit}")
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def unban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    reason: str | None = None,
) -> str:
    """Unban audit-log message."""
    b = (
        LogBuilder(f"{cfg.community_name} Unban")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
    )
    if reason:
        b.field("Unban Reason", reason)
    return b.section().date().build()


# ──────────────────────── Appeals logs ─────────────────────── #


def appeal_received_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
) -> str:
    """Review card posted to MAIN_GROUP and the appeals destination."""
    b = LogBuilder(f"New {cfg.community_name} Appeal Request").raw(
        f"User: {user_ref(target_id, target_fname)} \\(ID: {code(str(target_id))}\\)"
    )
    b.code_field("Ban ID", ban_id)
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A")
    return (
        b.date(label="Submitted")
        .section()
        .raw("This appeal is pending review\\.")
        .build()
    )


def appeal_submitted_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
) -> str:
    """Return the initial log message to post to LOG_CHANNEL when an appeal is submitted."""
    b = (
        LogBuilder(f"New {cfg.community_name} Appeal Submitted")
        .mention_field("User", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .code_field("Ban ID", ban_id)
    )
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A")
    return b.section().date(label="Submitted").build()


def _appeal_decision_edit(
    title: str,
    decision_label: str,
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at: datetime | None = None,
) -> str:
    submitted_str = fmt_dt(submitted_at) if submitted_at else "N/A"
    b = (
        LogBuilder(title)
        .mention_field("User", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .code_field("Ban ID", ban_id)
    )
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A")
    return (
        b.section()
        # * submitted_str arrives pre-escaped from fmt_dt: pass it through
        # * instead of escaping twice like the default field() does.
        .field("Submitted", submitted_str, escape=False)
        .raw(f"{decision_label}: {user_ref(admin_id, admin_fname)}")
        .date(label=f"{decision_label} at")
        .build()
    )


def appeal_approved_edit(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at: datetime | None = None,
) -> str:
    """Edited version of the submitted log shown when an appeal is approved."""
    return _appeal_decision_edit(
        f"{cfg.community_name} Appeal Approved",
        "Approved by",
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        ban_id,
        appeal_link,
        submitted_at,
    )


def appeal_rejected_edit(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at: datetime | None = None,
) -> str:
    """Edited version of the submitted log shown when an appeal is rejected."""
    return _appeal_decision_edit(
        f"{cfg.community_name} Appeal Rejected",
        "Rejected by",
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        ban_id,
        appeal_link,
        submitted_at,
    )


def appeal_unban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
) -> str:
    """Separate unban log posted to LOG_CHANNEL when an appeal is approved."""
    return (
        LogBuilder(f"{cfg.community_name} Unban (via Appeal)")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
        .section()
        .date()
        .build()
    )


# ──────────────────────── Roles logs ─────────────────────── #


def _role_title(role: str) -> str:
    """Return the human-readable label for a role string."""
    return db.users_roles.ROLE_LABEL.get(role, role.capitalize())


def promoted(
    target_id: int,
    target_fname: str,
    role: str,
    by_id: int,
    by_fname: str,
) -> str:
    """Unified promotion audit-log for Admin / Developer / Tester.

    Single shape: the role is shown as a field below the user, not in the title.
    """
    role_label = _role_title(role)
    return (
        LogBuilder(f"New {cfg.community_name} Promoted")
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Role", role_label)
        .section()
        .mention_field("Promoted by", by_id, by_fname)
        .code_field("ID", by_id)
        .section()
        .date()
        .build()
    )


def demoted(
    target_id: int,
    target_fname: str,
    role: str,
    by_id: int,
    by_fname: str,
) -> str:
    """Unified demotion audit-log: manual demote and ban/kick auto-demote share one format."""
    role_label = _role_title(role)
    return (
        LogBuilder(f"{cfg.community_name} Demoted")
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Role removed", role_label)
        .section()
        .mention_field("Demoted by", by_id, by_fname)
        .code_field("ID", by_id)
        .section()
        .date()
        .build()
    )


def ownership_transferred(
    new_owner_id: int,
    new_owner_fname: str,
    old_owner_id: int,
    old_owner_fname: str,
) -> str:
    """Ownership transfer audit-log."""
    return (
        LogBuilder(f"{cfg.community_name} Ownership Transferred")
        .mention_field("New Owner", new_owner_id, new_owner_fname)
        .code_field("ID", new_owner_id)
        .section()
        .mention_field("Previous Owner", old_owner_id, old_owner_fname)
        .code_field("ID", old_owner_id)
        .section()
        .date()
        .build()
    )


def promote_request_log(
    user_id: int,
    user_fname: str,
    username: str | None,
    request_id: str,
) -> str:
    """Promotion-request audit-log message sent to the Founder."""
    uname_part = f"@{username}" if username else "N/A"
    return (
        LogBuilder(f"{cfg.community_name} Promotion Request")
        .mention_field("User", user_id, user_fname)
        .code_field("ID", user_id)
        .field("Username", uname_part)
        .section()
        .code_field("Request ID", request_id)
        .date()
        .build()
    )


def promote_approved_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    request_id: str,
) -> str:
    """Audit-log written when a promotion request is approved."""
    return (
        LogBuilder(f"New {cfg.community_name} Admin Promoted")
        .mention_field("Admin", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .mention_field("Promoted by", admin_id, admin_fname)
        .code_field("ID", admin_id)
        .section()
        .code_field("Request ID", request_id)
        .date()
        .build()
    )


def promote_rejected_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    request_id: str,
) -> str:
    """Audit-log written when a promotion request is rejected."""
    return (
        LogBuilder(f"{cfg.community_name} Promotion Request Rejected")
        .mention_field("User", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .mention_field("Rejected by", admin_id, admin_fname)
        .code_field("ID", admin_id)
        .section()
        .code_field("Request ID", request_id)
        .date()
        .build()
    )


# ──────────────────────── Groups logs ─────────────────────── #


def group_connected_log(
    chat_id: int,
    chat_title: str,
    owner_id: int,
    owner_fname: str,
    chat_username: str | None = None,
) -> str:
    """Return a new federation-connected-group audit-log message."""
    uname = safe_username(chat_username)
    if uname:
        group_display = link(chat_title, f"https://t.me/{uname}")
    else:
        group_display = esc(chat_title)
    return (
        LogBuilder(f"New {cfg.community_name} Connected Group")
        .raw(f"Group: {group_display}")
        .code_field("ID", chat_id)
        .section()
        .mention_field("Added by Owner", owner_id, owner_fname)
        .code_field("ID", owner_id)
        .section()
        .date()
        .build()
    )


def group_connection_rejected_log(
    chat_id: int,
    chat_title: str,
    owner_id: int,
    owner_fname: str,
) -> str:
    """Connection-rejected audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Connection Rejected")
        .raw(f"Group: {esc(chat_title)} \\(ID: {chat_id}\\)")
        .section()
        .raw(
            f"Rejected by Owner: {user_ref(owner_id, owner_fname)} \\(ID: {code(str(owner_id))}\\)"
        )
        .section()
        .date()
        .build()
    )


def group_disconnected_log(
    chat_id: int,
    chat_title: str,
    actor_id: int,
    actor_fname: str,
) -> str:
    """Group-disconnected audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Group Disconnected")
        .field("Group", chat_title)
        .code_field("ID", chat_id)
        .section()
        .mention_field("Removed by", actor_id, actor_fname)
        .code_field("ID", actor_id)
        .section()
        .date()
        .build()
    )


def group_bot_removed_log(
    chat_id: int,
    chat_title: str,
) -> str:
    """Audit-log written when the bot is removed from a connected group."""
    return (
        LogBuilder(f"{cfg.community_name} Group Removed Bot")
        .field("Group", chat_title)
        .code_field("ID", chat_id)
        .section()
        .date()
        .build()
    )


def broadcast_log(
    admin_id: int,
    admin_fname: str,
    message_preview: str,
    success: int,
    failed: int,
) -> str:
    """Broadcast audit-log message."""
    preview = message_preview[:_MAX_BROADCAST_PREVIEW_LEN]
    return (
        LogBuilder(f"{cfg.community_name} Broadcast Sent")
        .mention_field("Admin", admin_id, admin_fname)
        .field("Message", preview)
        .section()
        .field("Groups reached", str(success))
        .field("Failed groups", str(failed))
        .section()
        .date()
        .build()
    )
