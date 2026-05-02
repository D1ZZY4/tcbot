# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation ban – proof collection ConversationHandler."""
from __future__ import annotations

from tcbot.modules.helper.workflows.ban_flow import build_handler

__module_name__ = "Ban"
__help_text__ = (
    "<code>/tcban</code> <i>&lt;target&gt; &lt;reason&gt;</i> – ban a user federation-wide.\n"
    "Reply to a message or provide a user ID / @username as the target.\n"
    "Aliases: <code>/fban</code>, <code>/ban</code>, <code>/tcfban</code>"
)

__handlers__ = [build_handler()]
