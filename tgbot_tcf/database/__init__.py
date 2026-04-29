# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Database package: connection, collection handles, and per-collection repos.

Two import styles are supported, depending on how much abstraction the caller
wants:

* **Raw collection handles.** Importing the lower-case names exported here
  (``federated_groups``, ``tc_admins``, ``bans`` …) yields the underlying
  ``AsyncIOMotorCollection`` objects defined in :mod:`.mongo`. Use this when
  a query is one-off or genuinely ad hoc.

* **Repository helpers.** Each collection also has a focused module
  (:mod:`.bans`, :mod:`.groups`, :mod:`.admins`, :mod:`.requests`,
  :mod:`.joins`, :mod:`.members`) that exposes named, typed accessors such as
  :func:`bans_repo.find_active_for_user`. Higher-level code in
  :mod:`tgbot_tcf.modules` uses these so query intent is documented in code.
"""
from . import admins as admins_repo
from . import bans as bans_repo
from . import groups as groups_repo
from . import joins as joins_repo
from . import members as members_repo
from . import requests as requests_repo
from .mongo import (
    bans,
    db,
    federated_groups,
    init_db,
    member_cache,
    pending_joins,
    promotion_requests,
    tc_admins,
    tc_owners,
)

__all__ = [
    "db",
    "init_db",
    # Raw collection handles
    "federated_groups",
    "tc_owners",
    "tc_admins",
    "bans",
    "promotion_requests",
    "pending_joins",
    "member_cache",
    # Repositories
    "admins_repo",
    "bans_repo",
    "groups_repo",
    "joins_repo",
    "members_repo",
    "requests_repo",
]
