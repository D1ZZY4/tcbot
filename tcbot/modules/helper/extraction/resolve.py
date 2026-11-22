# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Reply, argument, and entity target resolution."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from telegram import Chat

from tcbot import database as db
from tcbot.modules.helper.identity import ANONYMOUS_BOT_ID, TELEGRAM_USER_ID
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Bot, ChatFullInfo, Message, Update

log = get_logger(__name__)

# * Telegram lookups are wrapped in wait_for so a stalled API call never blocks
# * the user-facing reply. Per-call budget is the shared project-wide value.
_GET_CHAT_TIMEOUT = TELEGRAM_LOOKUP_TIMEOUT

# * A Telegram user ID is a positive decimal integer. Groups and channels
# * carry negative IDs (or resolve through a chat lookup), so a token that
# * does not name a positive integer is not a user target.
_USER_ID_RE = re.compile(r"-?\d+")


def parse_user_id_token(token: str) -> int | None:
    """Return the positive user ID a token names, or ``None``.

    Shape and range are checked together so a call site cannot accept a
    malformed signed token and then raise inside ``int()``. A group or
    channel ID is negative and is deliberately rejected: federation
    decisions target users, never chats.
    """
    if not _USER_ID_RE.fullmatch(token):
        return None
    value = int(token)
    return value if value > 0 else None


async def _safe_get_chat(bot: Bot, ident: str | int) -> Chat | ChatFullInfo | None:
    """Call ``bot.get_chat`` with a bounded timeout; returns ``None`` on failure."""
    try:
        return await asyncio.wait_for(bot.get_chat(ident), timeout=_GET_CHAT_TIMEOUT)
    except Exception as exc:
        log.debug("get_chat(%s) failed: %s", ident, exc)
        return None


# ──────────────────────── Target resolution ─────────────────────── #


def restates_reply_target(
    token: str | None,
    target_id: int,
    target_username: str | None,
) -> bool:
    """Return True when *token* restates the reply target.

    A moderator may repeat the quoted user before the reason or duration.
    The numeric form is exact; the username form is compared case-folded
    against the quoted sender's username. An absent username means the
    token cannot be proven to restate the target and is left untouched.
    """
    if not token:
        return False
    if parse_user_id_token(token) == target_id:
        return True
    if not token.startswith("@") or not target_username:
        return False
    return token[1:].casefold() == target_username.casefold()


def first_arg_is_explicit(args: list[str]) -> bool:
    """Return True when ``args[0]`` is shaped like an explicit target.

    Shape only (positive numeric ID or ``@username``), no I/O: whether the
    token actually names someone is decided by the resolver. Shared by
    :func:`extract_target` (override detection),
    :func:`extract_mod_target` (reason splitting), and the promotion entry
    (argument consumption) so all three agree on what counts as a target.
    """
    if not args:
        return False
    first = args[0]
    # * A bare "@" names nobody; treating it as explicit would only
    # * divert the reply path into a resolution that returns None.
    return parse_user_id_token(first) is not None or (
        first.startswith("@") and len(first) > 1
    )


async def _best_name(uid: int, *primary: str | None) -> str:
    """Pick the first non-empty/non-numeric primary name; fall back to cache, then str(uid).

    Returns the raw numeric ID string rather than a decorated ``User <id>``
    form so that callers using ``user_ref()`` or the ``user_ref() - code(id)``
    pattern can detect a numeric fallback and avoid displaying the ID twice.
    """
    for cand in primary:
        if cand is not None and not db.users_cache.is_placeholder_name(cand):
            return cand
    # * Try the member cache before resorting to a bare numeric ID.
    cached = await db.users_cache.get_first_name(uid, "")
    if not db.users_cache.is_placeholder_name(cached):
        return cached
    return str(uid)


