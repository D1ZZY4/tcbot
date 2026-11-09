# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Network diagnostics: /ping (alias /p) and /speedtest (alias /st)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import math
import os
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
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

# * Upper bound for one full bandwidth run (config + servers + ping +
# * download + upload). Slow links finish well under this; the handler
# * bounds the whole run so a hung route cannot stall moderation traffic.
_SPEEDTEST_TIMEOUT: int = 180

_SPEEDTEST_CONFIG_URL: str = "https://www.speedtest.net/speedtest-config.php"
_SPEEDTEST_SERVERS_URL: str = "https://www.speedtest.net/speedtest-servers-static.php"
# * Per-request ceilings inside the executor: the whole-run timeout above
# * still applies, these only bound individual stalled requests.
_HTTP_TIMEOUT_S: int = 30
# * Bot-bounded HTTP sizes: a subset of the speedtest.net HTTP sizes so one
# * run stays near 10 MB per direction even on slow links. The socket
# * variants advertised in config are not used; the HTTP path needs only
# * the standard library.
_DOWNLOAD_SIZES: list[int] = [350, 500, 750, 1000]
_UPLOAD_SIZES: list[int] = [262_144, 524_288, 1_048_576]
_DOWNLOAD_THREADS: int = 4
_UPLOAD_THREADS: int = 4
_CLOSEST_SERVERS: int = 5
_PING_SAMPLES: int = 3

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


# * speedtest.net rejects generic agents on config/servers (403). The
# * Ookla agent is the only one currently accepted for all endpoints.
_USER_AGENT: str = "Ookla/1.2.0 (android; Dalvik/2.1.0/Linux; Android)"


def _get_bytes(url: str, *, data: bytes | None = None) -> tuple[bytes, dict[str, str]]:
    """Fetch one URL synchronously, trusting the certifi bundle.

    Runs only inside the thread executor (see :func:`_run_speedtest`).
    ``data=None`` issues a GET; bytes issue a POST. Returns the body and
    the response headers so the trace parser can read them. A 307 POST
    redirect (HTTP server upgrade to HTTPS) is retried explicitly because
    the default opener resets on POST redirects.
    """
    current_url = url
    current_data = data
    for _ in range(3):
        context = ssl.create_default_context(cafile=certifi.where())
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context)
        )
        headers = {"User-Agent": _USER_AGENT, "Cache-Control": "no-cache"}
        if current_data is not None:
            headers["Content-Length"] = str(len(current_data))
        request = urllib.request.Request(
            current_url, data=current_data, headers=headers
        )
        try:
            with opener.open(request, timeout=_HTTP_TIMEOUT_S) as response:
                return response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            if exc.code != 307 or current_data is None:
                raise
            location = exc.headers.get("Location") if exc.headers else None
            if not location:
                raise
            current_url = location
    raise RuntimeError("speedtest redirect limit exceeded")


def _parse_xml(blob: bytes, what: str) -> ET.Element:
    """Parse one XML document, raising a clear failure on malformed input."""
    try:
        return ET.fromstring(blob.decode("utf-8", "replace"))
    except ET.ParseError as exc:
        raise RuntimeError(f"malformed speedtest {what}: {exc}") from exc


def _distance_km(origin: tuple[float, float], dest: tuple[float, float]) -> float:
    """Great-circle distance between two [lat, lon] points."""
    lat1, lon1 = origin
    lat2, lon2 = dest
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + math.cos(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) * math.sin(dlon / 2)
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fetch_config() -> tuple[dict[str, str], set[int], int]:
    """Return (client, ignore_ids, threadcount) from speedtest-config.php."""
    blob, _ = _get_bytes(_SPEEDTEST_CONFIG_URL)
    root = _parse_xml(blob, "config")
    client_el = root.find("client")
    if client_el is None:
        raise RuntimeError("speedtest config has no client")
    client = dict(client_el.attrib)
    server_cfg = root.find("server-config")
    ignore: set[int] = set()
    threadcount = 4
    if server_cfg is not None:
        raw_ignore = server_cfg.attrib.get("ignoreids", "")
        for part in raw_ignore.split(","):
            part = part.strip()
            if part:
                try:
                    ignore.add(int(part))
                except ValueError:
                    continue
        try:
            threadcount = int(server_cfg.attrib.get("threadcount", "4"))
        except ValueError:
            threadcount = 4
    return client, ignore, max(1, threadcount)


def _fetch_servers(threadcount: int, ignore: set[int]) -> list[dict[str, str]]:
    """Return the server list in document order (geosorted by the caller)."""
    url = f"{_SPEEDTEST_SERVERS_URL}?threads={threadcount}"
    blob, _ = _get_bytes(url)
    root = _parse_xml(blob, "servers")
    servers: list[dict[str, str]] = []
    servers_el = root.find("servers")
    candidates = list(servers_el.findall("server")) if servers_el is not None else []
    if not candidates:
        candidates = list(root.findall("server"))
    for el in candidates:
        attrib = dict(el.attrib)
        try:
            sid = int(attrib.get("id", "0"))
        except ValueError:
            continue
        if sid in ignore:
            continue
        if not attrib.get("url"):
            continue
        servers.append(attrib)
    return servers


