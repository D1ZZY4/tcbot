# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Entry point: python -m tgbot_tcf"""
import logging
import re
import traceback

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from typing import Any, cast


# Application is a heavily-parametrized generic; use a convenient alias for typing
AppT = Application[Any, Any, Any, Any, Any, Any]

from . import BOT_TOKEN, INITIAL_OWNER_ID
from .database import init_db, tc_owners
from .handlers import (
    admins,
    affiliate,
    appeal,
    ban,
    broadcast,
    checks,
    help as help_h,
    links,
    lists,
    maintenance,
    menu,
    sync,
    welcome,
)
from .keepalive import start_keepalive
from .utils.prefix import dispatch_alt_prefix, register_command

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    tb = (
        "".join(traceback.format_exception(type(err), err, err.__traceback__))
        if err
        else ""
    )
    logger.error("Update %s caused error: %s\n%s", update, err, tb)


def _add(app: AppT, aliases: list[str], cb: Any) -> None:
    """Register a command callback for `/`, `.`, and `!` prefixes."""
    app.add_handler(CommandHandler(aliases, cb))
    for name in aliases:
        register_command(name, cb)


async def post_init(app: Any) -> None:
    await init_db()
    if await tc_owners.find_one({}) is None:
        await tc_owners.insert_one({"user_id": INITIAL_OWNER_ID})
        logger.info("Seeded initial TC Owner (id=%s)", INITIAL_OWNER_ID)
    me = await app.bot.get_me()
    logger.info("Bot @%s started (id=%s)", me.username, me.id)


def build_app() -> AppT:
    app = Application.builder().token(BOT_TOKEN).post_init(cast(Any, post_init)).build()

    # ----- Help / start -----
    _add(app, ["start"], help_h.cmd_start)
    _add(app, ["help", "commands"], help_h.cmd_help)

    # ----- Listings / stats / links -----
    _add(app, ["tcfgroups", "groups", "listtc"], lists.cmd_fedgroups)
    _add(app, ["tcstats", "stats", "tcinfo"], lists.cmd_fedstats)
    _add(app, ["tclinks", "links", "tcconfig"], links.cmd_fedlinks)

    # ----- Ban status queries -----
    _add(app, ["checkme", "myban", "amibanned"], checks.cmd_checkme)
    _add(app, ["baninfo", "checkban", "banstatus"], checks.cmd_baninfo)

    # ----- Group affiliation -----
    _add(app, ["jointc", "requestjoin", "applytc"], affiliate.cmd_joinfed)
    _add(app, ["detc", "leavetc", "untc"], affiliate.cmd_defed)
    _add(app, ["rmtc", "removetc", "deletetc"], affiliate.cmd_rmfed)

    # ----- Admin management -----
    _add(app, ["tcpromote", "promote", "tcfpromote"], admins.cmd_promote)
    _add(app, ["tcdemote", "demote", "tcfdemote"], admins.cmd_demote)
    _add(app, ["tctransfer", "transfer", "tcowner"], admins.cmd_transfer_owner)
    _add(
        app,
        ["tcpromoterequests", "promoreqs", "tcreqs"],
        admins.cmd_promo_requests,
    )

    # ----- Bans -----
    _add(app, ["tcban", "ban", "tcfban"], ban.cmd_cban)
    _add(app, ["tcunban", "unban", "tcfunban"], ban.cmd_cunban)

    # ----- Broadcast / sync -----
    _add(app, ["tcbroadcast", "broadcast", "tcannounce"], broadcast.cmd_broadcast)
    _add(app, ["tcsync", "syncban", "tcfbanall"], sync.cmd_syncban)

    # ----- Maintenance -----
    _add(app, ["leaveall", "exitall", "tcleave"], maintenance.cmd_leaveall)
    _add(app, ["cleanup", "purge", "tcclean"], maintenance.cmd_cleanup)

    # ----- Alt-prefix dispatcher (`.` and `!` prefixes) -----
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(re.compile(r"^[.!]")),
            dispatch_alt_prefix,
        )
    )

    # ----- Group affiliation: bot-add prompt + my_chat_member tracking -----
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS, affiliate.on_new_chat_members
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            affiliate.on_affiliation_callback, pattern=r"^tc_(join|cancel)$"
        )
    )
    app.add_handler(
        ChatMemberHandler(
            affiliate.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    # ----- Welcome / Goodbye in MAIN_GROUP and EXEC_GROUP -----
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome.on_member_join
        ),
        group=1,
    )
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER, welcome.on_member_left
        ),
        group=1,
    )

    # ----- Start menu / interactive help / information / privacy callbacks -----
    app.add_handler(
        CallbackQueryHandler(
            menu.on_menu_callback,
            pattern=r"^(menu_|info_|help_)",
        )
    )

    # ----- Ban proof flow -----
    app.add_handler(
        CallbackQueryHandler(ban.on_cancel_proof, pattern=r"^cancel_proof$")
    )
    app.add_handler(
        MessageHandler(
            filters.ATTACHMENT & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
            ban.on_proof_message,
        )
    )

    # ----- Appeal flow -----
    app.add_handler(
        CallbackQueryHandler(appeal.on_cancel_appeal, pattern=r"^cancel_appeal$")
    )
    app.add_handler(
        CallbackQueryHandler(
            appeal.on_appeal_review, pattern=r"^appeal_(approve|reject)_"
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            appeal.on_appeal_message,
        )
    )

    # ----- Promotion request review callbacks -----
    app.add_handler(
        CallbackQueryHandler(
            admins.on_promote_callback, pattern=r"^(approve_promote_|reject_promote_)"
        )
    )

    app.add_error_handler(on_error)
    return app


def main() -> None:
    start_keepalive()
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
