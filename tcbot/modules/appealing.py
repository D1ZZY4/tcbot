# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Appeal system – entry via /start appeal<ban_id> deep link and admin decision callbacks."""
from __future__ import annotations

from telegram.ext import CallbackQueryHandler

from tcbot.modules.helper.workflows.appeal_flow import build_handler, on_appeal_decision

__module_name__ = "Appeal"
__help_text__ = (
    "<b>How to start an appeal</b>\n"
    "Tap the <b>Submit Appeal</b> button on your ban log message, or open the bot in PM "
    "and use the deep link from your ban notification.\n\n"

    "<b>Who can use it</b>\n"
    "Anyone with an active federation ban.\n\n"

    "<b>Where to start</b>\n"
    "Bot PM only.\n\n"

    "<b>How it works</b>\n"
    "Once you open the appeal flow, reply with a message that starts with <code>#appeal</code> "
    "and includes the following:\n\n"
    "- <b>Log link:</b> the link to your ban log (from @TranssionCoreFederationLogs)\n"
    "- <b>Clarification:</b> your honest explanation of what happened\n"
    "- <b>Agreement:</b> your commitment not to repeat the violation\n\n"
    "<b>Format example:</b>\n"
    "<pre>#appeal\n"
    "Log link: https://t.me/TranssionCoreFederationLogs/123\n"
    "Clarification: I spammed links without knowing the rules.\n"
    "Agreement: I will follow all community rules going forward.</pre>\n\n"

    "<b>What happens next</b>\n"
    "Your appeal is forwarded to TC admins for review. The admin who issued the ban has "
    "<b>12 hours</b> to respond. After that, any admin can approve or reject it.\n"
    "If approved → ban is lifted immediately.\n"
    "If rejected → ban stays. You'll be notified either way."
)

__handlers__ = [
    build_handler(),
    CallbackQueryHandler(on_appeal_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
]
