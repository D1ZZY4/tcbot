# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Federation stats: overview, staff roster, users, connected chats, bans, search."""

from __future__ import annotations

from tcbot.modules.helper.workflows.stats_flow.bans import BanViews
from tcbot.modules.helper.workflows.stats_flow.chats import ChatViews
from tcbot.modules.helper.workflows.stats_flow.overview import OverviewViews
from tcbot.modules.helper.workflows.stats_flow.people import PeopleViews
from tcbot.modules.helper.workflows.stats_flow.search import SearchViews
from tcbot.modules.helper.workflows.stats_flow.shared import (
    CHAT_KEY,
    MSG_KEY,
    RESULTS_KEY,
    SEARCH_KEY,
    _list_kb,
    back_kb,
    launch_group_title_refresh,
    main_kb,
)


class Stats(OverviewViews, PeopleViews, ChatViews, BanViews, SearchViews):
    """All view builders for ``/tcstats``.

    Thin facade over the per-domain view mixins: main overview, staff
    roster, member roster, connected chats, active bans, and the search
    panel. Every method returns ``(text, markup)`` so callers can answer
    the callback and edit the card without further work.
    """


__all__ = (
    "CHAT_KEY",
    "MSG_KEY",
    "RESULTS_KEY",
    "SEARCH_KEY",
    "Stats",
    "_list_kb",
    "back_kb",
    "launch_group_title_refresh",
    "main_kb",
)
