# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Process entry: webhook transport, fatal banner, and main startup."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
import traceback

from telegram import Update
from telegram.ext import Application

from tcbot import cfg
from tcbot.alive import register_webhook, start_keepalive
from tcbot.runtime.lifecycle import (
    _WEBHOOK_PATH,
    _build_application,
    _post_init,
    _post_shutdown,
    _register_handlers,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.logger import setup as setup_logging

log = get_logger(__name__)

# * Width of the fatal-error border printed to stderr.
_FATAL_BORDER_WIDTH: int = 70

# * Fatal banner color (same red as ERROR level). Always on, like every
# * BotLogFormatter line: startup failures must be visible on any terminal,
# * and there is no log configuration yet to consult for a preference.
_FATAL_RED: str = "\033[38;5;203m"
_FATAL_RESET: str = "\033[0m"


async def _run_webhook_mode(app: Application) -> None:
    """Run PTB in webhook mode using Flask (alive.py) as the webhook receiver.

    Lifecycle:
    0. Signal handlers registered immediately to close the SIGTERM race window.
    1. app.initialize() -> triggers _post_init (MongoDB, Redis, APScheduler, etc.)
    2. app.start()      -> starts the PTB update dispatcher
    3. set_webhook()    -> registers the public URL with Telegram
    4. get_webhook_info() -> verifies registration; fails fast on mismatch
    5. register_webhook() -> wires Flask's /webhook route to PTB's update_queue
    6. wait for SIGTERM / SIGINT
    7. Finally: delete_webhook(), app.stop(), app.shutdown() (-> _post_shutdown)
    """
    full_url = f"{cfg.webhook_url}{_WEBHOOK_PATH}"
    secret = cfg.webhook_secret

    # * Register signal handlers at the earliest possible moment.  If we wait
    # * until after _post_init + app.start() + set_webhook() the bot is exposed
    # * to a ~500 ms window where a SIGTERM would bypass the graceful shutdown
    # * path entirely (no delete_webhook, no app.stop, no _post_shutdown).
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    with contextlib.suppress(NotImplementedError):
        # * Windows does not support add_signal_handler; suppress gracefully.
        loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
        loop.add_signal_handler(signal.SIGINT, shutdown_event.set)

    async with app:
        # * PTB's Application.initialize() (called by __aenter__) does NOT invoke
        # * post_init - that callback is only called by run_polling/run_webhook.
        # * We call it explicitly here so MongoDB, Redis, APScheduler, and the
        # * error reporter are initialised before any update is processed.
        await _post_init(app)

        # * app.start() must be called after post_init so the dispatcher starts
        # * with all subsystems already connected.
        await app.start()

        try:
            log.info("Registering webhook at %s ...", full_url)
            await app.bot.set_webhook(
                url=full_url,
                secret_token=secret,
                allowed_updates=list(Update.ALL_TYPES),
                drop_pending_updates=True,
            )

            # * Fail fast if Telegram did not accept the registration.
            info = await app.bot.get_webhook_info()
            if info.url != full_url:
                log.critical(
                    "Webhook registration failed: expected %r, got %r. "
                    "Check WEBHOOK_URL and that the endpoint is reachable from Telegram.",
                    full_url,
                    info.url,
                )
                raise RuntimeError(
                    f"Webhook URL mismatch after set_webhook: {info.url!r} != {full_url!r}"
                )

            log.info(
                "Webhook active. Pending updates: %d | Max connections: %s",
                info.pending_update_count,
                info.max_connections,
            )

            # * Wire Flask's POST /webhook route to PTB's asyncio update_queue.
            # * loop is already obtained above (before async with app:).
            register_webhook(app.update_queue, loop, secret, app.bot)

            log.info("Bot running in webhook mode. Waiting for updates...")
            await shutdown_event.wait()

        except asyncio.CancelledError:
            log.info("Webhook mode cancelled.")
        finally:
            log.info("Webhook mode shutting down...")
            try:
                await app.bot.delete_webhook(drop_pending_updates=False)
            except Exception as exc:
                log.debug("delete_webhook failed during shutdown (non-fatal): %s", exc)
            await app.stop()
            # * PTB's Application.shutdown() does NOT invoke post_shutdown - that
            # * callback is only called by run_polling/run_webhook.  Call explicitly.
            await _post_shutdown(app)

    # * app.shutdown() (PTB internal teardown) is called by __aexit__.
    log.info("Bot shutdown complete.")


def _print_fatal(stage: str, exc: BaseException) -> None:
    """Print a fatal startup error with stage label and full traceback to stderr.

    Uses ``print`` intentionally: this runs before the event loop and logging
    are available, so stderr is the only reliable output path.
    """
    border = "=" * _FATAL_BORDER_WIDTH
    print(f"\n{_FATAL_RED}{border}", file=sys.stderr)
    print(f" FATAL STARTUP ERROR in stage: {stage}", file=sys.stderr)
    print(f" {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"{border}", file=sys.stderr)
    # * Render through format_exception so the traceback inherits the banner
    # * color instead of printing plain: every startup failure line is red.
    tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(f"{_FATAL_RED}{tb_text}{_FATAL_RESET}", file=sys.stderr, end="")
    print(f"{border}{_FATAL_RESET}", file=sys.stderr)


def main() -> None:
    """Configure and start the PTB application in webhook or polling mode."""
    # * Each stage is wrapped so any failure prints a clear stage + traceback before exit.
    stage = "logging setup"
    try:
        setup_logging(level=cfg.log_level)
        log.info("Starting %s bot...", cfg.community_name)

        stage = "keepalive server"
        start_keepalive()

        stage = "PTB application build"
        use_webhook = cfg.is_webhook_mode
        app: Application = _build_application(polling=not use_webhook)

        stage = "handler registration"
        _register_handlers(app)

        if use_webhook:
            log.info(
                "Webhook mode detected (URL: %s). Starting webhook transport...",
                cfg.webhook_url,
            )
            stage = "webhook"
            asyncio.run(_run_webhook_mode(app))
        else:
            # * Polling fallback: only for local development where no public URL exists.
            # * Accepted risk: documented in the scheduler and deployment docs.
            log.warning(
                "No WEBHOOK_URL or REPLIT_DEV_DOMAIN found. "
                "Falling back to long-polling (local development only). "
                "Do not use polling mode in production."
            )
            log.info("Starting long-polling...")
            stage = "polling"
            # * Bounded bootstrap retries: -1 would hang forever on a network
            # * partition, invisible to the run-bot watchdog (which restarts on
            # * death, not on hangs). InvalidToken still aborts immediately
            # * inside PTB (never retried), so this only bounds transient
            # * network failures before the loud crash-and-restart path below.
            app.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                bootstrap_retries=5,
            )
    except SystemExit:
        # * Module discovery uses SystemExit on failure; logging already reported the cause.
        raise
    except KeyboardInterrupt:
        log.info("Shutdown requested (KeyboardInterrupt).")
    except BaseException as exc:
        _print_fatal(stage, exc)
        raise SystemExit(1) from exc
