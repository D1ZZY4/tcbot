# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Bot-added join prompt and the group connection builder."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from telegram import Bot, ChatMember, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import identity, messages
from tcbot.modules.helper.buttons import connect_join_btn, connect_verify_btn
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_edit_message, send_text
from tcbot.modules.helper.messages.rich_format import divider, heading, paragraph
from tcbot.modules.helper.messages.rich_list import details
from tcbot.modules.helper.pipelines.connect_common import welcome_permission_note
from tcbot.modules.helper.pipelines.connect_decision import ConnectionDecisionMixin
from tcbot.modules.helper.pipelines.connect_replay import ConnectionReplayMixin
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import bold, bullet_list, code, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)

_REQUIRED_PERMS: tuple[str, ...] = (
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
)


class ConnectionAddedMixin:
    """Bot-added member-update step: removal, demotion, and join fast paths."""

    if TYPE_CHECKING:

        async def complete_join(
            self,
            chat_id: int,
            chat_title: str,
            owner_id: int,
            owner_fname: str,
            bot: Bot,
        ) -> bool:
            """Replay decisions into the new group."""
            ...

        def check_perms(self, member: ChatMember) -> bool:
            """Check the bot's required admin rights."""
            ...

        def connected_blind_message(self, locale: str | None = None) -> str:
            """Warning for an incomplete replay."""
            ...

        def connected_message(self, locale: str | None = None) -> str:
            """Success notice."""
            ...

        def verify_prompt(self, step: int, locale: str | None = None) -> str:
            """One verification page."""
            ...

        def verify_keyboard(
            self, step: int, locale: str | None = None
        ) -> InlineKeyboardMarkup:
            """Keyboard of one verification page."""
            ...

        def connecting_message(self, locale: str | None = None) -> str:
            """Progress notice."""
            ...

        def join_keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
            """Connect / Cancel keyboard."""
            ...

    async def on_bot_added(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle every change to the bot own member status in any chat."""
        cmc = update.my_chat_member
        if not cmc:
            return
        chat = cmc.chat
        if chat.type not in ("group", "supergroup"):
            return
        locale = await locale_for_update(update)
        new_status = cmc.new_chat_member.status
        old_status = cmc.old_chat_member.status if cmc.old_chat_member else None
        by_user = cmc.from_user
        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            conn_results = await asyncio.gather(
                db.groups_db.is_connected(chat.id, fresh=True),
                db.groups_db.deactivate_group(chat.id),
                db.groups_db.remove_pending(chat.id),
                return_exceptions=True,
            )
            throw_if_cancelled(conn_results)
            was_connected = conn_results[0]
            if isinstance(was_connected, BaseException):
                log.debug(
                    "is_connected check failed on bot removal from %d: %s",
                    chat.id,
                    was_connected,
                )
                was_connected = False
            for label, result in zip(
                ("deactivate", "remove_pending"), conn_results[1:], strict=True
            ):
                if isinstance(result, BaseException):
                    log.error(
                        "Bot removal cleanup (%s) failed for chat=%d: %s",
                        label,
                        chat.id,
                        result,
                    )
            if was_connected:
                try:
                    await messages.send_log(
                        ctx.bot,
                        messages.group_bot_removed_log(
                            chat.id, chat.title or "Unknown"
                        ),
                    )
                except Exception:
                    log.exception("Bot removed log failed for %d", chat.id)
            log.info("Bot removed from %d; group deactivated", chat.id)
            return
        if (
            new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)
            and old_status == ChatMemberStatus.ADMINISTRATOR
        ):
            if not cfg.is_primary_group(chat.id):
                warning_text = (
                    "Bot was demoted in group"
                    f" {bold(chat.title or str(chat.id))}"
                    f" (id: {code(str(chat.id))})."
                    " Federation bans cannot be enforced there until"
                    " admin rights are restored."
                )
                try:
                    await messages.send_log(ctx.bot, warning_text)
                except Exception as exc:
                    log.warning(
                        "Failed to send admin-rights-lost warning for chat=%d: %s",
                        chat.id,
                        exc,
                    )
            return
        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
            if cfg.is_primary_group(chat.id):
                try:
                    await db.groups_db.ensure_primary_group(chat.id, chat.title)
                except Exception:
                    log.exception(
                        "Primary group registration failed for chat %d", chat.id
                    )
                return
            if cfg.is_infrastructure_chat(chat.id):
                return
            pending, is_already_connected = await asyncio.gather(
                db.groups_db.get_pending(chat.id),
                db.groups_db.is_connected(chat.id, fresh=True),
                return_exceptions=True,
            )
            throw_if_cancelled((pending, is_already_connected))
            if isinstance(pending, BaseException):
                log.warning(
                    "get_pending check failed on bot-added for %d: %s", chat.id, pending
                )
                return
            if isinstance(is_already_connected, BaseException):
                log.warning(
                    "is_connected check failed on bot-added for %d: %s",
                    chat.id,
                    is_already_connected,
                )
                return
            if (
                pending
                # * A lingering pending row must not replay a join (and every
                # * ban/mute) for a group that is already connected. The common
                # * case is a failed pending cleanup followed by a re-promote.
                and not is_already_connected
                and new_status == ChatMemberStatus.ADMINISTRATOR
                and pending.get("owner_id")
            ):
                if self.check_perms(cmc.new_chat_member):
                    owner_fname = await db.users_cache.get_first_name(
                        pending.get("owner_id", 0), "Owner"
                    )
                    with contextlib.suppress(Exception):
                        await safe_edit_message(
                            ctx.bot,
                            chat.id,
                            pending.get("message_id", 0),
                            self.connecting_message(locale),
                            reply_markup=None,
                        )
                    try:
                        blind = await self.complete_join(
                            chat.id,
                            chat.title or "",
                            pending.get("owner_id", 0),
                            owner_fname,
                            ctx.bot,
                        )
                    except Exception:
                        log.exception(
                            "complete_join failed in on_bot_added for chat %d", chat.id
                        )
                        with contextlib.suppress(Exception):
                            await safe_edit_message(
                                ctx.bot,
                                chat.id,
                                pending.get("message_id", 0),
                                t("connecting.state.complete_join", locale, plain=True),
                                reply_markup=None,
                            )
                        return
                    welcome_note = await welcome_permission_note(
                        ctx.bot, chat.id, locale
                    )
                    try:
                        await safe_edit_message(
                            ctx.bot,
                            chat.id,
                            pending.get("message_id", 0),
                            (
                                self.connected_blind_message(locale)
                                if blind
                                else self.connected_message(locale)
                            )
                            + welcome_note,
                            reply_markup=None,
                        )
                    except Exception as exc:
                        log.debug("Failed to edit pending connect prompt: %s", exc)
                return
            if is_already_connected or pending:
                return
            owner_id = (
                by_user.id
                if by_user is not None and not identity.is_anon_admin(by_user)
                else 0
            )
            if owner_id == 0:
                log.info(
                    "Bot added to %d without an attributable admin; "
                    "prompting the group creator",
                    chat.id,
                )
            try:
                prompt = await send_text(
                    ctx.bot,
                    chat.id,
                    self.verify_prompt(0, locale),
                    reply_markup=self.verify_keyboard(0, locale),
                )
                await db.groups_db.add_pending(
                    chat.id, chat.title or "", owner_id, prompt.message_id
                )
            except Exception:
                log.exception("Join prompt send failed for %d", chat.id)


@dataclass(frozen=True)
class BuildConnection(
    ConnectionAddedMixin, ConnectionDecisionMixin, ConnectionReplayMixin
):
    """Configurable group-connection builder."""

    community_name: str
    required_perms: tuple[str, ...] = field(default=_REQUIRED_PERMS, kw_only=True)
    join_callback: str = field(default="tc_join", kw_only=True)
    cancel_callback: str = field(default="tc_cancel", kw_only=True)
    verify_callback: str = field(default="tc_verify", kw_only=True)

    def verify_prompt(self, step: int, locale: str | None = None) -> str:
        """Build one rich verification page shown before connecting."""
        if step == 0:
            return self._welcome_prompt(locale)
        key = f"page_{step}"
        title = t(f"connecting.verify.{key}_title", locale, plain=True)
        body = t(f"connecting.verify.{key}_body", locale)
        detail = t(f"connecting.verify.{key}_detail", locale)
        note = t(f"connecting.verify.{key}_note", locale, plain=True)
        return "\n".join(
            (
                heading(title),
                paragraph(body),
                divider(),
                details(
                    t("connecting.verify.why", locale, plain=True),
                    paragraph(detail),
                    open=True,
                ),
                divider(),
                paragraph(note),
            )
        )

    def _welcome_prompt(self, locale: str | None = None) -> str:
        """Introduce the bot on first add before the requirement pages.

        The welcome is an orientation, not a wall of rules: it says why the
        bot is here, what connecting changes, and what the owner will review.
        The three membership points are summarized here and detailed one by
        one on the following pages, so nothing is copied from the policy
        document verbatim and no page repeats another.
        """
        title = t(
            "connecting.verify.welcome_title",
            locale,
            community=self.community_name,
            plain=True,
        )
        intro = t(
            "connecting.verify.welcome_intro", locale, community=self.community_name
        )
        points_title = t("connecting.verify.welcome_points_title", locale, plain=True)
        points = [
            t(f"connecting.verify.welcome_point_{number}", locale)
            for number in (1, 2, 3)
        ]
        hint = t("connecting.verify.welcome_hint", locale)
        return "\n".join(
            (
                heading(title),
                paragraph(intro),
                divider(),
                paragraph(points_title),
                bullet_list(points),
                divider(),
                paragraph(hint),
            )
        )

    def verify_keyboard(
        self, step: int, locale: str | None = None
    ) -> InlineKeyboardMarkup:
        """Continue through the pages, then reveal Connect on the last one."""
        return connect_verify_btn(
            step,
            self.verify_callback,
            self.join_callback,
            self.cancel_callback,
            locale,
            total_steps=6,
        )

    def connected_message(self, locale: str | None = None) -> str:
        """Shown on a successful connection."""
        return t(
            "connecting.state.connected",
            locale,
            community=self.community_name,
            plain=True,
        )

    def connected_blind_message(self, locale: str | None = None) -> str:
        """Blind-replay warning shown instead of the success message."""
        return t(
            "connecting.state.connected_blind",
            locale,
            community=self.community_name,
            plain=True,
        )

    def declined_message(self, locale: str | None = None) -> str:
        """Shown when the owner taps Cancel."""
        return t("connecting.state.declined", locale, plain=True)

    def already_connected_message(self, locale: str | None = None) -> str:
        """Shown when the group is already part of the federation."""
        return t(
            "connecting.state.already_connected",
            locale,
            community=self.community_name,
            plain=True,
        )

    def connecting_message(self, locale: str | None = None) -> str:
        """Progress state edited into the prompt before the replay."""
        return t("connecting.state.connecting", locale, plain=True)

    def perms_required_message(self, locale: str | None = None) -> str:
        """Shown when the bot lacks the required admin permissions."""
        return t("connecting.state.perms_required", locale, plain=True)

    def join_keyboard(self, locale: str | None = None) -> InlineKeyboardMarkup:
        """Connect / Cancel keyboard for the join prompt."""
        return connect_join_btn(self.join_callback, self.cancel_callback, locale=locale)

    def check_perms(self, member: ChatMember) -> bool:
        """Return True when member holds every permission in required_perms."""
        return all(getattr(member, p, False) for p in self.required_perms)


connection = BuildConnection(cfg.community_name)
