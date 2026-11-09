# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Network diagnostics: /ping (alias /p) and /speedtest (alias /st)."""

from __future__ import annotations

import asyncio
import os
import ssl
import urllib.request
from typing import TYPE_CHECKING

import certifi
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_edit
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters
from tcbot.utils.time_and_date import elapsed_ms, monotonic

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #

_RL_PERIOD_S: int = 60
_RL_CMD_LIMIT: int = 3

# * Upper bound for one full bandwidth run (latency probe + download +
# * upload + trace). Slow links finish well under this; the handler bounds
# * the whole run so a hung route cannot stall moderation traffic.
_SPEEDTEST_TIMEOUT: int = 180

# * Fixed payloads for bandwidth measurement. 10 MB lands in a few
# * seconds on a healthy link without being unkind to the endpoints.
_SPEEDTEST_BYTES: int = 10_000_000
_SPEEDTEST_ENDPOINT: str = "https://speed.cloudflare.com"
# * Per-request ceilings inside the executor: the whole-run timeout above
# * still applies, these only bound individual stalled requests.
_HTTP_TIMEOUT_S: int = 30

# ──────────────────────── Module metadata ───────────────────────── #

__module_name__ = "Netspeed"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("netspeed.help.overview", locale)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("netspeed.help.commands.body", locale),
        ),
        replies.who_section(replies.perm_founder_only(locale, plain=False), locale),
        replies.where_section(replies.context_bot_or_group(locale), locale),
        (
            replies.sec_what(locale),
            t("netspeed.help.what.body", locale),
        ),
        (
            replies.sec_examples(locale),
            t("netspeed.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────────────── Size formatter ────────────────────────── #


def _readable_size(size_bytes: float) -> str:
    """Convert a byte count to a human-readable string (B to TB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


# ────────────── Blocking speedtest worker (thread executor) ─────── #


def _get_bytes(url: str, *, data: bytes | None = None) -> tuple[bytes, dict[str, str]]:
    """Fetch one URL synchronously, trusting the certifi bundle.

    Runs only inside the thread executor (see :func:`_run_speedtest`).
    ``data=None`` issues a GET; bytes issue a POST. Returns the body and
    the response headers so the trace parser can read them.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, data=data)
    with opener.open(request, timeout=_HTTP_TIMEOUT_S) as response:
        return response.read(), dict(response.headers)


def _fetch_trace() -> dict[str, str]:
    """Fetch Cloudflare's trace endpoint; returns its key=value fields."""
    blob, _ = _get_bytes(f"{_SPEEDTEST_ENDPOINT}/cdn-cgi/trace")
    kv: dict[str, str] = {}
    for line in blob.decode("utf-8", "replace").split("\n"):
        if "=" in line:
            key, value = line.split("=", 1)
            kv[key] = value
    return kv


def _run_speedtest() -> dict:
    """Run a full bandwidth test synchronously; intended for thread-executor use only.

    No provider dependency remains: latency, download, upload, and the
    client IP/country come from the Cloudflare speed endpoints, which
    teams already allow outbound. The returned dict keeps the Ookla shape
    the result renderer consumes (`client`/`server`/`bytes_*` fields), so
    replies render identically. Geodata the endpoints do not provide
    (ISP, coordinates) render as "N/A" rather than a fabricated value.
    """
    latency_start = monotonic()
    _get_bytes(f"{_SPEEDTEST_ENDPOINT}/__down?bytes=1000")
    ping_ms = elapsed_ms(latency_start)

    download_start = monotonic()
    blob, _ = _get_bytes(f"{_SPEEDTEST_ENDPOINT}/__down?bytes={_SPEEDTEST_BYTES}")
    download_elapsed_s = max(monotonic() - download_start, 0.001)
    download_bps = len(blob) / download_elapsed_s * 8

    body = os.urandom(_SPEEDTEST_BYTES)
    upload_start = monotonic()
    _get_bytes(f"{_SPEEDTEST_ENDPOINT}/__up", data=body)
    upload_elapsed_s = max(monotonic() - upload_start, 0.001)
    upload_bps = len(body) / upload_elapsed_s * 8

    trace = _fetch_trace()
    colo = trace.get("colo", "N/A")
    client_ip = trace.get("ip", "N/A")
    # * Named to keep the documented rendering path ("Ookla shape") working
    # * unchanged; the values honestly describe a Cloudflare measurement.
    return {
        "download": download_bps,
        "upload": upload_bps,
        "ping": ping_ms,
        "timestamp": str(int(monotonic())),
        "bytes_sent": len(body),
        "bytes_received": len(blob),
        "client": {
            "ip": client_ip,
            "isp": "N/A",
            "isprating": "N/A",
            "country": colo,
            "lat": "N/A",
            "lon": "N/A",
        },
        "server": {
            "name": "Cloudflare",
            "sponsor": "N/A",
            "latency": ping_ms,
            "country": colo,
            "cc": colo,
            "lat": "N/A",
            "lon": "N/A",
        },
        "share": None,
    }


# ──────────────────────── Command handlers ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with Telegram API round-trip latency in milliseconds."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    t0 = monotonic()
    try:
        sent = await msg.reply_text(t("netspeed.status.pinging", locale, plain=True))
    except Exception as exc:
        log.debug("cmd_ping initial reply failed: %s", exc)
        return
    ping_ms = elapsed_ms(t0)
    await safe_edit(
        sent,
        t(
            "netspeed.pong.body",
            locale,
            latency=Safe(code(f"{ping_ms:.1f} ms")),
        ),
        log_level="debug",
        log_label="cmd_ping",
        catch_all=True,
    )


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_speedtest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a full network speed test and reply with detailed results."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    try:
        notice = await msg.reply_text(t("netspeed.status.running", locale, plain=True))
    except Exception as exc:
        log.debug("cmd_speedtest initial reply failed: %s", exc)
        return
    try:
        loop = asyncio.get_running_loop()
        # * Ookla can hang for minutes on a bad route; bound the whole run
        # * so the handler (and its executor thread) cannot stall forever.
        # * The timeout only abandons the wait: the executor thread itself
        # * runs to completion in the background (documented limitation).
        async with asyncio.timeout(_SPEEDTEST_TIMEOUT):
            result: dict = await loop.run_in_executor(None, _run_speedtest)
    except TimeoutError:
        log.warning("Speedtest timed out after %ds", _SPEEDTEST_TIMEOUT)
        await safe_edit(
            notice,
            t("netspeed.status.timeout", locale, plain=True),
            parse_mode=None,
            log_level="debug",
            log_label="cmd_speedtest timeout-edit",
            catch_all=True,
        )
        return
    except Exception:
        log.exception("Speedtest failed")
        await safe_edit(
            notice,
            t("netspeed.status.failed", locale, plain=True),
            parse_mode=None,
            log_level="debug",
            log_label="cmd_speedtest failure-edit",
            catch_all=True,
        )
        return

    async def _parse_failed() -> None:
        # * KeyError (shape drift) and TypeError (None where a mapping was
        # * expected) both mean the result cannot be rendered honestly;
        # * shared responder so the two except clauses stay identical
        # * without a forbidden tuple-except.
        log.exception("Speedtest result parsing failed")
        await safe_edit(
            notice,
            t("netspeed.status.parse_failed", locale, plain=True),
            parse_mode=None,
            log_level="debug",
            log_label="cmd_speedtest parse-fail",
            catch_all=True,
        )

    try:
        dl = _readable_size(result["download"] / 8)
        ul = _readable_size(result["upload"] / 8)
        sent_bytes = _readable_size(int(result["bytes_sent"]))
        recv_bytes = _readable_size(int(result["bytes_received"]))
        client = result["client"]
        server = result["server"]

        text = (
            f"{t('netspeed.result.title', locale)}\n\n"
            f"{t('netspeed.result.field.ping', locale, value=Safe(code(str(result['ping']) + ' ms')))}\n"
            f"{t('netspeed.result.field.timestamp', locale, value=Safe(code(str(result['timestamp']))))}\n"
            f"{t('netspeed.result.field.download', locale, value=Safe(code(dl + '/s')))}\n"
            f"{t('netspeed.result.field.upload', locale, value=Safe(code(ul + '/s')))}\n"
            f"{t('netspeed.result.field.sent', locale, value=Safe(code(sent_bytes)))}\n"
            f"{t('netspeed.result.field.received', locale, value=Safe(code(recv_bytes)))}\n\n"
            f"{t('netspeed.result.client', locale)}\n"
            f"{t('netspeed.result.field.ip', locale, value=Safe(code(str(client['ip']))))}\n"
            f"{t('netspeed.result.field.isp', locale, value=Safe(code(str(client['isp']))))}\n"
            f"{t('netspeed.result.field.isp_rating', locale, value=Safe(code(str(client.get('isprating', 'N/A')))))}\n"
            f"{t('netspeed.result.field.country', locale, value=Safe(code(str(client['country']))))}\n"
            f"{t('netspeed.result.field.latitude', locale, value=Safe(code(str(client['lat']))))}\n"
            f"{t('netspeed.result.field.longitude', locale, value=Safe(code(str(client['lon']))))}\n\n"
            f"{t('netspeed.result.server', locale)}\n"
            f"{t('netspeed.result.field.name', locale, value=Safe(code(str(server['name']))))}\n"
            f"{t('netspeed.result.field.sponsor', locale, value=Safe(code(str(server.get('sponsor', 'N/A')))))}\n"
            f"{t('netspeed.result.field.latency', locale, value=Safe(code(str(server['latency']))))}\n"
            f"{t('netspeed.result.field.country', locale, value=Safe(code(str(server['country']) + ', ' + str(server['cc']))))}\n"
            f"{t('netspeed.result.field.latitude', locale, value=Safe(code(str(server['lat']))))}\n"
            f"{t('netspeed.result.field.longitude', locale, value=Safe(code(str(server['lon']))))}"
        )
    except KeyError:
        await _parse_failed()
        return
    except TypeError:
        await _parse_failed()
        return
    await safe_edit(
        notice,
        text,
        log_level="debug",
        log_label="cmd_speedtest result",
        catch_all=True,
    )


# ──────────────────────────── Handlers ──────────────────────────── #

_PING_CMDS = build_prefixed_filters("ping") | build_prefixed_filters("p")
_SPEEDTEST_CMDS = build_prefixed_filters("speedtest") | build_prefixed_filters("st")

__handlers__ = [
    MessageHandler(_PING_CMDS, cmd_ping),
    MessageHandler(_SPEEDTEST_CMDS, cmd_speedtest),
]
