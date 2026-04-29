# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Package configuration loader for the TCF bot."""
import os

from dotenv import load_dotenv

load_dotenv("c.env", override=False)
load_dotenv(".env", override=True)

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
MONGODB_URI: str = os.environ["MONGODB_URI"]
DB_NAME: str = os.environ.get("DB_NAME", "tcf_bot")

LOG_CHANNEL: int = int(os.environ.get("LOG_CHANNEL", "-1003941141635"))
MAIN_GROUP: int = int(os.environ.get("MAIN_GROUP", "-1003872207988"))
PROOF_TOPIC: int = int(os.environ.get("PROOF_TOPIC", "67"))
APPEAL_TOPIC: int = int(os.environ.get("APPEAL_TOPIC", "12"))
APPEAL_DISCUSSION_TOPIC: int = int(os.environ.get("APPEAL_DISCUSSION_TOPIC", "11"))
MAIN_CHANNEL: int = int(os.environ.get("MAIN_CHANNEL", "-1003852970764"))
EXEC_GROUP: int = int(os.environ.get("EXEC_GROUP", "-1002333013065"))
INITIAL_OWNER_ID: int = int(os.environ.get("INITIAL_OWNER_ID", "7146954165"))

BRANDING: str = os.environ.get(
    "BRANDING",
    "𝘛𝘊𝘍 - 𝘛𝘳𝘢𝘯𝘴𝘴𝘪𝘰𝘯 𝘊𝘰𝘳𝘦 𝘍𝘦𝘥𝘦𝘳𝘢𝘵𝘪𝘰𝘯",
)

PROOF_WAIT_SECONDS: int = int(os.environ.get("PROOF_WAIT_SECONDS", "60"))
ALBUM_DEBOUNCE_SECONDS: int = int(os.environ.get("ALBUM_DEBOUNCE_SECONDS", "2"))
APPEAL_WAIT_SECONDS: int = int(os.environ.get("APPEAL_WAIT_SECONDS", "600"))

ABOUT_TEXT: str = (
    "<b>What is TCF?</b>\n"
    "Transsion Core Federation (TCF) is a community-driven federation for "
    "Infinix, Tecno, and Itel groups. Our main focus is maintaining group "
    "security and a conducive environment so members can discuss comfortably.\n"
    "<i>TCF is not an official part of Transsion Holdings. This is strictly an "
    "independent community.</i>\n\n"
    "<b>History</b>\n"
    "Established in 2024. Originally named TFI, but it was disbanded due to "
    "internal issues. Shortly after, TCF was formed to continue managing the "
    "community with better stability."
)

APPEAL_INSTRUCTION_TEMPLATE: str = (
    "Transsion Core [Group]: Appeal Submission\n\n"
    "To submit an appeal for your federation ban, send a single message in this "
    "private chat that starts with #appeal and contains the following fields, "
    "each on its own line with the exact labels shown:\n\n"
    "#appeal\n"
    "Log link: <paste the link to your ban log message in the Log Channel>\n"
    "Clarification: <a brief, honest explanation of why your ban should be reviewed>\n"
    "Agreement: <write that you agree to follow the federation rules going forward>\n\n"
    "Notes:\n"
    "- The Log link must point to your specific ban entry in the Log Channel. "
    "If the link does not match our records the appeal will be rejected automatically.\n"
    "- Be honest and concise. False, abusive, or off-topic appeals will be discarded.\n"
    "- Once submitted, your appeal will be reviewed by federation admins. The "
    "original banning admin has the first 12 hours to respond; after that, any "
    "federation admin or owner can decide.\n\n"
    "Ban ID: {ban_id}\n"
    "Log Channel: @TranssionCoreFederationLogs"
)
