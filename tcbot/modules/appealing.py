# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Appeal system – entry via /start appeal_<ban_id> deep link and admin decision callbacks."""
from __future__ import annotations

from telegram.ext import CallbackQueryHandler

from tcbot.modules.helper.workflows.appeal_flow import build_handler, on_appeal_decision

__module_name__ = "Appeal"
__help_text__ = (
    "Submit a federation ban appeal via the <b>Submit Appeal</b> button on your ban log,\n"
    "or by using <code>/start appeal_&lt;ban_id&gt;</code> in my private chat.\n\n"
    "Reply with a message starting with <code>#appeal</code> containing:\n"
    "- <b>Log link:</b> (from @TranssionCoreFederationLogs)\n"
    "- <b>Clarification:</b> (your honest explanation)\n"
    "- <b>Agreement:</b> (your commitment not to repeat the violation)\n\n"
    "Your appeal will be reviewed by Transsion Core admins. "
    "The banning admin has 12 hours to decide; after that, any admin can approve or reject it.\n"
    "If approved, the ban is lifted; if rejected, the ban remains. You will be notified of the decision."
)

__handlers__ = [
    build_handler(),
    ## Pattern: appeal_approve_<ban_id> or appeal_reject_<ban_id>
    CallbackQueryHandler(on_appeal_decision, pattern=r"^appeal_(approve|reject)_\S+$"),
]
