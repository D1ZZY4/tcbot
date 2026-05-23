# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""TypedDict document schemas for MongoDB collections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from tcbot.database.types import BanId, ChatId, GroupId, UserId

BanStatus = Literal["active", "expired", "revoked"]
RoleName = Literal["founder", "admin", "developer", "tester"]
RequestStatus = Literal["pending", "approved", "rejected"]


class AdminDoc(TypedDict, total=False):
    user_id: UserId
    promoted_by: UserId
    promoted_date: datetime


class BanDoc(TypedDict, total=False):
    ban_id: BanId
    banned_user_id: UserId
    reason: str
    admin_user_id: UserId
    proof_message_id: int
    log_message_id: int
    previous_proof_message_id: int | None
    previous_log_message_id: int | None
    timestamp: datetime
    updated_timestamp: datetime | None
    is_active: bool
    update_count: int
    review_message_id: int | None
    review_timestamp: datetime | None
    appeal_log_msg_id: int | None
    appeal_submitted_at: datetime | None
    appeal_link: str


class GroupDoc(TypedDict, total=False):
    chat_id: GroupId
    title: str
    added_by: UserId
    added_date: datetime
    is_active: bool


class PendingGroupDoc(TypedDict, total=False):
    chat_id: ChatId
    title: str
    owner_id: UserId
    message_id: int
    added_date: datetime


class RoleDoc(TypedDict, total=False):
    user_id: UserId
    role: RoleName
    assigned_by: UserId
    assigned_at: datetime


class RoleRefDoc(TypedDict, total=False):
    user_id: UserId


class UserDoc(TypedDict, total=False):
    user_id: UserId
    username: str | None
    first_name: str | None
    last_name: str | None
    commit_date: datetime
    last_updated: datetime


class WarnDoc(TypedDict, total=False):
    _id: object
    user_id: UserId
    reason: str
    admin_id: UserId
    chat_id: ChatId
    timestamp: datetime


class WarnCountDoc(TypedDict, total=False):
    user_id: UserId
    chat_id: ChatId
    count: int
    updated_at: datetime


class PromotionRequestDoc(TypedDict, total=False):
    request_id: str
    target_id: UserId
    username: str | None
    first_name: str
    promoted_by: UserId
    status: RequestStatus
    requested_date: datetime
    resolved_date: datetime | None
    resolved_by: UserId | None
