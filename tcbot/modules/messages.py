# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Central message string namespace for the TCF bot.

All user-facing strings are defined here so tests can snapshot them
and accidental edits are caught immediately.
"""
from __future__ import annotations


class M:
    ## Branding
    BRANDING_LINE: str = "𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯"

    ## Generic errors
    NOT_AUTHORIZED: str = "You are not authorized."
    CANNOT_RESOLVE_USER: str = "Cannot resolve user."
    USER_NOT_BANNED: str = "User is not banned."
    ALREADY_TC_ADMIN: str = "Already a Transsion Core Admin."
    NOT_TC_ADMIN: str = "Not a Transsion Core Admin."
    INVALID_OR_EXPIRED_BAN: str = "Invalid or expired ban."

    ## Ban / unban
    BAN_SUCCESS: str = (
        "User {target_id} has been banned from the Transsion Core. Reason: {reason}"
    )
    UNBAN_SUCCESS: str = "User {target_id} has been unbanned from the Transsion Core."

    ## Admin management
    PROMOTE_OWNER_DONE: str = "User {target_id} is now a Transsion Core Admin."
    TRANSFER_DONE: str = "Ownership transferred to {target_id}."

    ## Appeal decisions
    APPEAL_DECISION_APPROVED: str = (
        "User has been unbanned and the appeal has been approved by {reviewer_link}."
    )
    APPEAL_DECISION_REJECTED: str = (
        "The appeal has been rejected by {reviewer_link}."
    )
