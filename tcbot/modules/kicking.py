# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

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
    "Removes a user from the <b>current group only</b> — this is not a federation-wide action. "
    "The user can rejoin via an invite link unless they are separately federation-banned.\n\n"
    "If the target holds a federation role (Tester / Developer / Admin), that role is "
    "automatically removed and they are notified by DM. A log entry is posted to the "
    "federation logs channel.\n\n"

    "<b>Flow</b>\n"
    "1. Run <code>/tckick</code> with the target (and optional inline reason).\n"
    "2. If no reason was given, the bot asks — reply with text or tap <b>Skip</b>.\n"
    "3. The bot asks for proof — send a photo/video or tap <b>Skip</b> to kick without proof.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username after the command.\n\n"

    "<b>Examples</b>\n"
    "<code>/tckick @username being disruptive</code> — reason inline\n"
    "<code>/tck 123456789</code> — bot will ask for reason\n"
    "Or reply to a message and run <code>/tck</code>."
)

__handlers__ = [kick_conversation()]
