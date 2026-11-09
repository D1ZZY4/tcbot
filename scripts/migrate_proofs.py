# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""One-shot proof migration: move ban proofs to a new channel and repoint refs.

Copies every stored proof message from the old proof chat into a new channel,
updates ``proof_message_id`` / ``previous_proof_message_id`` in the bans
collection, rewrites the proof deep-link buttons on the stored ban log
messages, and fixes any old proof link inside the copied captions.

This is an operator runbook tool (see docs/operations/proof-migration.md),
not part of the bot runtime: it talks to MongoDB and Telegram directly and
does not import tcbot. Stop the bot while it runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from typing import TYPE_CHECKING

from pymongo import MongoClient
from pyrogram import Client
from pyrogram.types import MessageEntity
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

# * Default destination agreed with the operator: a plain channel, no topic.
# * Overridable with --new-proof-chat.
DEFAULT_NEW_PROOF_CHAT = -1003997518221
DEFAULT_STATE_PATH = "proof_migration_state.json"
# * Largest flood wait the script will sleep through before aborting.
_MAX_FLOOD_WAIT_S = 300


# ─────────────────────────────── Pure helpers ──────────────────────────────


def chat_link_id(chat_id: int) -> str:
    """Strip the -100 supergroup prefix for t.me/c/ URLs (mirrors parse_link)."""
    s = str(chat_id)
    if s.startswith("-100"):
        return s[4:]
    return s.lstrip("-")


def proof_link(chat_id: int, message_id: int) -> str:
    """Build the t.me/c/ deep link used by proof buttons and captions."""
    return f"https://t.me/c/{chat_link_id(chat_id)}/{message_id}"


def url_matches(url: str, old_link: str) -> bool:
    """Return True when a button/caption URL targets the old proof message.

    Matches the bare link and the same link with a query suffix (old forum
    topic links carry ?thread=...), so thread'd and plain links both hit.
    """
    return url == old_link or url.startswith(old_link + "?")


def swap_link_url(url: str, links: dict[str, str]) -> str:
    """Return the new URL when ``url`` targets a mapped old link, else as-is."""
    for old_link, new_link in links.items():
        if url_matches(url, old_link):
            return new_link
    return url


def build_link_map(
    old_chat: int,
    new_chat: int,
    old_mid: int | None,
    new_mid: int | None,
) -> dict[str, str]:
    """Map one old proof message to its new link; empty when either is absent."""
    if not old_mid or not new_mid:
        return {}
    return {proof_link(old_chat, old_mid): proof_link(new_chat, new_mid)}


# ─────────────────────────────── State file ────────────────────────────────


def _as_dict(value: object) -> dict:
    """Return value as a dict, else an empty one (defensive state parsing)."""
    return dict(value) if isinstance(value, dict) else {}