async def _cached_username_target(username: str) -> tuple[int, str] | None:
    """Last-resort exact username lookup while MTProto cannot answer.

    The live resolvers are always tried first. A cached username is used only
    when MTProto is down, because Telegram usernames can be released and
    reassigned: while a live resolver exists, an unknown username must stay
    unknown rather than resolve to whoever held it before.
    """
    if db.mtproto.is_available():
        return None
    cached = await db.users_cache.get_by_username(username)
    if cached is None:
        return None
    uid, first = cached
    log.warning(
        "Resolved @%s from the member cache while MTProto is unavailable: %d",
        username,
        uid,
    )
    return uid, await _best_name(uid, first, username)


async def extract_target(
    update: Update,
    args: list[str],
    bot: Bot | None = None,
    *,
    prefer_explicit: bool = False,
) -> tuple[int, str] | tuple[None, None]:
    """Return (user_id, first_name) resolved from reply, args, entity, or mention.

    Priority order:
    1. Reply (most common use case), with one exception: a typed numeric
       ID or ``@username`` that verifies as a real user different from the
       quoted sender overrides the reply. A typed ID is deliberate intent;
       a quote is often just context, and silently acting on the quoted
       user is how wrong-person moderation happens. Anything unverified
       (a reason starting with a number, an unknown ID) keeps the reply
       target, as before.
    2. Args with full info (numeric ID or @username)
    3. Args with partial info (search users_cache by name), only with
       ``prefer_explicit=True``: fuzzy matching can point at the wrong
       person (the search takes the first of up to five hits), so
       moderation paths resolve reply, numeric ID, and ``@username`` only.
    4. Text mention entity
    5. @Mention entity

    Only Telegram users resolve. A group or channel ID, and an ``@username``
    that resolves to a group or channel, is not a moderation target and
    yields no hit. A Telegram user ID is positive; a negative token is a
    chat ID and is rejected before any lookup.

    With ``prefer_explicit=True`` (read-only views such as /check, where
    showing the wrong person costs nothing), any resolving arg wins over
    the reply; when the arg resolves to nobody, the reply still stands.

    The returned name is always a human-readable string. When Telegram returns
    no first_name and the member cache has no entry, falls back to the bare
    numeric ID string (``str(uid)``) so callers using ``user_ref()`` can detect
    the numeric fallback and avoid displaying the ID twice.
    """
    msg: Message | None = update.effective_message
    if msg is None:
        return None, None

    # * The reply read is sync (no I/O beyond a possible cached-name
    # * fallback), so peek it once and branch below. Every path below
    # * preserves the old order except the two explicit beats reply cases.
    reply_hit = await _reply_target(msg)
    if (
        args
        and reply_hit is not None
        and not prefer_explicit
        and not first_arg_is_explicit(args)
    ):
        return reply_hit
    if args and reply_hit is not None and prefer_explicit:
        hit = await _args_target(args, bot, allow_partial=True)
        return hit if hit is not None else reply_hit
    if args and reply_hit is not None:
        verified = await _args_target(args, bot, verified=True)
        if verified is not None and verified[0] != reply_hit[0]:
            log.info(
                "explicit target %d overrides reply target %d",
                verified[0],
                reply_hit[0],
            )
            return verified
        return reply_hit
    if args:
        hit = await _args_target(args, bot, allow_partial=prefer_explicit)
        if hit is not None:
            return hit
    elif reply_hit is not None:
        return reply_hit
    hit = await _entity_target(msg, bot)
    if hit is not None:
        return hit
    return None, None


def reply_uid(msg: Message) -> int | None:
    """Return the user ID quoted by ``msg``, or ``None``.

    Synchronous core of the reply-target decision, shared by
    :func:`_reply_target` and :func:`extract_mod_target` so both agree on
    who the quoted message names. Mirrors the skip rules exactly:
    GroupAnonymousBot and the Telegram service account never count, a
    channel sender is not an actionable target, and neither is a group
    sender (a group ID names no user).
    """
    target_msg = msg.reply_to_message
    if target_msg is None:
        return None
    from_user = target_msg.from_user
    if from_user is None:
        return None
    if from_user.id in (ANONYMOUS_BOT_ID, TELEGRAM_USER_ID):
        return None
    return from_user.id


