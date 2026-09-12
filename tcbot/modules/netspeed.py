# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Network diagnostics: /ping (alias /p) and /speedtest (alias /st)."""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import TYPE_CHECKING

import certifi
from speedtest import ConfigRetrievalError, Speedtest, SpeedtestHTTPSHandler
from telegram.ext import ContextTypes, MessageHandler

from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters
from tcbot.utils.time_and_date import elapsed_ms, monotonic

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #

_RL_PERIOD_S: int = 60
_RL_CMD_LIMIT: int = 3

# * Upper bound for one Ookla run (best-server + download + upload +
# * share). Normal runs finish well under a minute.
_SPEEDTEST_TIMEOUT: int = 180

# ──────────────────────── Module metadata ───────────────────────── #

__module_name__ = "Netspeed"
__help_text__ = t("netspeed.help.overview")

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        t("netspeed.help.commands.body"),
    ),
    replies.who_section(replies.perm_founder_only(plain=False)),
    replies.where_section(replies.CONTEXT_BOT_OR_GROUP),
    (
        replies.SEC_WHAT,
        t("netspeed.help.what.body"),
    ),
    (
        replies.SEC_EXAMPLES,
        t("netspeed.help.examples.body"),
    ),
]

__help__: replies.HelpEntry = {
    "name": __module_name__,
    "overview": __help_text__,
    "sections": __help_sections__,
}


# ──────────────────────── Size formatter ────────────────────────── #


def _readable_size(size_bytes: float) -> str:
    """Convert a byte count to a human-readable string (B to TB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


# ────────────── Blocking speedtest worker (thread executor) ─────── #

# * Lazily built certifi context shared by every speedtest run in this
# * process. Built once: reading the bundle file per connection is wasteful,
# * and runs are rare (Founder-only, rate-limited).
_SSL_CONTEXT: ssl.SSLContext | None = None


def _install_certifi_context(opener: object) -> None:
    """Point an opener's HTTPS handlers at the certifi bundle, in place.

    speedtest-cli 2.1.x builds its opener with ``context=None``, so every
    HTTPS connection falls back to the system CA store, which fails with
    CERTIFICATE_VERIFY_FAILED on sandboxes without a usable
    /etc/ssl/certs (same environment issue as the MongoDB clients, fixed
    there via ``mongo_client_kwargs``). The library offers no context
    parameter, so patch the handler objects directly; the same opener
    instance is shared by ``Speedtest`` and its ``SpeedtestResults``,
    covering config, servers, download, upload, and share alike.
    Pinned assumption: the ``SpeedtestHTTPSHandler._context`` attribute
    in ``speedtest-cli>=2.1,<3`` (the pinned range in pyproject.toml).
    """
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
    handlers: list = getattr(opener, "handlers", [])
    for handler in handlers:
        if isinstance(handler, SpeedtestHTTPSHandler):
            handler._context = _SSL_CONTEXT


class _CertifiSpeedtest(Speedtest):
    """Speedtest trusting the certifi bundle instead of the system CA store.

    Base ``__init__`` assigns ``self._opener`` before its first
    ``get_config()`` call, so overriding ``get_config`` is the earliest
    hook to patch the opener before any network use (the constructor
    itself performs the failing config fetch).
    """

    def get_config(self) -> dict | None:
        """Fetch config after pointing the opener at the certifi bundle."""
        _install_certifi_context(self._opener)
        return super().get_config()


def _run_speedtest() -> dict:
    """Run a full speedtest synchronously; intended for thread-executor use only."""
    # * Retry config fetch once; Ookla sometimes returns transient 403s.
    for attempt in range(2):
        try:
            st = _CertifiSpeedtest()
            st.get_best_server()
            st.download()
            st.upload()
            st.results.share()
            return st.results.dict()
        except ConfigRetrievalError as exc:
            if attempt == 0:
                log.warning("Speedtest config retrieval failed (attempt 1/2): %s", exc)
            else:
                raise
    return {}


# * Ookla builds the share link as plain http
# * (``http://www.speedtest.net/result/<id>.png`` in speedtest-cli 2.1.x),
# * which Telegram fetches server-side for sendPhoto, so both schemes are
# * accepted and only non-http(s) values fall back to text.
def _share_photo_url(result: dict) -> str | None:
    """Return the Ookla share image URL when it uses http(s), else None."""
    share_url = result.get("share")
    if isinstance(share_url, str) and share_url.startswith(("http://", "https://")):
        return share_url
    return None


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
    try:
        await sent.edit_text(
            t(
                "netspeed.pong.body",
                locale,
                latency=Safe(code(f"{ping_ms:.1f} ms")),
            ),
            parse_mode="MarkdownV2",
        )
    except Exception as exc:
        log.debug("cmd_ping edit failed: %s", exc)


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
        async with asyncio.timeout(_SPEEDTEST_TIMEOUT):
            result: dict = await loop.run_in_executor(None, _run_speedtest)
    except TimeoutError:
        log.warning("Speedtest timed out after %ds", _SPEEDTEST_TIMEOUT)
        try:
            await notice.edit_text(t("netspeed.status.timeout", locale, plain=True))
        except Exception as edit_exc:
            log.debug("cmd_speedtest timeout-edit failed: %s", edit_exc)
        return
    except Exception:
        log.exception("Speedtest failed")
        try:
            await notice.edit_text(t("netspeed.status.failed", locale, plain=True))
        except Exception as edit_exc:
            log.debug("cmd_speedtest failure-edit failed: %s", edit_exc)
        return

    async def _parse_failed() -> None:
        # * KeyError (shape drift) and TypeError (None where a mapping was
        # * expected) both mean the result cannot be rendered honestly;
        # * shared responder so the two except clauses stay identical
        # * without a forbidden tuple-except.
        log.exception("Speedtest result parsing failed")
        try:
            await notice.edit_text(
                t("netspeed.status.parse_failed", locale, plain=True)
            )
        except Exception as edit_exc:
            log.debug("cmd_speedtest parse-fail edit failed: %s", edit_exc)

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
    share_url = _share_photo_url(result)
    if result.get("share") and not share_url:
        log.warning("Speedtest returned non-http(s) share URL; sending text only")
    try:
        if share_url:
            # * Edit the "please wait" notice to the result text and send the
            # * share photo as a separate reply to the original command message,
            # * both in parallel. This avoids deleting the notice (consistent
            # * with the edit pattern used in cmd_ping and other action modules).
            await asyncio.gather(
                notice.edit_text(text, parse_mode="MarkdownV2"),
                msg.reply_photo(share_url),
                return_exceptions=True,
            )
        else:
            await notice.edit_text(text, parse_mode="MarkdownV2")
    except Exception as exc:
        log.debug("cmd_speedtest result edit failed: %s", exc)


# ──────────────────────────── Handlers ──────────────────────────── #

_PING_CMDS = build_prefixed_filters("ping") | build_prefixed_filters("p")
_SPEEDTEST_CMDS = build_prefixed_filters("speedtest") | build_prefixed_filters("st")

__handlers__ = [
    MessageHandler(_PING_CMDS, cmd_ping),
    MessageHandler(_SPEEDTEST_CMDS, cmd_speedtest),
]
