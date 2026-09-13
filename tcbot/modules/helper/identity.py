# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Identity helpers: classify users and produce identity-aware moderation replies.

Classify a user (self / bot / Telegram / Founder / staff / regular) and produce
friendly, identity-aware replies for moderation commands.

The bot voice is professional, friendly, and formal with light dry humour. Plain text
only; no pictograph emoji, no text emoticons. One short witty line per identity is
enough; no exclamation cascades.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from tcbot import database as db
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t

if TYPE_CHECKING:
    from telegram import Bot

# ───────────────────────────── Constants ────────────────────────────── #

# * Telegram's official service / system account ID. The 777000 channel ID
# * also surfaces on forwarded service messages but never as an action target.
TELEGRAM_USER_ID = 777000

# * Telegram's internal ID for the GroupAnonymousBot placeholder, which appears
# * as the sender when a real admin posts using "send message as group" mode.
# * The true identity is unknown to the bot, so federation commands are refused.
ANONYMOUS_BOT_ID = 1087968824

IdentityKind = Literal[
    "self",  # the executor targeted themselves
    "this_bot",  # this bot is the target
    "other_bot",  # any other Telegram bot
    "telegram",  # Telegram service account
    "anon_admin",  # GroupAnonymousBot
    "founder",  # the federation Founder
    "admin",  # federation Admin (staff)
    "developer",  # federation Developer (custom role)
    "tester",  # federation Tester (custom role)
    "user",  # regular user, no federation role
]


@dataclass(frozen=True)
class Identity:
    """Resolved identity for a moderation target."""

    kind: IdentityKind
    target_id: int
    fname: str
    username: str | None = None
    is_bot: bool = False

    @property
    def role_label(self) -> str | None:
        """Public-facing role label or ``None`` for non-staff identities."""
        return (
            db.users_roles.ROLE_LABEL.get(self.kind)
            if self.kind in db.users_roles.ROLE_LABEL
            else None
        )


# ────────────────────────── Resolution ──────────────────────────── #


async def classify(
    bot: Bot,
    executor_id: int,
    target_id: int,
    target_fname: str | None = None,
    *,
    target_is_bot: bool | None = None,
) -> Identity:
    """Return an :class:`Identity` for ``target_id`` relative to ``executor_id``.

    The name-cache and role-cache reads are independent, so they run in
    parallel and the total latency is one round trip rather than two, even
    when the role is ultimately unused (self, bot, and Telegram targets
    return before any role check).

    A role-lookup failure degrades to ``kind="user"`` (fail open), so every
    moderation caller must pair this with an independent fail-closed role
    read: ``resolve_and_check`` for ban, kick, mute, warn, and unban entries,
    or a guarded ``get_effective_role`` fetch for promote and demote. The
    paired read rejects the action on lookup failure, which keeps the
    degraded ``"user"`` kind from becoming an authorization bypass.
    Cancellation always propagates; only ordinary lookup failures degrade.
    """
    # * Both are independent cached reads; run in parallel.
    # * return_exceptions=True prevents a transient DB error from propagating
    # * to every moderation command that calls classify().
    mention_data, role_result = await asyncio.gather(
        db.users_cache.get_user_mention_data(target_id),
        db.users_roles.get_effective_role(target_id),
        return_exceptions=True,
    )
    throw_if_cancelled((mention_data, role_result))
    (cached_fname, target_username) = (
        mention_data if not isinstance(mention_data, BaseException) else (None, None)
    )
    role = role_result if not isinstance(role_result, BaseException) else None
    # * Override fname when it looks like a fallback: missing, the legacy
    # * "User <id>" format, or a bare numeric string returned by _best_name().
    if (
        not target_fname
        or target_fname.startswith("User ")
        or target_fname.lstrip("-").isdigit()
    ):
        target_fname = cached_fname
    # * Guard: cached_fname is None when the DB call itself raised an exception.
    if not target_fname:
        target_fname = str(target_id)

    if target_id == executor_id:
        return Identity("self", target_id, target_fname, target_username, is_bot=False)
    if target_id == bot.id:
        return Identity(
            "this_bot", target_id, target_fname, target_username, is_bot=True
        )
    if target_id == TELEGRAM_USER_ID:
        return Identity(
            "telegram", target_id, target_fname, target_username, is_bot=False
        )
    if target_id == ANONYMOUS_BOT_ID:
        return Identity(
            "anon_admin", target_id, target_fname, target_username, is_bot=True
        )
    if target_is_bot:
        return Identity(
            "other_bot", target_id, target_fname, target_username, is_bot=True
        )

    if role == "founder":
        return Identity("founder", target_id, target_fname, target_username)
    if role == "admin":
        return Identity("admin", target_id, target_fname, target_username)
    if role == "developer":
        return Identity("developer", target_id, target_fname, target_username)
    if role == "tester":
        return Identity("tester", target_id, target_fname, target_username)
    return Identity("user", target_id, target_fname, target_username)


