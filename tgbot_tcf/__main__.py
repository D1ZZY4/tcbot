"""Entry point: python -m tgbot_tcf"""
import asyncio
import logging
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

from .config import BOT_TOKEN
from .db import init_db
from .handlers import admins
from .handlers import affiliate
from .handlers import appeal
from .handlers import ban
from .handlers import broadcast
from .handlers import checks
from .handlers import help as help_h
from .handlers import lists
from .handlers import maintenance
from .handlers import menu
from .handlers import sync
from .keepalive import start_keepalive

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__)) if err else ""
    logger.error("Update %s caused error: %s\n%s", update, err, tb)


def _add(app: Application, aliases: list[str], cb) -> None:
    app.add_handler(CommandHandler(aliases, cb))


async def post_init(app: Application) -> None:
    await init_db()
    me = await app.bot.get_me()
    logger.info("Bot @%s started (id=%s)", me.username, me.id)


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Help / start / about
    _add(app, ["help", "commands"], help_h.cmd_help)
    _add(app, ["start"], help_h.cmd_start)
    _add(app, ["about", "tcfabout", "fedabout"], help_h.cmd_about)

    # Listings
    _add(app, ["fedgroups", "groups", "listfed"], lists.cmd_fedgroups)
    _add(app, ["fedstats", "stats", "fedinfo"], lists.cmd_fedstats)
    _add(app, ["fedchannels", "channels", "fedconfig"], lists.cmd_fedchannels)

    # Status
    _add(app, ["checkme", "myban", "amibanned"], checks.cmd_checkme)
    _add(app, ["baninfo", "checkban", "banstatus"], checks.cmd_baninfo)

    # Affiliation
    _add(app, ["joinfed", "requestjoin", "applyfed"], affiliate.cmd_joinfed)
    _add(app, ["defed", "leavefed", "unfed"], affiliate.cmd_defed)
    _add(app, ["rmfed", "removefed", "deletefed"], affiliate.cmd_rmfed)

    # Admin management (owner)
    _add(app, ["cpromote", "compromote", "fpromote"], admins.cmd_promote)
    _add(app, ["cdemote", "comdemote", "fdemote"], admins.cmd_demote)
    _add(app, ["transferowner", "tfowner", "fedowner"], admins.cmd_transfer_owner)

    # Bans
    _add(app, ["cban", "comban", "fban"], ban.cmd_cban)
    _add(app, ["cunban", "comunban", "funban"], ban.cmd_cunban)

    # Broadcast / sync
    _add(app, ["broadcast", "announce", "fcast"], broadcast.cmd_broadcast)
    _add(app, ["syncban", "forcesync", "fbanall"], sync.cmd_syncban)

    # Maintenance
    _add(app, ["leaveall", "exitall", "fedleave"], maintenance.cmd_leaveall)
    _add(app, ["cleanup", "purge", "fedclean"], maintenance.cmd_cleanup)

    # Group affiliation events
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, affiliate.on_new_chat_members)
    )
    app.add_handler(
        CallbackQueryHandler(affiliate.on_affiliation_callback, pattern=r"^fed_(join|cancel)$")
    )
    app.add_handler(ChatMemberHandler(affiliate.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Start menu / interactive help (Features 24 & 25)
    app.add_handler(
        CallbackQueryHandler(
            menu.on_menu_callback,
            pattern=r"^(menu_(about|help|stats|groups|fedinfo|back_start)|help_[a-z]+)$",
        )
    )

    # Ban proof flow
    app.add_handler(CallbackQueryHandler(ban.on_cancel_proof, pattern=r"^cancel_proof$"))
    app.add_handler(
        MessageHandler(
            filters.ATTACHMENT & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
            ban.on_proof_message,
        )
    )

    # Appeal flow
    app.add_handler(CallbackQueryHandler(appeal.on_cancel_appeal, pattern=r"^cancel_appeal$"))
    app.add_handler(
        CallbackQueryHandler(appeal.on_appeal_review, pattern=r"^appeal_(approve|reject)_")
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            appeal.on_appeal_message,
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
