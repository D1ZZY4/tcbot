# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Application lifecycle: build, post-init, handler wiring, and shutdown."""

from __future__ import annotations

import asyncio
import warnings

from telegram import LinkPreviewOptions, Update
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    Defaults,
    TypeHandler,
)

from tcbot import cfg
from tcbot import database as db
from tcbot.database import mtproto as mtproto_mod
from tcbot.database import redis_client
from tcbot.database import scheduler as sched_mod
from tcbot.database.cache import drain_redis_mutations
from tcbot.database.mongos import close as close_mongo
from tcbot.database.mongos import connect, ensure_indexes
from tcbot.modules import get_handlers
from tcbot.modules.helper.decorators import global_rate_limit_handler
from tcbot.modules.helper.workflows.connected_flow import drain_harvest_tasks
from tcbot.runtime.errors import (
    _asyncio_report_tasks,
    _error_handler,
    _make_asyncio_exc_handler,
)
from tcbot.runtime.members import (
    _member_cache_tasks,
    _startup_tasks,
    _update_member_cache,
)
from tcbot.utils import error_reporter
from tcbot.utils import logger as logger_mod
from tcbot.utils.dispatch import drain_tasks
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import (
    API_POOL_SIZE,
    HTTP_CONNECT_TIMEOUT,
    HTTP_POOL_TIMEOUT,
    HTTP_READ_TIMEOUT,
    HTTP_WRITE_TIMEOUT,
)

log = get_logger(__name__)

# * Pool size for the dedicated getUpdates lane (polling mode only).
_UPDATES_POOL_SIZE: int = 4

# * Applied globally via Defaults so every bot message suppresses link preview cards.
_LINK_PREVIEW_DISABLED: LinkPreviewOptions = LinkPreviewOptions(is_disabled=True)

# * PTB handler group IDs: lower number = higher priority.
_HANDLER_GROUP_RATE_LIMITER: int = -1
_HANDLER_GROUP_CACHE: int = 10

# * URL path where Telegram delivers webhook updates.
_WEBHOOK_PATH: str = "/webhook"

# * PTB emits a UserWarning about per_message=False + CallbackQueryHandler when
# * ConversationHandlers are built. Our flows deliberately use per_message=False
# * because approval callbacks must be matchable across multiple messages. The
# * warning is accurate but the behaviour is intentional, so we suppress it here
# * rather than at every call site.
warnings.filterwarnings(
    "ignore",
    message=r"If 'per_message=False', 'CallbackQueryHandler'.*",
    category=UserWarning,
)


async def _warm_hot_caches() -> None:
    """Pre-warm frequently-read L1+L2 caches immediately after startup.

    Step 1 (parallel): get_owner_id + active_groups; both are TwoLevelCache-backed
    so the first command handler gets an L1 hit instead of a cold MongoDB round-trip.

    Step 2 (sequential dep): get_effective_role(owner_id); requires owner_id from
    step 1 and populates the effective_role_cache (L1+L2) for the owner so the first
    command from the owner resolves the role without any DB round-trip.
    """
    try:
        owner_id_r, _ = await asyncio.gather(
            db.users_roles.get_owner_id(),
            db.groups_db.active_groups(),
            return_exceptions=True,
        )
        log.debug("Cache warm-up: owner_id and active_groups pre-loaded into L1+L2.")
        if isinstance(owner_id_r, int):
            await db.users_roles.get_effective_role(owner_id_r)
            log.debug("Cache warm-up: owner effective_role pre-loaded into L1+L2.")
    except Exception as exc:
        log.debug("Cache warm-up failed (non-fatal): %s", exc)


