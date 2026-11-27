# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Single owner for Kurigram/Telegram error types, groupings, and predicates."""

from __future__ import annotations

from pyrogram.errors import (
    AuthKeyDuplicated,
    BadRequest,
    ButtonUserInvalid,
    ChatAdminRequired,
    Flood,
    Forbidden,
    RPCError,
    SessionRevoked,
    Timedout,
    Unauthorized,
)
from pyrogram.errors import Timeout as RPCTimeout


class PollingConflictError(RuntimeError):
    """Another process is already polling the same bot identity."""


# * Error groups shared by classification, dispatch, and operator messaging.
# * All code-420 RPCs share the Flood base; only matching FloodWait missed the
# * premium, slowmode, and other flood-family errors Kurigram can surface.
RATE_LIMIT_ERRORS: tuple[type[BaseException], ...] = (Flood,)
TELEGRAM_TIMEOUT_ERRORS: tuple[type[BaseException], ...] = (Timedout, RPCTimeout)
TRANSPORT_TIMEOUT_ERRORS: tuple[type[BaseException], ...] = (
    TimeoutError,
    Timedout,
    RPCTimeout,
)
API_REFUSAL_ERRORS: tuple[type[BaseException], ...] = (BadRequest, Forbidden)
OWNER_ONLY_ERRORS: tuple[type[BaseException], ...] = (
    PollingConflictError,
    Unauthorized,
)
MTPROTO_AUTH_TYPE_NAMES: tuple[str, ...] = (
    "AuthKeyDuplicated",
    "AuthKeyNotFound",
    "SessionRevoked",
)


_INVALID_BUTTON_USER_MARKERS: tuple[str, ...] = (
    "button_user_invalid",
    "buttonuserinvalid",
)


def is_invalid_button_user(exc: object) -> bool:
    """Return True for a stale or invalid user-profile button in a rich message.

    Kurigram 2.2.27 maps the 400 ``BUTTON_USER_INVALID`` RPC to the exact
    ``ButtonUserInvalid`` class. Durable records rebuild the refusal as text,
    so the marker check stays as a fallback for those rebuilt exceptions.
    """
    if exc is None:
        return False
    if isinstance(exc, ButtonUserInvalid):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _INVALID_BUTTON_USER_MARKERS)


def is_bad_request(exc: object) -> bool:
    """Return True for a Telegram bad-request refusal."""
    return isinstance(exc, BadRequest)


def is_forbidden(exc: object) -> bool:
    """Return True for a Telegram forbidden refusal."""
    return isinstance(exc, Forbidden)


def is_rate_limit(exc: object) -> bool:
    """Return True for a Telegram flood-wait rate limit."""
    return isinstance(exc, RATE_LIMIT_ERRORS)


def is_telegram_timeout(exc: object) -> bool:
    """Match Kurigram's RPC timeout without claiming builtin timeouts.

    Python 3.11 made ``asyncio.TimeoutError`` an alias of the builtin, so an
    ``isinstance(exc, TimeoutError)`` branch would label database and worker
    deadlines as Telegram failures. Match the client's RPC timeout classes
    directly.
    """
    return isinstance(exc, TELEGRAM_TIMEOUT_ERRORS)


def is_api_refusal(exc: object) -> bool:
    """Return True for a service answer that proves the transport is healthy."""
    return isinstance(exc, API_REFUSAL_ERRORS)


def is_unauthorized(exc: object) -> bool:
    """Return True for an invalid or revoked bot token."""
    return isinstance(exc, Unauthorized)


def is_chat_admin_required(exc: object) -> bool:
    """Return True when Telegram reports missing admin rights in a chat."""
    return isinstance(exc, ChatAdminRequired)


def is_rpc_error(exc: object) -> bool:
    """Return True for any Kurigram RPC error."""
    return isinstance(exc, RPCError)


def is_owner_only(exc: object) -> bool:
    """Return True for errors that must only reach the owner DM."""
    return isinstance(exc, OWNER_ONLY_ERRORS)


def is_mtproto_auth_error(exc: object) -> bool:
    """Return True for a dead MTProto session reported by Telegram."""
    return type(exc).__name__ in MTPROTO_AUTH_TYPE_NAMES


def is_auth_key_duplicated(exc: object) -> bool:
    """Check whether *exc* is Telegram's 406 AUTH_KEY_DUPLICATED."""
    try:
        from pyrogram.errors import AuthKeyDuplicated  # noqa: PLC0415
    except ImportError:
        return type(exc).__name__ == "AuthKeyDuplicated"
    return isinstance(exc, AuthKeyDuplicated)


def is_auth_key_not_found(exc: object) -> bool:
    """Check whether *exc* is Telegram's transport 404 AUTH_KEY_NOT_FOUND.

    Kurigram raises this from the session receive worker when the server
    reports the auth key is gone. It is a ``TransportError`` subclass, not
    an ``RPCError``, so it is detected in its own module.
    """
    try:
        from pyrogram.session.session import AuthKeyNotFound  # noqa: PLC0415
    except ImportError:
        return type(exc).__name__ == "AuthKeyNotFound"
    return isinstance(exc, AuthKeyNotFound)


def is_session_revoked(exc: object) -> bool:
    """Check whether Telegram revoked the stored session (401 SESSION_REVOKED)."""
    try:
        from pyrogram.errors import SessionRevoked  # noqa: PLC0415
    except ImportError:
        return type(exc).__name__ == "SessionRevoked"
    return isinstance(exc, SessionRevoked)


__all__ = [
    "API_REFUSAL_ERRORS",
    "MTPROTO_AUTH_TYPE_NAMES",
    "OWNER_ONLY_ERRORS",
    "RATE_LIMIT_ERRORS",
    "TELEGRAM_TIMEOUT_ERRORS",
    "TRANSPORT_TIMEOUT_ERRORS",
    "AuthKeyDuplicated",
    "BadRequest",
    "ButtonUserInvalid",
    "ChatAdminRequired",
    "Flood",
    "Forbidden",
    "RPCError",
    "RPCTimeout",
    "SessionRevoked",
    "Timedout",
    "Unauthorized",
    "is_api_refusal",
    "is_auth_key_duplicated",
    "is_auth_key_not_found",
    "is_bad_request",
    "is_chat_admin_required",
    "is_forbidden",
    "is_invalid_button_user",
    "is_mtproto_auth_error",
    "is_owner_only",
    "is_rate_limit",
    "is_rpc_error",
    "is_session_revoked",
    "is_telegram_timeout",
    "is_unauthorized",
]
