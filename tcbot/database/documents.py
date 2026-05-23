from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class AdminDoc(TypedDict, total=False):
    user_id: int
    promoted_by: int
    promoted_date: datetime


class BanDoc(TypedDict, total=False):
    ban_id: str
    banned_user_id: int
    reason: str
    admin_user_id: int
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
    chat_id: int
    title: str
    added_by: int
    added_date: datetime
    is_active: bool


class PendingGroupDoc(TypedDict, total=False):
    chat_id: int
    title: str
    owner_id: int
    message_id: int
    added_date: datetime


class RoleDoc(TypedDict, total=False):
    user_id: int
    role: str
    assigned_by: int
    assigned_at: datetime


class RoleRefDoc(TypedDict, total=False):
    user_id: int


class UserDoc(TypedDict, total=False):
    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    commit_date: datetime
    last_updated: datetime


class WarnDoc(TypedDict, total=False):
    _id: object
    user_id: int
    reason: str
    admin_id: int
    chat_id: int
    timestamp: datetime


class WarnCountDoc(TypedDict, total=False):
    user_id: int
    chat_id: int
    count: int
    updated_at: datetime


class PromotionRequestDoc(TypedDict, total=False):
    request_id: str
    target_id: int
    username: str | None
    first_name: str
    promoted_by: int
    status: str
    requested_date: datetime
    resolved_date: datetime | None
    resolved_by: int | None