async def _reply_target(msg: Message) -> tuple[int, str] | None:
    """Priority 1: reply sender, skipping placeholders and channel posts."""
    # * Skip GroupAnonymousBot (id 1087968824): it is a Telegram pseudo-user
    # * that appears as `from_user` when an anonymous admin sends a message.
    # * Targeting it would attempt to act on the placeholder, not a real user.
    # * Similarly skip the Telegram service account (777000) and channel posts.
    uid = reply_uid(msg)
    if uid is None:
        return None
    target_msg = msg.reply_to_message
    if target_msg is None:  # * Unreachable: reply_uid just saw one.
        return None
    from_user = target_msg.from_user
    if from_user is None:  # * Unreachable: reply_uid just read it.
        return None
    return uid, from_user.first_name or await _best_name(uid)


async def _args_target(
    args: list[str],
    bot: Bot | None,
    *,
    allow_partial: bool = False,
    verified: bool = False,
) -> tuple[int, str] | None:
    """Priorities 2-3: numeric ID, @username, then partial name search.

    The partial-name search runs only with ``allow_partial=True``
    (read-only callers via ``prefer_explicit``): it takes the first of
    up to five fuzzy hits, which is fine for a profile view but never
    for a moderation target.

    With ``verified=True`` only real Telegram users count: numeric IDs and
    ``@usernames`` that resolve to a private chat, and the partial-name
    search never runs. The private-chat check applies in every mode, so a
    group or channel never becomes a moderation target.
    """
    arg = args[0].lstrip("@")

    # * Priority 2a: Numeric ID. Only a positive ID names a user: a
    # * negative token is a chat ID and is rejected before any lookup.
    uid = parse_user_id_token(arg)
    if uid is not None:
        # * Fast path: IDs are immutable, so a cached identity is
        # * authoritative for resolution and the live get_chat round
        # * trip (a full _GET_CHAT_TIMEOUT on a blip) can be skipped.
        # * Only real cached names count: bare-numeric and legacy
        # * "User <id>" fallbacks fall through to the live lookup,
        # * exactly like the outage path below already does.
        # * Verified callers never take the fast path: a stale cache
        # * entry must not override the reply target without a live
        # * check that the ID still resolves on Telegram.
        try:
            cached_name = await db.users_cache.get_first_name(uid, "")
        except Exception as exc:
            log.debug("numeric fast-path cache read failed for %d: %s", uid, exc)
            cached_name = ""
        if not verified and not db.users_cache.is_placeholder_name(cached_name):
            return uid, cached_name
        chat_first: str | None = None
        chat_username: str | None = None
        if bot:
            chat = await _safe_get_chat(bot, uid)
            if chat is not None and getattr(chat, "type", None) == Chat.PRIVATE:
                chat_first = chat.first_name
                chat_username = chat.username
        if verified and not chat_first:
            return None
        return uid, await _best_name(uid, chat_first, chat_username)

    if _USER_ID_RE.fullmatch(arg):
        # * A numeric token outside the positive user-id range is a chat id,
        # * not a username; there is nothing left to resolve.
        return None

    # * Priority 2b: @username lookup
    if bot and arg:
        chat = await _safe_get_chat(bot, f"@{arg}")
        if chat is not None:
            if getattr(chat, "type", None) != Chat.PRIVATE:
                return None
            return chat.id, await _best_name(
                chat.id, chat.first_name, chat.username, arg
            )
        # * Bot API username lookups miss some existing accounts; one MTProto
        # * exact-username resolve before giving up (deterministic, no fuzzy).
        hit = await db.mtproto.resolve_username(arg)
        if hit is not None:
            uid, fname, _ = hit
            if uid > 0:
                return uid, await _best_name(uid, fname, arg)
        # ! CRITICAL: a verified override must rest on a live resolution. A
        # ! cached username can be reassigned, so during an MTProto outage it
        # ! must not displace the reply target and moderate the wrong user.
        if not verified:
            cached = await _cached_username_target(arg)
            if cached is not None:
                return cached
        log.warning(
            "Could not resolve @%s (MTProto available=%s).",
            arg,
            db.mtproto.is_available(),
        )

    # * Priority 3: Partial name search in users_cache, read-only
    # * callers only (see _args_target docstring for why moderation
    # * paths never fuzzy-match).
    # * Uses a server-side regex query capped at 5 results; avoids loading
    # * the entire user cache into Python for a linear scan.
    if allow_partial and arg:
        matches = await db.users_cache.search_by_name(arg)
        if matches:
            user = matches[0]
            uid = user.get("user_id")
            if uid and int(uid) > 0:
                return uid, user.get("first_name") or await _best_name(uid)
    return None


