# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Federation ban – proof collection ConversationHandler
from __future__ import annotations

from tcbot.modules.helper.workflows.ban_flow import build_handler

__module_name__ = "Ban"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcban</code> (alias: <code>/tcb</code>)\n\n"

    "<b>Who can use it</b>\n"
    "Developer and above (Founder / Admin / Developer).\n\n"

    "<b>Where to use it</b>\n"
    "Exec group, connected groups, or bot PM.\n\n"

    "<b>What it does</b>\n"
    "Issues a <b>federation-wide ban</b> on the target. After the command, the bot will ask "
    "you to submit proof (photo or video). Once proof is uploaded, the ban is logged and "
    "enforced across all connected groups automatically.\n"
    "If the user is already banned, the existing record gets updated with the new reason and proof.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"

    "<b>Examples</b>\n"
    "<code>/tcban @username spamming affiliate links</code>\n"
    "<code>/tcban 123456789 scamming members</code>\n"
    "Or reply to a message, then: <code>/tcb reason here</code>"
)

__handlers__ = [build_handler()]