async def _post_init(app: Application) -> None:
    """Connect to MongoDB, ensure indexes, seed owner, start scheduler, and attach error reporter."""
    # * Fail fast on missing MTProto credentials before any side effect
    # * (Mongo connect, index writes): the bot refuses to boot without them
    # * on long-lived transports. Serverless never reaches this function,
    # * so its documented degrade is unaffected.
    if not cfg.mtproto_enabled:
        raise RuntimeError(
            "API_ID/API_HASH are required for MTProto identity resolution; refusing to boot degraded."
        )
    log.info("post_init: connecting to MongoDB...")
    await connect()

    # * Run index creation, owner seeding, and Redis connect in parallel.
    # * All three are safe to run concurrently once the MongoDB client is live.
    log.info("post_init: parallel setup (indexes, owner seed, Redis)...")

    async def _try_redis() -> None:
        if cfg.redis_url:
            try:
                await redis_client.connect(cfg.redis_url)
            except Exception as exc:
                log.warning(
                    "Redis connection failed; running with in-memory cache only: %s",
                    exc,
                )
        else:
            log.info("REDIS_URL not set; in-memory cache only.")

    indexes_r, owner_r, _, _mtproto_r = await asyncio.gather(
        ensure_indexes(),
        db.users_roles.ensure_initial_owner(cfg.initial_owner_id),
        _try_redis(),
        mtproto_mod.start(),
        return_exceptions=True,
    )
    if isinstance(indexes_r, BaseException):
        raise indexes_r
    if isinstance(owner_r, BaseException):
        log.warning("ensure_initial_owner failed (non-fatal): %s", owner_r)
    # * MTProto is mandatory: missing credentials or a login-less session
    # * must abort boot loudly instead of serving numeric-ID displays.
    # * A degraded False (lease held elsewhere) is not fatal: the bot
    # * serves fully on the Bot API without MTProto lookups.
    if isinstance(_mtproto_r, BaseException):
        raise _mtproto_r
    if _mtproto_r is False:
        log.warning(
            "MTProto degraded: another live instance owns the shared session "
            "(or the lease claim failed). Identity lookups run Bot-API-only; "
            "moderation is unaffected."
        )

    # * APScheduler 3.11.3 with MongoDBJobStore - persistent scheduled jobs.
    # * app.bot is live here (post_init runs inside the initialised app), so
    # * the optional enforcement-sync sweep gets a real Bot reference; a
    # * SYNC_INTERVAL_HOURS of 0 keeps the sweep disabled.
    await sched_mod.start(
        cfg.mongodb_uri,
        cfg.db_name,
        cfg.warn_expiry_days,
        bot=app.bot,
        sync_interval_hours=cfg.sync_interval_hours,
    )

    # * Pre-warm hot caches (owner ID + active groups) as a background task so
    # * the first real user command hits L1 instead of going all the way to MongoDB.
    # * Strong reference in _startup_tasks prevents GC before completion (RUF006).
    loop = asyncio.get_running_loop()
    _t = loop.create_task(_warm_hot_caches(), name="tcbot.cache_warmup")
    _startup_tasks.add(_t)
    _t.add_done_callback(_startup_tasks.discard)

    # * Attach live bot to the error reporter (enables Layers 1 + 3)
    # * Owner ID is passed so infra-level errors (Conflict, InvalidToken)
    # * go to the owner's DM instead of the shared logs_errors channel.
    lec, let = cfg.logs_errors
    error_reporter.attach(app.bot, lec, let, owner_id=cfg.initial_owner_id)

    # * Register asyncio-level exception handler (Layer 3)
    loop.set_exception_handler(_make_asyncio_exc_handler(loop))

    log.info("Bot initialised.")
    # * Internal IDs go to DEBUG so they do not appear in default INFO logs.
    log.debug("Owner: %d | LOG_ERRORS: %d", cfg.initial_owner_id, lec)


async def _post_shutdown(app: Application) -> None:
    """Stop APScheduler and close Redis after the application fully shuts down."""
    # * Drain fire-and-forget sets first (bounded): member-cache writes,
    # * startup warm-ups, admin harvests, and log shipping may still use
    # * the database and Telegram below. Each drain is time-boxed and the
    # * survivors are cancelled, so a hung task cannot stall teardown.
    await drain_tasks(_member_cache_tasks, label="member cache")
    await drain_tasks(_startup_tasks, label="startup warm-up")
    await drain_tasks(_asyncio_report_tasks, label="async error reports")
    await drain_harvest_tasks()
    await logger_mod.drain_pending()
    # * Drain first: queued L2 writes must land before the pool closes
    # * underneath them; the gather below runs concurrently otherwise.
    await drain_redis_mutations()
    await asyncio.gather(
        sched_mod.stop(),
        redis_client.close(),
        mtproto_mod.stop(),
        return_exceptions=True,
    )
    # * Close the shared Motor client last: every drain above still writes.
    close_mongo()


def _build_application(*, polling: bool) -> Application:
    """Construct the PTB Application with transport-appropriate connection pool sizes."""
    builder = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        # * Disable link preview on all bot messages globally.
        .defaults(Defaults(link_preview_options=_LINK_PREVIEW_DISABLED))
        # * Process independent updates in parallel (big latency win)
        .concurrent_updates(True)  # noqa: FBT003
        # * HTTP connection pool for outbound API calls (send, edit, delete, etc.)
        .connection_pool_size(API_POOL_SIZE)
        # * HTTP timeouts - generous but bounded so hangs never block the loop
        .read_timeout(HTTP_READ_TIMEOUT)
        .write_timeout(HTTP_WRITE_TIMEOUT)
        .connect_timeout(HTTP_CONNECT_TIMEOUT)
        .pool_timeout(HTTP_POOL_TIMEOUT)
        # * Global Telegram API pacing: ~30 req/s with automatic 429/RetryAfter
        # * backoff.  Works alongside fan_out's semaphore (max 10 concurrent) and
        # * the per-user decorator rate limiter (group -1).
        .rate_limiter(AIORateLimiter())
    )
    if polling:
        # * Dedicated pool for the getUpdates long-polling lane (not used in webhook mode).
        builder = builder.get_updates_connection_pool_size(_UPDATES_POOL_SIZE)
    return builder.build()


def _register_handlers(app: Application) -> None:
    """Attach the global rate limiter, module handlers, cache harvester, and error handler."""
    # * Layer 1: Global per-user rate limiter - runs before every handler (group -1)
    app.add_handler(
        TypeHandler(Update, global_rate_limit_handler),
        group=_HANDLER_GROUP_RATE_LIMITER,
    )

    # * Register all module handlers via tcbot.modules
    for handler in get_handlers():
        app.add_handler(handler)

    # * Low-priority handler: cache every effective_user we observe.
    # * Runs on every update (messages, callback queries, my_chat_member)
    # * so future log messages and mention links resolve to real names.
    app.add_handler(
        TypeHandler(Update, _update_member_cache), group=_HANDLER_GROUP_CACHE
    )

    # * Layer 2: PTB global error handler - catches all unhandled handler exceptions
    app.add_error_handler(_error_handler)