async def extract_mod_target(
    update: Update,
    args: list[str],
    bot: Bot | None = None,
) -> tuple[tuple[int, str] | tuple[None, None], bool]:
    """Resolve a moderation target plus whether ``args[0]`` was consumed.

    Wraps :func:`extract_target` (the verified-override rule applies) and
    reports whether the first arg token named the target, so entries split
    reason text without reimplementing the reply/override decision:

    - no reply + explicit-shaped ``args[0]``: consumed (classic path);
    - reply + ``args[0]`` naming the resolved target: consumed (override
      path; the typed ID is the target, not reason text);
    - otherwise (reply retained, restated-ID reply, unshaped first token,
      or nothing resolved): not consumed; ``parse_inline_reason`` still
      strips a restated ID via ``reply_target_id``.
    """
    msg = update.effective_message
    quoted_uid = reply_uid(msg) if msg is not None else None
    hit = await extract_target(update, args, bot)
    target_id, _ = hit
    consumed = (
        target_id is not None
        and bool(args)
        and first_arg_is_explicit(args)
        and (quoted_uid is None or target_id != quoted_uid)
    )
    return hit, consumed


async def _entity_target(msg: Message, bot: Bot | None) -> tuple[int, str] | None:
    """Priorities 4-5: text-mention entity, then @mention entity."""
    for ent in msg.entities or []:
        if ent.type == "text_mention" and ent.user:
            u = ent.user
            if u.id in (ANONYMOUS_BOT_ID, TELEGRAM_USER_ID):
                continue
            return u.id, u.first_name or await _best_name(u.id)

    if bot:
        # * Telegram entity offsets are UTF-16 code units, not Python str
        # * indices. Slicing the str directly misaligns past any emoji
        # * (surrogate pair) before the mention and may resolve the wrong
        # * username. Slice the UTF-16-LE bytes instead; a split surrogate
        # * fails to decode and the entity is skipped (fail closed).
        raw = (msg.text or "").encode("utf-16-le")
        for ent in msg.entities or []:
            if ent.type == "mention":
                try:
                    uname = raw[
                        (ent.offset + 1) * 2 : (ent.offset + ent.length) * 2
                    ].decode("utf-16-le")
                except UnicodeDecodeError:
                    continue
                except ValueError:
                    continue
                if uname.lstrip("@") in (
                    "GroupAnonymousBot",
                    "Telegram",
                ):
                    continue
                chat = await _safe_get_chat(bot, f"@{uname}")
                if chat is not None:
                    if getattr(chat, "type", None) != Chat.PRIVATE:
                        continue
                    return chat.id, await _best_name(chat.id, chat.first_name, uname)
                hit = await db.mtproto.resolve_username(uname)
                if hit is not None:
                    uid, fname, _ = hit
                    if uid > 0:
                        return uid, await _best_name(uid, fname, uname)
                cached = await _cached_username_target(uname)
                if cached is not None:
                    return cached

    return None
