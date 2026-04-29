# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Help system catalogue.

The interactive help menu and the ``/help`` command both render the same
content. Defining the catalogue once here keeps button labels, callback
identifiers, and the longer detail text in lock-step.

The detail text is intentionally verbose: it tells users which command
aliases are available, who may use them, where they may be used, and any
behavioural notes (for example the proof-collection step for ``/tcban``).
The wording is taken verbatim from PROMPT Feature 31 so the contract with
the federation tooling stays intact.
"""
from __future__ import annotations

from typing import Final


HELP_MODULE_ROWS: Final[list[list[tuple[str, str]]]] = [
    [("Ban", "help_ban"), ("Unban", "help_unban")],
    [("Check Ban", "help_check"), ("Ban Info", "help_baninfo")],
    [("Promote/Demote", "help_admin"), ("Transfer Owner", "help_transfer")],
    [("Broadcast", "help_broadcast"), ("Group Affiliation", "help_affiliation")],
    [("Disaffiliate", "help_defed"), ("Appeal", "help_appeal")],
    [("Join/Leave", "help_join"), ("Statistics", "help_stats")],
    [("Cleanup", "help_cleanup")],
]


HELP_DETAILS: Final[dict[str, str]] = {
    "help_ban": (
        "<b>Ban Module</b>\n"
        "Commands: /tcban, /ban, /tcfban\n"
        "Usage: /tcban &lt;target&gt; &lt;reason&gt; "
        "(target can be reply, user ID, or @username)\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Where: Any affiliated group, the main forum, exec group, or PM.\n"
        "Note: A proof is required. After issuing the command, you'll be asked "
        "to upload photo/video evidence."
    ),
    "help_unban": (
        "<b>Unban Module</b>\n"
        "Commands: /tcunban, /unban, /tcfunban\n"
        "Usage: /tcunban &lt;target&gt; [optional reason]\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Where: Any affiliated group, main forum, exec group, or PM.\n"
        "If an appeal was pending, it will be automatically closed."
    ),
    "help_check": (
        "<b>Check Ban Module</b>\n"
        "Commands: /checkme, /myban, /amibanned\n"
        "Usage: Simply type /checkme anywhere.\n"
        "Who can use: Everyone.\n"
        "If banned, you'll see details and a button to submit an appeal."
    ),
    "help_baninfo": (
        "<b>Ban Info Module</b>\n"
        "Commands: /baninfo, /checkban, /banstatus\n"
        "Usage: /baninfo &lt;target&gt;\n"
        "Who can use: Everyone.\n"
        "Shows detailed information about a user's ban status."
    ),
    "help_admin": (
        "<b>Promote/Demote Module</b>\n"
        "Commands: /tcpromote, /promote, /tcfpromote  (promote)\n"
        "/tcdemote, /demote, /tcfdemote  (demote)\n"
        "Usage: /tcpromote &lt;target&gt; (promote); /tcdemote &lt;target&gt; (demote)\n"
        "Who can use: Promote - Transsion Core Admins (creates request) or "
        "Owner (immediate). Demote - Owner only.\n"
        "Note: Self-demote produces a special message about the bot's role."
    ),
    "help_transfer": (
        "<b>Transfer Owner Module</b>\n"
        "Commands: /tctransfer, /transfer, /tcowner\n"
        "Usage: /tctransfer &lt;target&gt;\n"
        "Who can use: Transsion Core Owner only.\n"
        "Transfers ownership to another user. The old owner becomes a regular admin."
    ),
    "help_broadcast": (
        "<b>Broadcast Module</b>\n"
        "Commands: /tcbroadcast, /broadcast, /tcannounce\n"
        "Usage: /tcbroadcast &lt;message&gt;\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Sends the message to all affiliated groups."
    ),
    "help_affiliation": (
        "<b>Group Affiliation Module</b>\n"
        "Commands: /jointc, /requestjoin, /applytc (explicit join)\n"
        "/detc, /leavetc, /untc (disaffiliate current group)\n"
        "/rmtc, /removetc, /deletetc &lt;group_id&gt; (remove by ID)\n"
        "Who can use: Join - group owner; disaffiliate - group owner or TC admin; "
        "remove - TC admins.\n"
        "Note: Bot added automatically asks to join."
    ),
    "help_defed": (
        "<b>Disaffiliate Module</b>\n"
        "Inside a group: /detc, /leavetc, /untc - the group owner or any TC "
        "owner/admin can remove the group from TCF.\n"
        "By group ID (any chat): /rmtc, /removetc, /deletetc &lt;group_id&gt; - "
        "TC owner or admin only."
    ),
    "help_appeal": (
        "<b>Appeal Module</b>\n"
        "If you are banned, you can submit an appeal by clicking 'Submit Appeal' "
        "on the ban log message in @TranssionCoreFederationLogs, or by using "
        "/start appeal_&lt;ban_id&gt; in my private chat.\n"
        "The bot will then guide you through the process. You need to reply with "
        "a message starting with #appeal, containing:\n"
        "- Log link: (from the log channel)\n"
        "- Clarification: (your honest explanation)\n"
        "- Agreement: (your commitment not to repeat the violation)\n\n"
        "Your appeal will be reviewed by Transsion Core admins. The banning admin "
        "has 12 hours to decide; after that, any admin can approve or reject it. "
        "If approved, the ban is lifted; if rejected, the ban remains. "
        "You'll be notified of the decision."
    ),
    "help_join": (
        "<b>Join/Leave Module</b>\n"
        "Commands: /jointc, /requestjoin, /applytc (join)\n"
        "/detc, /leavetc, /untc (leave Transsion Core)\n"
        "Who can use: Join - group owner; leave - group owner or TC admin."
    ),
    "help_stats": (
        "<b>Statistics Module</b>\n"
        "Commands: /tcstats, /stats, /tcinfo\n"
        "Usage: /tcstats\n"
        "Who can use: Everyone.\n"
        "Displays current Transsion Core stats: owner, admin count, "
        "affiliated groups, active bans."
    ),
    "help_cleanup": (
        "<b>Cleanup Module</b>\n"
        "Commands: /cleanup, /purge, /tcclean\n"
        "Usage: /cleanup\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Checks all affiliated groups and removes those where the bot is "
        "no longer present."
    ),
}
