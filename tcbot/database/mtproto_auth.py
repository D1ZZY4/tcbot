# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""One-time MTProto session authorization.

Run once, interactively, wherever a terminal and the database are reachable::

    uv run python -m tcbot.database.mtproto_auth +6281234567890

Sends a Telegram login code to the account, verifies it (plus the 2FA
password when set), and stores the session in MongoDB, where every bot
instance picks it up. Nothing here is wired into extraction: this only
mints the credential the resolver uses.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from typing import TYPE_CHECKING

from pyrogram.errors import (
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
)

from tcbot.database import mongos as mongos_mod
from tcbot.database import mtproto

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram import Client
    from pyrogram.types import User

log = logging.getLogger(__name__)


async def _already_authorized(client: Client) -> User | None:
    """Return the logged-in user, or None when this session is fresh."""
    try:
        return await client.get_me()
    except Exception:
        return None


async def authorize(
    phone: str,
    *,
    code_fn: Callable[[str], str] = input,
    password_fn: Callable[[str], str] = getpass.getpass,
) -> str:
    """Authorize the shared session for *phone*; return where it is stored.

    Raises RuntimeError with a human message for every expected failure
    (bad number/code, expired code, wrong password, flood wait). Unexpected
    errors propagate untouched.
    """
    if not mtproto.is_configured():
        raise RuntimeError("API_ID/API_HASH are not set; nothing to authorize.")
    try:
        await mongos_mod.connect()
    except Exception as exc:
        raise RuntimeError(
            f"MongoDB unreachable, session has nowhere to land: {exc}"
        ) from exc
    client = mtproto.client()
    await client.connect()
    try:
        me = await _already_authorized(client)
        if me is not None:
            log.info("Session already authorized as %s.", me.id)
            return _store_ref()
        try:
            sent = await client.send_code(phone)
        except (PhoneNumberInvalid, FloodWait) as exc:
            raise RuntimeError(f"Cannot send login code: {exc}") from exc
        try:
            await client.sign_in(
                phone, sent.phone_code_hash, code_fn("Enter Telegram login code: ")
            )
        except SessionPasswordNeeded:
            try:
                await client.check_password(password_fn("Enter 2FA password: "))
            except PasswordHashInvalid as exc:
                raise RuntimeError("Wrong 2FA password.") from exc
        except (PhoneCodeInvalid, PhoneCodeExpired) as exc:
            raise RuntimeError(f"Login code rejected: {exc}") from exc
        me = await _already_authorized(client)
        if me is None:  # ponytail: paranoid branch, sign_in said ok but whoami fails
            raise RuntimeError("Sign-in reported success but whoami failed; retry.")
        log.info("Session authorized as %s.", me.id)
        return _store_ref()
    finally:
        await client.disconnect()


def _store_ref() -> str:
    """Human reference to where the shared session persists."""
    return f"mongodb:mtproto_state:{mtproto.cfg.mtproto_session}"


def main(argv: list[str] | None = None) -> int:
    """CLI entry: authorize one phone number, confirm where it landed."""
    parser = argparse.ArgumentParser(description="Authorize the MTProto session once.")
    parser.add_argument(
        "phone", nargs="?", help="Account phone number, e.g. +6281234567890"
    )
    args = parser.parse_args(argv)
    phone = (args.phone or input("Account phone number: ")).strip().replace(" ", "")
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"
    try:
        where = asyncio.run(authorize(phone))
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"Authorized. Session stored in {where}; every instance picks it up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