def _line(ident: Identity) -> str:
    """Build the canonical ``mention - <id>`` chunk for an identity."""
    return user_ref(ident.target_id, ident.fname, ident.username)


# ────────────────── Per-action witty refusals ───────────────────── #
# * Each action/kind pair lives in identity.toml [refuse.<action>].
# * ``user`` and lower-rank staff are never returned here; those go
# * through the normal moderation flow. The reply is one short
# * professional-but-friendly line.
# * Staff roles (admin/developer/tester) are intentionally absent from the
# * ban/kick/mute tables: those entries auto-demote the target via
# * Demote.execute before enforcing, so refusing here would make the
# * documented auto-demote unreachable.


# * Which (action, kind) pairs refuse, mirroring the old per-action tables.
# * Structure only (the prose lives in identity.toml); ``user`` and
# * lower-rank staff are never listed here and flow through normally.
_REFUSE_KEYS: dict[str, frozenset[IdentityKind]] = {
    "ban": frozenset({"self", "this_bot", "telegram", "anon_admin", "founder"}),
    "kick": frozenset({"self", "this_bot", "telegram", "anon_admin", "founder"}),
    "mute": frozenset({"self", "this_bot", "telegram", "anon_admin", "founder"}),
    "warn": frozenset(
        {"self", "this_bot", "telegram", "other_bot", "anon_admin", "founder"}
    ),
    "unban": frozenset(
        {
            "self",
            "this_bot",
            "telegram",
            "anon_admin",
            "founder",
            "admin",
            "developer",
            "tester",
        }
    ),
    "unmute": frozenset(
        {"self", "this_bot", "telegram", "other_bot", "anon_admin", "founder"}
    ),
    "promote": frozenset(
        {
            "self",
            "this_bot",
            "telegram",
            "other_bot",
            "anon_admin",
            "founder",
            "admin",
        }
    ),
    "demote": frozenset(
        {"self", "this_bot", "telegram", "other_bot", "anon_admin", "founder"}
    ),
    "transfer": frozenset({"self", "this_bot", "telegram", "other_bot", "anon_admin"}),
    "unwarn": frozenset(
        {"self", "this_bot", "telegram", "other_bot", "anon_admin", "founder"}
    ),
    "resetwarns": frozenset(
        {"self", "this_bot", "telegram", "other_bot", "anon_admin", "founder"}
    ),
}


def refuse_message(
    action: str, ident: Identity, locale: str | None = None
) -> str | None:
    """Return a witty refusal line for ``action`` against ``ident``, or ``None``.

    ``None`` means the action is allowed against this identity and the caller
    should proceed with the normal moderation flow.
    """
    if ident.kind not in _REFUSE_KEYS.get(action, frozenset()):
        return None
    return t(f"identity.refuse.{action}.{ident.kind}", locale, line=Safe(_line(ident)))


# ─────────── Recognition notes (read-only views) ──────────────── #
# * Single owner for "who is this?" copy on read-only surfaces such as
# * /check: moderation entries use refuse_message/staff_notice instead, so
# * no caller builds these lines inline. Staff and Founder are absent on
# * purpose: the profile Role line already labels them.
_PROFILE_NOTE_KINDS: frozenset[IdentityKind] = frozenset(
    {"this_bot", "self", "telegram", "anon_admin"}
)


def profile_note(ident: Identity, locale: str | None = None) -> str | None:
    """Return a recognition note for special identities, or ``None``.

    ``None`` means the identity needs no note (regular users, staff, and
    Founder: staff and Founder are already labeled by the profile Role
    line, so a note would only restate it).
    """
    if ident.kind not in _PROFILE_NOTE_KINDS:
        return None
    return t(f"identity.note.{ident.kind}", locale)


# ─────────────── Staff heads-up (action proceeds) ───────────────── #
# * For warn / unwarn / unmute / resetwarns on staff targets, the action
# * proceeds but we surface a short heads-up so the executor knows the
# * target is staff; useful when an Admin is cleaning up a stale record.


def staff_notice(
    action: str,
    ident: Identity,
    community_name: str,
    locale: str | None = None,
) -> str | None:
    """Return a heads-up line when acting on staff, or ``None`` otherwise."""
    if ident.kind not in ("admin", "developer", "tester"):
        return None
    return t(
        "identity.staff.notice",
        locale,
        line=Safe(_line(ident)),
        community=community_name,
        role=ident.role_label or ident.kind,
        action=action,
    )