def load_state(path: str) -> dict:
    """Load the resume state ({"done": {...}, "copies": {...}}); empty when absent."""
    try:
        with pathlib.Path(path).open(encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError, json.JSONDecodeError:
        return {"done": {}, "copies": {}}
    if not isinstance(data, dict):
        return {"done": {}, "copies": {}}
    return {"done": _as_dict(data.get("done")), "copies": _as_dict(data.get("copies"))}


def save_state(path: str, state: dict) -> None:
    """Write state atomically so an interruption never leaves a torn file."""
    tmp = pathlib.Path(path + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def ban_ids_pending(bans: list[dict], state: dict) -> list[str]:
    """Return ban ids not yet marked done in the state file."""
    done = state.get("done") or {}
    return [
        str(ban.get("ban_id")) for ban in bans if str(ban.get("ban_id")) not in done
    ]


# ──────────────────────────────── Telegram I/O ─────────────────────────────


def _is_flood(exc: BaseException) -> bool:
    """Return True for Telegram flood-wait errors from either client."""
    name = type(exc).__name__
    if name in ("FloodWait", "RetryAfter"):
        return True
    text = str(exc).lower()
    return "flood" in text and "wait" in text


async def _with_retry[T](call: Callable[[], Awaitable[T]]) -> T:
    """Await a Telegram call, sleeping through one flood wait and retrying."""
    try:
        return await call()
    except Exception as exc:
        if not _is_flood(exc):
            raise
        wait = max(0, int(getattr(exc, "value", 0) or getattr(exc, "retry_after", 0)))
        if wait > _MAX_FLOOD_WAIT_S:
            raise RuntimeError(
                f"Flood wait of {wait}s exceeds the {_MAX_FLOOD_WAIT_S}s ceiling; "
                "aborting. Re-run later to resume."
            ) from exc
        print(f"  flood wait: sleeping {wait}s", flush=True)
        await asyncio.sleep(wait)
        return await call()


async def _fetch_one(client: Client, chat_id: int, mid: int):
    """Fetch one message; returns None when it no longer exists.

    get_messages with a single id returns the message (or None), but the
    client also accepts list modes, so a list result is normalized here.
    """
    msg = await _with_retry(lambda: client.get_messages(chat_id, mid))
    if isinstance(msg, list):
        return msg[0] if msg else None
    return msg


async def copy_proof(
    client: Client,
    old_chat: int,
    new_chat: int,
    mid: int,
) -> int | None:
    """Copy one proof message (albums whole) to the new channel.

    Returns the new first message id, or None when the old message is gone.
    Albums go through get_media_group + copy_media_group so Telegram keeps
    the grouping; singles copy through copy_message.
    """
    msg = await _fetch_one(client, old_chat, mid)
    if msg is None:
        return None
    if getattr(msg, "media_group_id", None):
        members = await _with_retry(lambda: client.get_media_group(old_chat, mid))
        if members:
            copied = await _with_retry(
                lambda: client.copy_media_group(new_chat, old_chat, mid)
            )
            if copied:
                return min(int(getattr(m, "id", 0)) for m in copied) or None
            return None
    copied_one = await _with_retry(lambda: client.copy_message(new_chat, old_chat, mid))
    if copied_one is None:
        return None
    return int(getattr(copied_one, "id", 0)) or None


async def fix_caption_links(
    client: Client,
    new_chat: int,
    new_mid: int,
    links: dict[str, str],
) -> bool:
    """Rewrite old proof links inside one copied message's caption.

    Only the URL entities change; the caption text is untouched. Returns
    True when the caption was edited.
    """
    if not links:
        return False
    msg = await _fetch_one(client, new_chat, new_mid)
    if msg is None:
        return False
    entities = getattr(msg, "caption_entities", None)
    if not entities:
        return False
    changed = False
    new_entities: list[MessageEntity] = []
    for ent in entities:
        old_url = getattr(ent, "url", "") or ""
        target = swap_link_url(str(old_url), links)
        if target != str(old_url):
            new_entities.append(
                MessageEntity(
                    type=ent.type,
                    offset=ent.offset,
                    length=ent.length,
                    url=target,
                    user=ent.user,
                    language=ent.language,
                    custom_emoji_id=ent.custom_emoji_id,
                )
            )
            changed = True
        else:
            new_entities.append(ent)
    if not changed:
        return False
    await _with_retry(
        lambda: client.edit_message_caption(
            new_chat, new_mid, msg.caption or "", caption_entities=new_entities
        )
    )
    return True


def rebuild_markup(
    remote_markup: object, links: dict[str, str]
) -> tuple[InlineKeyboardMarkup | None, int]:
    """Rebuild a log message's inline markup with proof URLs swapped.

    remote_markup is a pyrogram InlineKeyboardMarkup (or None). Returns
    (markup, changed_count); markup is None when the markup carries a button
    shape this script cannot faithfully rebuild, in which case the caller
    leaves the message untouched. URL buttons keep the ban-log PRIMARY
    style; callback buttons pass through by text and callback data.
    """
    rows_in = getattr(remote_markup, "inline_keyboard", None) or []
    new_rows: list[list[InlineKeyboardButton]] = []
    changed = 0
    unknown = False
    for row in rows_in:
        new_row: list[InlineKeyboardButton] = []
        for btn in row:
            text = getattr(btn, "text", "") or ""
            url = getattr(btn, "url", None)
            callback = getattr(btn, "callback_data", None)
            if url:
                new_url = swap_link_url(str(url), links)
                if new_url != str(url):
                    changed += 1
                new_row.append(
                    InlineKeyboardButton(
                        text,
                        url=new_url,
                        style=KeyboardButtonStyle.PRIMARY,
                    )
                )
            elif callback:
                new_row.append(InlineKeyboardButton(text, callback_data=str(callback)))
            else:
                unknown = True
                new_row.append(InlineKeyboardButton(text or " ", callback_data="_"))
        new_rows.append(new_row)
    if unknown and changed:
        return None, changed
    return InlineKeyboardMarkup(new_rows), changed


async def edit_log_markup(
    client: Client,
    bot: Bot,
    logs_chat: int,
    log_mid: int,
    links: dict[str, str],
) -> tuple[bool, int]:
    """Swap proof URLs on one stored log message. Returns (edited, count)."""
    msg = await _fetch_one(client, logs_chat, log_mid)
    if msg is None:
        return False, 0
    markup, changed = rebuild_markup(getattr(msg, "reply_markup", None), links)
    if not changed or markup is None:
        return False, changed
    await _with_retry(
        lambda: bot.edit_message_reply_markup(logs_chat, log_mid, reply_markup=markup)
    )
    return True, changed


# ────────────────────────────── Migration core ─────────────────────────────


async def migrate_ban(
    *,
    client: Client,
    bot: Bot,
    bans,
    ban: dict,
    old_chat: int,
    new_chat: int,
    logs_chat: int,
    state: dict,
    state_path: str,
    apply: bool,
    delay: float,
) -> tuple[bool, str]:
    """Migrate one ban record. Returns (ok, note)."""
    ban_id = str(ban.get("ban_id"))
    copies: dict = state.setdefault("copies", {})
    entry: dict = dict(state.setdefault("done", {}).get(ban_id) or {})

    old_proof = int(ban.get("proof_message_id") or 0)
    raw_prev = ban.get("previous_proof_message_id")
    old_prev = int(raw_prev) if raw_prev else 0

    new_proof: int | None = entry.get("proof_new")
    new_prev: int | None = entry.get("prev_new")

    if new_proof is None and old_proof:
        cached = copies.get(str(old_proof))
        if cached:
            new_proof = int(cached)
        elif not apply:
            return True, f"would copy proof {old_proof} -> new channel"
        else:
            new_proof = await copy_proof(client, old_chat, new_chat, old_proof)
            if new_proof is None:
                return False, f"old proof {old_proof} not found (deleted?)"
            copies[str(old_proof)] = new_proof
            entry["proof_new"] = new_proof
            state["done"][ban_id] = entry
            save_state(state_path, state)

    if new_prev is None and old_prev:
        cached = copies.get(str(old_prev))
        if cached:
            new_prev = int(cached)
        elif not apply:
            return True, f"would copy previous proof {old_prev} -> new channel"
        else:
            new_prev = await copy_proof(client, old_chat, new_chat, old_prev)
            if new_prev is None:
                return False, f"old previous proof {old_prev} not found (deleted?)"
            copies[str(old_prev)] = new_prev
            entry["prev_new"] = new_prev
            state["done"][ban_id] = entry
            save_state(state_path, state)

    if not apply:
        return True, f"would update ban {ban_id} + edit its log buttons"

    update: dict[str, object] = {}
    if old_proof and new_proof:
        update["proof_message_id"] = new_proof
    if old_prev and new_prev:
        update["previous_proof_message_id"] = new_prev
    if update:
        await bans.update_one({"ban_id": ban_id}, {"$set": update})

    links = {
        **build_link_map(old_chat, new_chat, old_proof, new_proof),
        **build_link_map(old_chat, new_chat, old_prev, new_prev),
    }
    if links and not entry.get("caption_fixed"):
        for new_mid in sorted({m for m in (new_proof, new_prev) if m}):
            await fix_caption_links(client, new_chat, new_mid, links)
            await asyncio.sleep(delay)
        entry["caption_fixed"] = True
        state["done"][ban_id] = entry
        save_state(state_path, state)

    log_mids = {
        int(ban.get("log_message_id") or 0),
        int(ban.get("previous_log_message_id") or 0),
    }
    log_mids.discard(0)
    done_log_mids: Sequence[int] = entry.get("log_edited") or []
    for log_mid in sorted(log_mids):
        if log_mid in done_log_mids:
            continue
        edited, _n = await edit_log_markup(client, bot, logs_chat, log_mid, links)
        entry.setdefault("log_edited", [])
        entry["log_edited"].append(log_mid)
        state["done"][ban_id] = entry
        save_state(state_path, state)
        if edited:
            await asyncio.sleep(delay)

    entry["done"] = True
    state["done"][ban_id] = entry
    save_state(state_path, state)
    return True, f"migrated ban {ban_id}"


async def run(args: argparse.Namespace) -> int:
    """Execute the migration per parsed args. Returns a process exit code."""
    if args.old_proof_chat == args.new_proof_chat:
        print(
            "error: --old-proof-chat and --new-proof-chat must differ", file=sys.stderr
        )
        return 2

    token = os.environ.get("BOT_TOKEN", "").strip()
    mongo_uri = os.environ.get("MONGODB_URI", "").strip()
    db_name = os.environ.get("DB_NAME", "tcbot").strip() or "tcbot"
    try:
        api_id = int(os.environ.get("API_ID", "0"))
    except ValueError:
        api_id = 0
    api_hash = os.environ.get("API_HASH", "").strip()
    missing = [
        name
        for name, val in (
            ("BOT_TOKEN", token),
            ("MONGODB_URI", mongo_uri),
            ("API_ID", str(api_id) if api_id else ""),
            ("API_HASH", api_hash),
        )
        if not val
    ]
    if missing:
        print(f"error: missing env: {', '.join(missing)}", file=sys.stderr)
        return 2

    print("=" * 64)
    print("Proof migration")
    print(f"  old proof chat : {args.old_proof_chat}")
    print(f"  new proof chat : {args.new_proof_chat}")
    print(f"  logs chat      : {args.logs_chat}")
    print(f"  database       : {db_name}")
    print(f"  mode           : {'APPLY' if args.apply else 'DRY-RUN (no writes)'}")
    print("  Stop the bot before --apply: the MTProto login is bot-token based.")
    print("=" * 64)

    mongo = MongoClient(mongo_uri)
    bans = mongo[db_name]["bans"]
    if args.ban_id:
        query: dict = {"ban_id": args.ban_id}
    else:
        query = {
            "$or": [
                {"proof_message_id": {"$gt": 0, "$exists": True}},
                {"previous_proof_message_id": {"$ne": None, "$exists": True}},
            ]
        }
    # * Sync read: this is a one-shot operator script, not the hot path.
    all_bans = list(
        bans.find(query, {"_id": 0}).sort([("timestamp", 1), ("ban_id", 1)])
    )
    state = load_state(args.state)
    pending = ban_ids_pending(all_bans, state)
    if args.limit:
        pending = pending[: args.limit]
    by_id = {str(b.get("ban_id")): b for b in all_bans}
    print(f"  bans with proofs: {len(all_bans)}, pending: {len(pending)}")

    ok = 0
    failures: list[str] = []
    bot = Bot(token)
    try:
        client = Client(
            args.session,
            api_id=api_id,
            api_hash=api_hash,
            bot_token=token,
        )
        await client.start()
        try:
            for ban_id in pending:
                ban = by_id[ban_id]
                try:
                    success, note = await migrate_ban(
                        client=client,
                        bot=bot,
                        bans=bans,
                        ban=ban,
                        old_chat=args.old_proof_chat,
                        new_chat=args.new_proof_chat,
                        logs_chat=args.logs_chat,
                        state=state,
                        state_path=args.state,
                        apply=args.apply,
                        delay=args.delay,
                    )
                    print(f"  [{ban_id}] {note}", flush=True)
                    if success:
                        ok += 1
                    else:
                        failures.append(f"{ban_id}: {note}")
                except Exception as exc:
                    failures.append(f"{ban_id}: {type(exc).__name__}: {exc}")
                    print(
                        f"  [{ban_id}] FAILED: {type(exc).__name__}: {exc}",
                        flush=True,
                    )
                await asyncio.sleep(args.delay)
        finally:
            maybe = client.stop()
            if asyncio.iscoroutine(maybe):
                await maybe
    finally:
        mongo.close()

    print("=" * 64)
    print(f"  done: {ok} ok, {len(failures)} failed")
    for item in failures:
        print(f"    - {item}")
    print(f"  state file: {args.state} (keep it until re-verified)")
    print("=" * 64)
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line flags for the migration run."""
    parser = argparse.ArgumentParser(
        description="Migrate proof messages to a new channel and repoint refs."
    )
    parser.add_argument("--old-proof-chat", type=int, required=True)
    parser.add_argument("--new-proof-chat", type=int, default=DEFAULT_NEW_PROOF_CHAT)
    parser.add_argument("--logs-chat", type=int, required=True)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--session", default="proof_migration")
    parser.add_argument(
        "--apply", action="store_true", help="write; default is dry-run"
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ban-id")
    parser.add_argument("--delay", type=float, default=0.4)
    return parser.parse_args(argv)


def main() -> int:
    """Parse arguments, run the migration, and return the exit code."""
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
