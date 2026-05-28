# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Identity helpers — classify a user (self / bot / Telegram / Founder / staff / regular)
and produce friendly, identity-aware replies for moderation commands.

The bot voice is professional + friendly with light, dry humour. Plain text only —
text emoticons like ``:)``, ``:v``, ``:')`` are allowed sparingly; pictograph emoji
are not. One short witty line per identity is enough — no exclamation cascades.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from telegram import Bot

from tcbot import database as db
from tcbot.database.users_db import ROLE_LABEL, get_effective_role
from tcbot.modules.helper.formatter import code, mention

# ───────────────────────────── Constants ────────────────────────────── #

# * Telegram's official service / system account ID. The 777000 channel ID
# * also surfaces on forwarded service messages but never as an action target.
TELEGRAM_USER_ID = 777000

IdentityKind = Literal[
    "self",  # the executor targeted themselves
    "this_bot",  # this bot is the target
    "other_bot",  # any other Telegram bot
    "telegram",  # Telegram service account
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
    is_bot: bool = False

    @property
    def role_label(self) -> str | None:
        """Public-facing role label or ``None`` for non-staff identities."""
        return ROLE_LABEL.get(self.kind) if self.kind in ROLE_LABEL else None


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

    Parameters
    ----------
    bot:
        Live PTB bot. Used to detect targets that are *this* bot.
    executor_id:
        The user invoking the moderation command.
    target_id:
        The user being acted on.
    target_fname:
        Best-effort first name from upstream resolution; falls back to a cache
        lookup, then to ``"User <id>"``.
    target_is_bot:
        Optional pre-known bot flag (e.g. from ``bot.get_chat`` upstream).

    Notes
    -----
    Role resolution uses the cached :func:`get_effective_role` so this stays
    cheap — every code path that calls ``classify`` already has the user's
    profile resolved upstream, so the only async hit is the role cache.
    """
    if not target_fname or target_fname.startswith("User "):
        target_fname = await db.users_db.get_first_name(
            target_id, target_fname or f"User {target_id}"
        )

    if target_id == executor_id:
        return Identity("self", target_id, target_fname, is_bot=False)
    if target_id == bot.id:
        return Identity("this_bot", target_id, target_fname, is_bot=True)
    if target_id == TELEGRAM_USER_ID:
        return Identity("telegram", target_id, target_fname, is_bot=False)
    if target_is_bot:
        return Identity("other_bot", target_id, target_fname, is_bot=True)

    role = await get_effective_role(target_id)
    if role == "founder":
        return Identity("founder", target_id, target_fname)
    if role == "admin":
        return Identity("admin", target_id, target_fname)
    if role == "developer":
        return Identity("developer", target_id, target_fname)
    if role == "tester":
        return Identity("tester", target_id, target_fname)
    return Identity("user", target_id, target_fname)


def _line(ident: Identity) -> str:
    """Build the canonical ``mention - <id>`` chunk for an identity."""
    return f"{mention(ident.target_id, ident.fname)} - {code(str(ident.target_id))}"


# ────────────────── Per-action witty refusals ───────────────────── #
# * Each map covers identities that should *not* be acted on. ``user`` and
# * lower-rank staff are never returned here — those go through the normal
# * moderation flow. The reply is one short professional-but-friendly line.

_BAN_REFUSE: dict[IdentityKind, str] = {
    "self": "Banning yourself is a creative idea, but no - the federation needs you.",
    "this_bot": "I keep this federation running. Banning me is a no-go :)",
    "telegram": "Telegram itself? Bold move. Not happening.",
    "founder": "{line} is the Founder - banning the boss is above my pay grade.",
    "admin": "{line} is an Admin. Demote them first if you really mean it.",
    "developer": "{line} is a Developer. Demote them before you ban.",
    "tester": "{line} is a Tester. Demote them before you ban.",
}

_KICK_REFUSE: dict[IdentityKind, str] = {
    "self": "Kicking yourself? Just leave the group instead :v",
    "this_bot": "Kick me? I run this place. Not happening.",
    "telegram": "Pretty sure I can't kick Telegram from its own group.",
    "founder": "{line} is the Founder. They are not getting kicked here.",
    "admin": "{line} is an Admin. Demote them first if you really mean it.",
    "developer": "{line} is a Developer. Demote them before you kick.",
    "tester": "{line} is a Tester. Demote them before you kick.",
}

_MUTE_REFUSE: dict[IdentityKind, str] = {
    "self": "Can't mute yourself - that's not how this works.",
    "this_bot": "Muting me won't do much - I don't send messages on my own anyway.",
    "telegram": "Telegram service messages aren't muteable from here.",
    "founder": "{line} is the Founder - the mute button doesn't apply :')",
    "admin": "{line} is an Admin. Demote them first if you really mean it.",
    "developer": "{line} is a Developer. Demote them before you mute.",
    "tester": "{line} is a Tester. Demote them before you mute.",
}

_WARN_REFUSE: dict[IdentityKind, str] = {
    "self": "Self-warning is just journaling. Try /reflect ... oh wait, that's not a thing.",
    "this_bot": "Warn me? I'm the one who manages warnings around here.",
    "telegram": "Telegram doesn't take warnings, sorry.",
}

_UNBAN_REFUSE: dict[IdentityKind, str] = {
    "self": "You can't unban yourself :v use /checkme and submit an appeal instead.",
    "this_bot": "{line} - I manage the bans, not receive them. Nothing to undo.",
    "telegram": "Telegram was never on the ban list to begin with.",
    "founder": "{line} is the Founder - they have never been banned.",
    "admin": "{line} is an Admin. Staff are not federation-bannable, so nothing to undo.",
    "developer": "{line} is a Developer. Staff are not federation-bannable, so nothing to undo.",
    "tester": "{line} is a Tester. Staff are not federation-bannable, so nothing to undo.",
}

_UNMUTE_REFUSE: dict[IdentityKind, str] = {
    "self": "You can't unmute yourself - ask a moderator.",
    "this_bot": "{line} - bots aren't muteable, so nothing to undo.",
    "telegram": "Telegram service was never muted.",
    "founder": "{line} is the Founder - definitely not muted.",
}

_PROMOTE_REFUSE: dict[IdentityKind, str] = {
    "self": "Promoting yourself would be nice, but the hierarchy says no.",
    "this_bot": "Promoting a bot doesn't quite work - I'm already running things.",
    "telegram": "Telegram is doing fine on its own, no role needed.",
    "other_bot": "Other bots can't hold federation roles - Telegram users only.",
}

_DEMOTE_REFUSE: dict[IdentityKind, str] = {
    "self": "Can't demote yourself - ask a higher-up if you really mean it.",
    "this_bot": "I have no role to lose. Nothing to demote :)",
    "telegram": "Telegram has no role here.",
    "founder": "{line} is the Founder - ownership transfer is a separate command.",
}


_REFUSE_TABLES: dict[str, dict[IdentityKind, str]] = {
    "ban": _BAN_REFUSE,
    "kick": _KICK_REFUSE,
    "mute": _MUTE_REFUSE,
    "warn": _WARN_REFUSE,
    "unban": _UNBAN_REFUSE,
    "unmute": _UNMUTE_REFUSE,
    "promote": _PROMOTE_REFUSE,
    "demote": _DEMOTE_REFUSE,
}


def refuse_message(action: str, ident: Identity) -> str | None:
    """Return a witty refusal line for ``action`` against ``ident``, or ``None``.

    ``None`` means the action is allowed against this identity and the caller
    should proceed with the normal moderation flow.
    """
    table = _REFUSE_TABLES.get(action, {})
    template = table.get(ident.kind)
    if template is None:
        return None
    return template.format(line=_line(ident))


# ─────────────── Staff heads-up (action proceeds) ───────────────── #
# * For unwarn / unmute / resetwarns on staff targets, the action proceeds
# * but we surface a short heads-up so the executor knows the target is
# * staff — useful when an Admin is cleaning up a stale record.


def staff_notice(action: str, ident: Identity, community_name: str) -> str | None:
    """Return a heads-up line when acting on staff, or ``None`` otherwise."""
    if ident.kind not in ("admin", "developer", "tester"):
        return None
    return (
        f"Heads up - {_line(ident)} is a {community_name} {ident.role_label}. "
        f"Proceeding with {action} anyway."
    )
