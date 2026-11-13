# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Runtime state tables: the MTProto session and the APScheduler job store."""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Column,
    Float,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)

from ._shared import metadata

# * The Kurigram session state. One row per key, scoped by the session
# * namespace: ``<ns>:kv:<name>`` scalars, ``<ns>:peer:<peer_id>`` peers
# * and ``<ns>:ustate:<id>`` update states.
# *
# * The three record kinds share one table and are told apart by the key
# * prefix, so the columns of the other kinds stay NULL. The scalar value
# * is stored as msgpack because the session keys hold opaque Python
# * objects (the authorization key is raw bytes).
mtproto_state = Table(
    "mtproto_state",
    metadata,
    Column("id", Text, nullable=False, autoincrement=False),
    Column("value", LargeBinary, nullable=True),
    Column("access_hash", BigInteger, nullable=True),
    Column("type", Text, nullable=True),
    Column("usernames", ARRAY(Text), nullable=True),
    Column("phone_number", Text, nullable=True),
    Column("updated_on", BigInteger, nullable=True),
    Column("pts", Integer, nullable=True),
    Column("qts", Integer, nullable=True),
    Column("date", Integer, nullable=True),
    Column("seq", Integer, nullable=True),
    # * The single-owner lease lives in this table too: the holder and
    # * the epoch second its lease expires at are the only fields a
    # * lease row carries. The primary key serves the lease lookup.
    Column("owner", Text, nullable=True),
    Column("expires_at", BigInteger, nullable=True),
    PrimaryKeyConstraint("id"),
)

# * The update states are read oldest-first by the session worker.
Index("ix_mtproto_state_date", mtproto_state.c.date)
# * A GIN index serves the containment and equality lookups the peer
# * username search needs over the name array.
Index("ix_mtproto_state_usernames", mtproto_state.c.usernames, postgresql_using="gin")
# * The row key carries the session namespace as a prefix, so the peer
# * and update-state lookups match on a prefix. The default text opclass
# * can only serve a prefix scan under a C collation, and the deployment
# * database is not C, so the pattern opclass is required.
Index(
    "ix_mtproto_state_id_pattern",
    mtproto_state.c.id,
    postgresql_ops={"id": "text_pattern_ops"},
)
Index(
    "ix_mtproto_state_phone_number",
    mtproto_state.c.phone_number,
    postgresql_where=text("phone_number IS NOT NULL"),
)

# * The persistent APScheduler state. APScheduler owns the rows; the
# * declaration keeps the table inside the schema contract.
apscheduler_jobs = Table(
    "apscheduler_jobs",
    metadata,
    Column("id", Text, nullable=False, autoincrement=False),
    Column("next_run_time", Float, nullable=True),
    Column("job_state", LargeBinary, nullable=False),
    PrimaryKeyConstraint("id"),
)
