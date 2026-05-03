# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Auth decorators for command handlers."""
from __future__ import annotations

import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.database.roles_db import get_effective_role, role_rank

log = logging.getLogger(__name__)


def owner_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.admins_db.is_owner(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text("This command is for the owner only.")
    return wrapper


def staff_only(func):
    """Founder and Admin."""
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.admins_db.is_staff(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text("You don't have permission to use this command.")
    return wrapper


def mod_only(func):
    """Founder, Admin, Developer — for ban/unban."""
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and role_rank(await get_effective_role(uid)) >= role_rank("developer"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text("You're not authorized to use this command.")
    return wrapper


def basic_mod_only(func):
    """Founder, Admin, Developer, Tester — for kick/mute/warn."""
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and role_rank(await get_effective_role(uid)) >= role_rank("tester"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text("You're not authorized to use this command.")
    return wrapper
