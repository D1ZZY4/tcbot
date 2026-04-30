# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Single source of truth for every user-facing string the bot emits.

All copy is grouped under one :class:`Messages` namespace exported as ``M``.
Two principles guide the wording here:

1. **Spec-locked strings** – text that the PROMPT specification fixes
   verbatim (for example ``"You are not authorized."`` or ``"Cannot resolve
   user."``) must remain byte-for-byte identical so the contract with the
   federation tooling stays intact.
2. **Friendly-yet-formal tone** – every other string is phrased with warmth
   and respect: clear sentences, full punctuation, no slang, no emoji, no
   stiff phrasing. The aim is to sound like a thoughtful operations partner.

Curly-brace placeholders (``{name}``) are filled with :py:meth:`str.format`
or f-string substitution at the call site. HTML segments stay valid HTML
because every reply that uses these strings sets ``parse_mode=HTML``.
"""
from __future__ import annotations

from typing import Final


class Messages:
    """Namespace of every user-facing message the bot is allowed to send."""

    # ----------------------------------------------------------------- core
    BRANDING_LINE: Final[str] = "𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯"

    # ---------------------------------------------------- spec-locked replies
    NOT_AUTHORIZED: Final[str] = "You are not authorized."
    CANNOT_RESOLVE_USER: Final[str] = "Cannot resolve user."
    USER_NOT_BANNED: Final[str] = "User is not banned."
    USER_NOT_BANNED_TCF: Final[str] = "User is not banned in the Transsion Core."
    NOT_BANNED_SELF: Final[str] = "You are not banned in the Transsion Core."
    ALREADY_TC_ADMIN: Final[str] = "Already a Transsion Core Admin."
    NOT_TC_ADMIN: Final[str] = "Not a Transsion Core Admin."
    INVALID_OR_EXPIRED_BAN: Final[str] = "Invalid or expired ban."
    GROUP_NOT_AFFILIATED: Final[str] = "This group is not affiliated with TCF."
    DEFED_NOT_ALLOWED: Final[str] = (
        "Only the group owner or Transsion Core admins can disaffiliate this group."
    )
    BAN_TC_ROLE_BLOCKED: Final[str] = "Cannot ban a Transsion Core Admin or Owner."
    BAN_SELF_BLOCKED: Final[str] = "You cannot ban yourself."
    UNBAN_SELF_BLOCKED: Final[str] = (
        "You are not banned, or you cannot unban yourself."
    )
    PROMOTE_SELF_BLOCKED: Final[str] = "You cannot promote yourself."
    DEMOTE_SELF_BLOCKED: Final[str] = (
        "I cannot demote myself. I hold a crucial position in this Transsion Core.\n"
        "Please ask the owner to do it."
    )
    DEMOTE_OWNER_BLOCKED: Final[str] = "Cannot demote the Transsion Core Owner."
    TRANSFER_SELF_OWNER: Final[str] = "You are already the owner."
    TRANSFER_NOT_OWNER: Final[str] = "Only the owner can use this command."
    ALREADY_AFFILIATED: Final[str] = "Already affiliated."
    PROVIDE_BAN_REASON: Final[str] = "Please provide a reason."
    PROVIDE_BROADCAST_TEXT: Final[str] = "Please provide a message to broadcast."

    # The PROMPT (Feature 1 & 2) fixes the wording the bot uses to ask for the
    # admin permission set. The pending-join feature appends a soft confirmation.
    PERMS_NEEDED: Final[str] = (
        "Please make the bot an admin with the necessary permissions "
        "(delete messages, ban users, invite users) and try again. "
        "Once you grant the permissions, affiliation will complete automatically."
    )

    AFFILIATION_PROMPT: Final[str] = (
        "Do you want this community to join the Transsion Core Federation?"
    )
    AFFILIATION_SUCCESS: Final[str] = (
        "This community is now affiliated with TCF. Federation commands "
        "can now be used here by authorized Transsion Core admins."
    )
    AFFILIATION_SUCCESS_SHORT: Final[str] = (
        "This community is now affiliated with TCF."
    )
    AFFILIATION_AUTO_COMPLETED: Final[str] = (
        "Permissions granted. This community is now affiliated with TCF. "
        "Federation commands can now be used here."
    )
    AFFILIATION_AUTO_COMPLETED_SHORT: Final[str] = (
        "Permissions granted. This community is now affiliated with TCF."
    )
    AFFILIATION_CANCELLED: Final[str] = "Affiliation cancelled. Leaving the group."
    AFFILIATION_REJOIN_NOTICE: Final[str] = (
        "I have rejoined this community. This group is already affiliated "
        "with the Transsion Core Federation, so federation commands remain "
        "available to authorized Transsion Core admins."
    )
    AFFILIATION_PERMS_LOST: Final[str] = (
        "My required admin permissions in this community have been removed "
        "(delete messages, ban users, invite users). Federation enforcement "
        "will be limited until the permissions are restored."
    )
    AFFILIATION_CHANNEL_UNSUPPORTED: Final[str] = (
        "Channels are not supported. Leaving the channel."
    )
    AFFILIATION_OWNER_ONLY_ALERT: Final[str] = "Only the group owner can decide."
    AFFILIATION_VERIFY_ROLE_FAIL: Final[str] = (
        "I am unable to verify your role in this group at the moment. "
        "Please try again."
    )
    AFFILIATION_GROUP_OWNER_ONLY: Final[str] = (
        "Only the group owner can request affiliation."
    )
    AFFILIATION_GROUPS_ONLY: Final[str] = (
        "This command must be used inside a group."
    )
    AFFILIATION_FED_GROUPS_ONLY: Final[str] = (
        "This command must be used inside a federated group."
    )

    # Disaffiliation
    GROUP_DISAFFILIATED: Final[str] = (
        "This group has been removed from the Transsion Core Federation."
    )
    REMOVE_USAGE: Final[str] = "Usage: /rmtc <group_id>"
    REMOVE_NOT_FOUND: Final[str] = "Group not found or already removed."
    REMOVE_OK: Final[str] = "Group {group_id} has been removed from the federation."

    # Ban / unban (PROMPT-locked acknowledgements)
    BAN_USAGE: Final[str] = "Usage: /tcban <target> <reason>"
    BAN_PROOF_PROMPT: Final[str] = (
        "Please provide proof for this ban. "
        "Send a photo or video (multiple media allowed). You have 60 seconds."
    )
    BAN_PROOF_ONLY_MEDIA: Final[str] = (
        "Only photos or videos are accepted as proof. "
        "Please send a photo or video, or press Cancel to abort."
    )
    BAN_PROOF_TIMEOUT: Final[str] = (
        "Proof submission timed out. Please run the command again when you "
        "are ready to upload the evidence."
    )
    BAN_PROOF_FAILED_UPLOAD: Final[str] = (
        "I was unable to upload your proof to the federation. "
        "Please try the command again in a moment."
    )
    BAN_OPERATION_CANCELLED: Final[str] = (
        "Operation cancelled. No further action will be taken."
    )
    BAN_NO_ACTIVE_SESSION: Final[str] = (
        "There is no active proof session for you in this chat."
    )
    BAN_SELF_BOT_BLOCKED: Final[str] = (
        "I am unable to act on myself in this manner."
    )
    BAN_SUCCESS: Final[str] = (
        "User {target_name} (ID: {target_id}) has been banned from the "
        "Transsion Core.\nReason: {reason}"
    )
    UNBAN_SUCCESS: Final[str] = (
        "User {target_name} (ID: {target_id}) has been unbanned from the "
        "Transsion Core."
    )

    # Promote / demote / transfer
    PROMOTE_NEEDS_TARGET: Final[str] = (
        "Reply to a user, provide a user ID, or provide a username to promote."
    )
    DEMOTE_NEEDS_TARGET: Final[str] = (
        "Reply to a user, provide a user ID, or provide a username to demote."
    )
    TRANSFER_NEEDS_TARGET: Final[str] = (
        "Reply to a user, provide a user ID, or provide a username "
        "to transfer ownership to."
    )
    PROMOTE_OWNER_DONE: Final[str] = (
        "User {target_name} (ID: {target_id}) is now a Transsion Core Admin."
    )
    DEMOTE_DONE: Final[str] = (
        "User {target_name} (ID: {target_id}) has been demoted from "
        "Transsion Core Admin."
    )
    TRANSFER_DONE: Final[str] = (
        "Ownership transferred to {target_name} (ID: {target_id})."
    )
    PROMOTION_REQUEST_SENT: Final[str] = (
        "Promotion request for {target_name} (ID: {target_id}) has been "
        "sent to the Transsion Core Owner for approval."
    )
    PROMOTION_REQUEST_APPROVED: Final[str] = (
        "Promotion request approved. {target_name} is now a Transsion Core Admin."
    )
    PROMOTION_REQUEST_REJECTED: Final[str] = "Promotion request rejected."
    PROMOTION_REQUEST_NOT_FOUND_ALERT: Final[str] = "Promotion request not found."
    PROMOTION_REQUEST_RESOLVED_ALERT: Final[str] = (
        "This request has already been resolved."
    )
    PROMOTION_OWNER_ONLY_ALERT: Final[str] = (
        "Only the Transsion Core Owner can act on this."
    )
    NO_PENDING_PROMO_REQUESTS: Final[str] = "No pending promotion requests."

    # Appeals
    APPEAL_PRIVATE_ONLY: Final[str] = (
        "Appeals can only be started in a private chat with the bot."
    )
    APPEAL_INVALID_LOG_LINK: Final[str] = (
        "Invalid log link. Please check and try again."
    )
    APPEAL_SUBMITTED: Final[str] = (
        "Thank you. Your appeal has been submitted and is now awaiting review "
        "by Transsion Core admins. You will be notified of the decision."
    )
    APPEAL_SUBMIT_FAILED: Final[str] = (
        "I was unable to submit your appeal at this moment. "
        "Please try again in a little while."
    )
    APPEAL_CANCELLED: Final[str] = (
        "Appeal cancelled. You are welcome to start the process again at any time."
    )
    APPEAL_RESOLVED_ALREADY_INACTIVE: Final[str] = (
        "Appeal resolved (ban no longer active)."
    )
    APPEAL_RESOLVED_ALREADY_UNBANNED: Final[str] = (
        "Appeal resolved (user already unbanned)."
    )
    APPEAL_BAN_INACTIVE_ALERT: Final[str] = "This ban is already inactive."
    APPEAL_TWELVE_HOUR_RULE_ALERT: Final[str] = (
        "Only the banning admin can review within the first 12 hours."
    )
    APPEAL_NOTIFY_USER_APPROVED: Final[str] = (
        "Good news. Your appeal has been approved and you have been unbanned "
        "from the Transsion Core. Please review the federation rules before "
        "rejoining the affiliated communities."
    )
    APPEAL_NOTIFY_USER_REJECTED: Final[str] = (
        "Your appeal has been reviewed and unfortunately not approved at this "
        "time. The federation ban remains in effect."
    )
    APPEAL_PENDING_REVIEW: Final[str] = "This appeal is pending review."
    APPEAL_DECISION_APPROVED: Final[str] = (
        "Appeal approved by {reviewer_link}. User has been unbanned."
    )
    APPEAL_DECISION_REJECTED: Final[str] = "Appeal rejected by {reviewer_link}."

    # Broadcast / maintenance
    BROADCAST_RESULT: Final[str] = (
        "Broadcast sent to {success} groups. Failed: {failure} groups."
    )
    LEAVE_ALL_RESULT: Final[str] = (
        "Left {success} groups. Failed to leave {failure} groups."
    )
    CLEANUP_RESULT: Final[str] = (
        "Cleaned up {count} groups that were no longer accessible."
    )

    # Check / status
    CHECKME_BANNED: Final[str] = (
        "You are currently banned from Transsion Core.\n"
        "Reason: {reason}\n"
        "Banned by Transsion Core Admin: {admin_name}"
    )

    BANINFO_HEADER: Final[str] = "<b>Ban Details</b>"

    # Listings
    NO_AFFILIATED_GROUPS: Final[str] = "No groups are currently affiliated with TCF."
    NO_TC_ADMINS: Final[str] = "There are no Transsion Core Admins at this time."
    ADMINS_LIST_HEADER: Final[str] = "<b>There is Admin in</b>"

    # /start fallbacks
    START_GROUP_HINT: Final[str] = (
        "For the full menu, please open a private chat with me and send /start. "
        "You can also use /help here for a quick overview.\nBot: @{username}"
    )

    # Menu / help (PROMPT-locked exact text from Feature 31)
    START_WELCOME: Final[str] = (
        "<b>Welcome to the Transsion Core Federation (TCF) Bot!</b>\n"
        "I'm here to help you manage Transsion Core groups, bans, appeals, "
        "and more. Use the buttons below to navigate."
    )
    HELP_INTRO: Final[str] = (
        "<b>TCF Bot Help</b>\n"
        "I'm your assistant for managing the Transsion Core Federation. "
        "Select a topic below to learn more about what I can do."
    )
    PRIVACY_MAIN: Final[str] = (
        "<b>Privacy Information</b>\n"
        "Select one of the below options for more information about how the "
        "bot handles your privacy."
    )
    PRIVACY_POLICY: Final[str] = (
        "The Transsion Core Federation bot only collects data necessary for "
        "federation moderation: user IDs, group IDs, and message IDs related "
        "to bans and proofs. No personal messages, phone numbers, or media "
        "are stored beyond what you explicitly provide as proof. Your data "
        "is never shared with third parties and is only used to maintain a "
        "secure environment. All ban records are accessible only to "
        "Transsion Core admins."
    )
    LINKS_TEXT: Final[str] = (
        "<b>Transsion Core Federation - Official Links</b>\n"
        "Use the buttons below to access our channels and groups. "
        "For developers interested in contributing to Transsion device "
        "development, join TRAVEL - an independent community for "
        "collaboration and networking."
    )
    MENU_OWNER_ONLY_ALERT: Final[str] = (
        "Only the user who opened this menu can use these buttons."
    )

    # Welcome / goodbye in MAIN_GROUP and EXEC_GROUP (PROMPT Feature 27 - exact)
    WELCOME_GROUP: Final[str] = (
        "<b>Welcome to <i>{group_title}</i>, {user_link}!</b>\n"
        "We're glad to have you here. This is an official group of the "
        "Transsion Core Federation. Please take a moment to review the group "
        "rules and feel free to introduce yourself.\n\n"
        "If you have any questions or need assistance, don't hesitate to "
        "ask our admins.\n\n"
        "Enjoy your stay!"
    )
    GOODBYE_GROUP: Final[str] = (
        "{user_link} has left the group. We're sad to see you go! "
        "If you ever wish to rejoin, you're always welcome back."
    )

    # Information sub-menu header (matches PROMPT Feature 24 sub-menu)
    INFORMATION_HEADER: Final[str] = "<b>Transsion Core Information</b>"


M: Final[Messages] = Messages()
"""Convenience module-level alias used across the codebase."""