def _closest_servers(
    servers: list[dict[str, str]], client: dict[str, str]
) -> list[dict[str, str]]:
    """Take the nearest servers by great-circle distance from the client."""
    try:
        origin = (float(client["lat"]), float(client["lon"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError("speedtest client location unknown") from exc
    scored: list[tuple[float, dict[str, str]]] = []
    for server in servers:
        try:
            dest = (float(server["lat"]), float(server["lon"]))
        except KeyError, ValueError, TypeError:
            continue
        scored.append((_distance_km(origin, dest), server))
    scored.sort(key=lambda item: item[0])
    return [server for _, server in scored[:_CLOSEST_SERVERS]]


def _server_base(server: dict[str, str]) -> str:
    """Return the speedtest base directory for one server URL."""
    url = server["url"]
    if "/upload.php" in url:
        return url.rsplit("/upload.php", 1)[0]
    return url.rstrip("/")


def _ping_server(base: str) -> float:
    """Average latency over small probes; raises when no probe succeeds."""
    samples: list[float] = []
    for i in range(_PING_SAMPLES):
        stamp = int(monotonic() * 1000)
        try:
            start = monotonic()
            blob, _ = _get_bytes(f"{base}/latency.txt?x={stamp}.{i}")
            if blob.strip() != b"test=test":
                continue
            samples.append(elapsed_ms(start))
        except Exception:
            continue
    if not samples:
        raise RuntimeError("speedtest latency unreachable")
    return sum(samples) / len(samples)


def _pick_best(
    closest: list[dict[str, str]],
) -> tuple[dict[str, str], float, str]:
    """Pick the lowest-latency server; returns (server, ping_ms, base)."""
    results: list[tuple[float, dict[str, str], str]] = []
    for server in closest:
        base = _server_base(server)
        try:
            ping_ms = _ping_server(base)
        except Exception:
            continue
        results.append((ping_ms, server, base))
    if not results:
        raise RuntimeError("speedtest best server unreachable")
    results.sort(key=lambda item: item[0])
    ping_ms, server, base = results[0]
    return server, ping_ms, base


def _download(base: str) -> tuple[float, int]:
    """Concurrent download over the bounded size subset; returns (bps, bytes)."""
    urls: list[str] = []
    for size in _DOWNLOAD_SIZES:
        for _ in range(_DOWNLOAD_THREADS):
            stamp = int(monotonic() * 1000)
            urls.append(f"{base}/random{size}x{size}.jpg?r={stamp}")

    def _fetch(one: str) -> int:
        blob, _ = _get_bytes(one)
        return len(blob)

    start = monotonic()
    total = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=_DOWNLOAD_THREADS) as pool:
        for count in pool.map(_fetch, urls):
            total += count
    elapsed_s = max(monotonic() - start, 0.001)
    return total / elapsed_s * 8.0, total


def _upload(base: str) -> tuple[float, int]:
    """Concurrent upload over the bounded size subset; returns (bps, bytes)."""
    tasks: list[int] = []
    for size in _UPLOAD_SIZES:
        tasks.extend([size] * _UPLOAD_THREADS)

    def _post(size: int) -> int:
        body = os.urandom(size)
        _get_bytes(f"{base}/upload.php", data=body)
        return size

    start = monotonic()
    total = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=_UPLOAD_THREADS) as pool:
        for count in pool.map(_post, tasks):
            total += count
    elapsed_s = max(monotonic() - start, 0.001)
    return total / elapsed_s * 8.0, total


def _run_speedtest() -> dict:
    """Run a full test synchronously; intended for thread-executor use only.

    No provider dependency remains: config, server list, latency,
    download, and upload come from speedtest.net over the standard
    library. The returned dict keeps the shape the result renderer
    consumes (`client`/`server`/`bytes_*` fields), so replies render
    identically.
    """
    client, ignore, threadcount = _fetch_config()
    servers = _fetch_servers(threadcount, ignore)
    if not servers:
        raise RuntimeError("speedtest server list empty")
    closest = _closest_servers(servers, client)
    if not closest:
        raise RuntimeError("speedtest no usable servers")
    server, ping_ms, base = _pick_best(closest)
    download_bps, bytes_received = _download(base)
    upload_bps, bytes_sent = _upload(base)
    return {
        "download": download_bps,
        "upload": upload_bps,
        "ping": ping_ms,
        "timestamp": str(int(monotonic())),
        "bytes_sent": bytes_sent,
        "bytes_received": bytes_received,
        "client": {
            "ip": client.get("ip", "N/A"),
            "isp": client.get("isp", "N/A"),
            "isprating": client.get("isprating", "N/A"),
            "country": client.get("country", "N/A"),
            "lat": client.get("lat", "N/A"),
            "lon": client.get("lon", "N/A"),
        },
        "server": {
            "name": server.get("name", "N/A"),
            "sponsor": server.get("sponsor", "N/A"),
            "latency": ping_ms,
            "country": server.get("country", "N/A"),
            "cc": server.get("cc", "N/A"),
            "lat": server.get("lat", "N/A"),
            "lon": server.get("lon", "N/A"),
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
        # * A bad route can hang the measurement for minutes; bound the
        # * whole run so the handler (and its executor thread) cannot stall
        # * forever.
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
