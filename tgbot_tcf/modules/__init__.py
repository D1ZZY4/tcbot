# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Feature-specific business logic for the Transsion Core Federation bot.

The ``modules`` package is the domain layer of the bot. Telegram update
handlers in :mod:`tgbot_tcf.handlers` stay thin and delegate the actual work
(database writes, cross-group enforcement, log-text construction, message
copy, keyboard layouts, validation) to the small, focused modules in this
package.

Layout
------
``messages``        Centralised, friendly-yet-formal user-facing strings.
``log_templates``   Builders for messages posted to the log channel.
``keyboards``       Reusable inline-keyboard factories.
``help_text``       Help module catalogue and detail copy.
``bans``            Ban / unban DB lifecycle and proof-caption builders.
``affiliations``    Group affiliation lifecycle and permission checks.
``admins_mod``      Owner / admin role lifecycle and promotion requests.
``appeals``         Appeal session storage, parsing, and review templates.
``broadcast_mod``   Broadcast loop over active federated groups.
``maintenance_mod`` Leave-all and cleanup loops over active federated groups.
``cache_repo``      Member-cache write-paths and seeding from admin lists.

Importing :mod:`tgbot_tcf.modules` itself is intentionally cheap; consumers
should import the specific submodule they need (``from tgbot_tcf.modules
import bans`` or ``from tgbot_tcf.modules.messages import M``).
"""
from . import (
    admins_mod,
    affiliations,
    appeals,
    bans,
    broadcast_mod,
    cache_repo,
    help_text,
    keyboards,
    log_templates,
    maintenance_mod,
    messages,
)

__all__ = [
    "admins_mod",
    "affiliations",
    "appeals",
    "bans",
    "broadcast_mod",
    "cache_repo",
    "help_text",
    "keyboards",
    "log_templates",
    "maintenance_mod",
    "messages",
]
