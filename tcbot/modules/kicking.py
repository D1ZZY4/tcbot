# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Group kick command
from __future__ import annotations

from tcbot.modules.helper.workflows.kicking_conv import kick_conversation

__module_name__ = "Kick"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tckick</code> (alias: <code>/tck</code>)\n\n"

    "<b>Who can use it</b>\n"
    "Tester and above (Founder / Admin / Developer / Tester).\n\n"

    "<b>Where to use it</b>\n"
    "Inside any connected group.\n\n"

    "<b>What it does</b>\n"
    "Removes a user from the current group. Unlike a ban, the user can still rejoin "
    "via an invite link — this is just a removal, not a long-term restriction.\n"
    "The kick is logged to the database for record keeping.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"

    "<b>Flow</b>\n"
    "The bot will ask for a reason (optional) and proof (optional) before executing.\n\n"

    "<b>Examples</b>\n"
    "<code>/tckick @username being disruptive</code>\n"
    "<code>/tck 123456789</code>\n"
    "Or reply to a message and run <code>/tck</code>."
)

__handlers__ = [kick_conversation()]
