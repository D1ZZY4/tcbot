# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Network diagnostics: /ping (alias /p) and /speedtest (alias /st)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from speedtest import Speedtest
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.formatter import esc
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #

_RL_PERIOD_S: int = 60
_RL_CMD_LIMIT: int = 3

# ──────────────────────── Module metadata ───────────────────────── #

__module_name__ = "Netspeed"
__help_text__ = (
    "Network diagnostics: ping for Telegram API round-trip latency, "
    "speedtest for full upload and download bandwidth measurement."
)
__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/ping</code> (alias: <code>/p</code>)\n"
        "<code>/speedtest</code> (alias: <code>/st</code>)",
    ),
    (
        replies.SEC_WHO,
        replies.PERM_FOUNDER_ONLY,
    ),
    (
        replies.SEC_WHERE,
        replies.CONTEXT_BOT_OR_GROUP,
    ),
    (
        replies.SEC_WHAT,
        "<b>ping</b>: Measures the round-trip time from the bot to "
        "Telegram's servers.\n"
        "<b>speedtest</b>: Runs a full network speed test and reports "
        "ping, upload, download, bytes transferred, client IP, ISP, "
        "and best-server details.",
    ),
    (
        replies.SEC_EXAMPLES,
        "<code>/ping</code>\n"
        "<code>/p</code>\n"
        "<code>/speedtest</code>\n"
        "<code>/st</code>",
    ),
]


# ──────────────────────── Size formatter ────────────────────────── #


def _readable_size(size_bytes: float) -> str:
    """Convert a byte count to a human-readable string (B to TB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


# ────────────── Blocking speedtest worker (thread executor) ─────── #


def _run_speedtest() -> dict:
    """Run a full speedtest synchronously; intended for thread-executor use only."""
    st = Speedtest()
    st.get_best_server()
    st.download()
    st.upload()
    st.results.share()
    return st.results.dict()


# ──────────────────────── Command handlers ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with Telegram API round-trip latency in milliseconds."""
    msg = update.effective_message
    t0 = time.monotonic()
    sent = await msg.reply_text("Pinging...")
    elapsed_ms = (time.monotonic() - t0) * 1_000
    try:
        await sent.edit_text(
            f"Pong! Round-trip: <code>{elapsed_ms:.1f} ms</code>",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.debug("cmd_ping edit failed: %s", exc)


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_speedtest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a full network speed test and reply with detailed results."""
    msg = update.effective_message
    notice = await msg.reply_text("Running speed test, please wait...")
    try:
        loop = asyncio.get_running_loop()
        result: dict = await loop.run_in_executor(None, _run_speedtest)
    except Exception:
        log.exception("Speedtest failed")
        try:
            await notice.edit_text("Speed test failed. Check the bot logs for details.")
        except Exception as edit_exc:
            log.debug("cmd_speedtest failure-edit failed: %s", edit_exc)
        return

    dl = _readable_size(result["download"] / 8)
    ul = _readable_size(result["upload"] / 8)
    sent_bytes = _readable_size(int(result["bytes_sent"]))
    recv_bytes = _readable_size(int(result["bytes_received"]))
    client = result["client"]
    server = result["server"]

    text = (
        "<b>Speed Test Results</b>\n\n"
        f"<b>Ping:</b> <code>{esc(result['ping'])} ms</code>\n"
        f"<b>Timestamp:</b> <code>{esc(result['timestamp'])}</code>\n"
        f"<b>Download:</b> <code>{esc(dl)}/s</code>\n"
        f"<b>Upload:</b> <code>{esc(ul)}/s</code>\n"
        f"<b>Sent:</b> <code>{esc(sent_bytes)}</code>\n"
        f"<b>Received:</b> <code>{esc(recv_bytes)}</code>\n\n"
        "<b>Client Info</b>\n"
        f"<b>IP:</b> <code>{esc(client['ip'])}</code>\n"
        f"<b>ISP:</b> <code>{esc(client['isp'])}</code>\n"
        f"<b>ISP Rating:</b> <code>{esc(client['isprating'])}</code>\n"
        f"<b>Country:</b> <code>{esc(client['country'])}</code>\n"
        f"<b>Latitude:</b> <code>{esc(client['lat'])}</code>\n"
        f"<b>Longitude:</b> <code>{esc(client['lon'])}</code>\n\n"
        "<b>Server Info</b>\n"
        f"<b>Name:</b> <code>{esc(server['name'])}</code>\n"
        f"<b>Sponsor:</b> <code>{esc(server['sponsor'])}</code>\n"
        f"<b>Latency:</b> <code>{esc(server['latency'])}</code>\n"
        f"<b>Country:</b> <code>{esc(server['country'])}, {esc(server['cc'])}</code>\n"
        f"<b>Latitude:</b> <code>{esc(server['lat'])}</code>\n"
        f"<b>Longitude:</b> <code>{esc(server['lon'])}</code>"
    )

    share_url: str | None = result.get("share")
    try:
        if share_url:
            # * Delete the "please wait" notice and send photo + caption in parallel.
            await asyncio.gather(
                notice.delete(),
                msg.reply_photo(share_url, caption=text, parse_mode="HTML"),
                return_exceptions=True,
            )
        else:
            await asyncio.gather(
                notice.delete(),
                msg.reply_text(text, parse_mode="HTML"),
                return_exceptions=True,
            )
    except Exception as exc:
        log.debug("cmd_speedtest reply failed: %s", exc)
        try:
            await notice.edit_text(text, parse_mode="HTML")
        except Exception as fallback_exc:
            log.debug("cmd_speedtest fallback edit failed: %s", fallback_exc)


# ──────────────────────────── Handlers ──────────────────────────── #

_PING_CMDS = build_prefixed_filters("ping") | build_prefixed_filters("p")
_SPEEDTEST_CMDS = build_prefixed_filters("speedtest") | build_prefixed_filters("st")

__handlers__ = [
    MessageHandler(_PING_CMDS, cmd_ping),
    MessageHandler(_SPEEDTEST_CMDS, cmd_speedtest),
]
