# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Client-added join prompt and the group connection builder."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import ChatMember, InlineKeyboardMarkup

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import identity, messages
from tcbot.modules.helper.buttons import connect_join_btn, connect_verify_btn
from tcbot.modules.helper.context import Ctx, chat_id_of
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import safe_edit_message, send_text
from tcbot.modules.helper.pipelines.connect_common import welcome_permission_note
from tcbot.modules.helper.pipelines.connect_decision import ConnectionDecisionMixin
from tcbot.modules.helper.pipelines.connect_replay import ConnectionReplayMixin
from tcbot.modules.helper.rich.formats import divider, heading, paragraph
from tcbot.modules.helper.rich.list import details
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import bold, bullet_list, code, t
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

log = get_logger(__name__)

_REQUIRED_PERMS: tuple[str, ...] = (
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
)


class ConnectionAddedMixin:
    """Client-added member-ctx step: removal, demotion, and join fast paths."""

    if TYPE_CHECKING:

        async def complete_join(
            self,
            chat_id: int,
            chat_title: str,
            owner_id: int,
            owner_fname: str,
            bot: Client,
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

    async def on_bot_added(self, ctx: Ctx) -> None:
        """Handle every change to the bot own member status in any chat."""
        cmc = ctx.chat_member
        if cmc is None:
            return
        changed_user = getattr(getattr(cmc, "new_chat_member", None), "user", None)
        if (
            changed_user is not None
            and getattr(changed_user, "id", None) != (await ctx.bot_identity()).id
        ):
            return
        chat = cmc.chat
        if getattr(chat.type, "value", chat.type) not in (
            "group",
            "supergroup",
            "forum",
        ):
            return
        locale = await locale_for_update(ctx)
        new_member = cmc.new_chat_member
        if new_member is None:
            return
        new_status = new_member.status
        old_status = cmc.old_chat_member.status if cmc.old_chat_member else None
        by_user = cmc.from_user
        if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            # * Read before writing: a concurrent deactivate would answer the
            # * fresh connection check with the post-removal value and drop the
            # * removal audit log. The two writes stay parallel once the fact
            # * they depend on is known.
            try:
                was_connected = await db.groups_db.is_connected(
                    chat_id_of(chat), fresh=True
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug(
                    "is_connected check failed on bot removal from %d: %s",
                    chat_id_of(chat),
                    exc,
                )
                was_connected = False
            cleanup_results = await asyncio.gather(
                db.groups_db.deactivate_group(chat_id_of(chat)),
                db.groups_db.remove_pending(chat_id_of(chat)),
                return_exceptions=True,
            )
            throw_if_cancelled(cleanup_results)
            for label, result in zip(
                ("deactivate", "remove_pending"), cleanup_results, strict=True
            ):
                if isinstance(result, BaseException):
                    log.error(
                        "Client removal cleanup (%s) failed for chat=%d: %s",
                        label,
                        chat_id_of(chat),
                        result,
                    )
            if was_connected:
                try:
                    await messages.send_log(
                        ctx.bot,
                        messages.group_bot_removed_log(
                            chat_id_of(chat), chat.title or "Unknown"
                        ),
                    )
                except Exception:
                    log.exception("Client removed log failed for %d", chat_id_of(chat))
            log.info("Client removed from %d; group deactivated", chat_id_of(chat))
            return
        if (
            new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)
            and old_status == ChatMemberStatus.ADMINISTRATOR
        ):
            if not cfg.is_primary_group(chat_id_of(chat)):
                warning_text = (
                    "Client was demoted in group"
                    f" {bold(chat.title or str(chat_id_of(chat)))}"
                    f" (id: {code(str(chat_id_of(chat)))})."
                    " Federation bans cannot be enforced there until"
                    " admin rights are restored."
                )
                try:
                    await messages.send_log(ctx.bot, warning_text)
                except Exception as exc:
                    log.warning(
                        "Failed to send admin-rights-lost warning for chat=%d: %s",
                        chat_id_of(chat),
                        exc,
                    )
            return
        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
            if cfg.is_primary_group(chat_id_of(chat)):
                try:
                    await db.groups_db.ensure_primary_group(
                        chat_id_of(chat), chat.title
                    )
                except Exception:
                    log.exception(
                        "Primary group registration failed for chat %d",
                        chat_id_of(chat),
                    )
                return
            if cfg.is_infrastructure_chat(chat_id_of(chat)):
                return
            pending, is_already_connected = await asyncio.gather(
                db.groups_db.get_pending(chat_id_of(chat)),
                db.groups_db.is_connected(chat_id_of(chat), fresh=True),
                return_exceptions=True,
            )
            throw_if_cancelled((pending, is_already_connected))
            if isinstance(pending, BaseException):
                log.warning(
                    "get_pending check failed on bot-added for %d: %s",
                    chat_id_of(chat),
                    pending,
                )
                return
            if isinstance(is_already_connected, BaseException):
                log.warning(
                    "is_connected check failed on bot-added for %d: %s",
                    chat_id_of(chat),
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
                # * Re-promotion is a fast path back into the wizard, not an
                # * implicit Connect. The actor must still be the group owner;
                # * pending.owner_id only names the original bot-adder and an
                # * administrator can be a different person.
                actor_id = by_user.id if by_user is not None else 0
                if not actor_id:
                    return
                try:
                    actor_member = await asyncio.wait_for(
                        ctx.bot.get_chat_member(chat_id_of(chat), actor_id),
                        timeout=TELEGRAM_LOOKUP_TIMEOUT,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning(
                        "Re-promote owner lookup failed for chat=%d: %s",
                        chat_id_of(chat),
                        exc,
                    )
                    return
                if actor_member.status != ChatMemberStatus.OWNER:
                    return
                if new_member is not None and self.check_perms(new_member):
                    owner_fname = await db.users_cache.get_first_name(
                        pending.get("owner_id", 0), "Owner"
                    )
                    with contextlib.suppress(Exception):
                        await safe_edit_message(
                            ctx.bot,
                            chat_id_of(chat),
                            pending.get("message_id", 0),
                            self.connecting_message(locale),
                            reply_markup=None,
                        )
                    try:
                        blind = await self.complete_join(
                            chat_id_of(chat),
                            chat.title or "",
                            pending.get("owner_id", 0),
                            owner_fname,
                            ctx.bot,
                        )
                    except Exception:
                        log.exception(
                            "complete_join failed in on_bot_added for chat %d",
                            chat_id_of(chat),
                        )
                        with contextlib.suppress(Exception):
                            await safe_edit_message(
                                ctx.bot,
                                chat_id_of(chat),
                                pending.get("message_id", 0),
                                t("connecting.state.complete_join", locale, plain=True),
                                reply_markup=None,
                            )
                        return
                    welcome_note = await welcome_permission_note(
                        ctx.bot, chat_id_of(chat), locale
                    )
                    try:
                        await safe_edit_message(
                            ctx.bot,
                            chat_id_of(chat),
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
                    "Client added to %d without an attributable admin; "
                    "prompting the group creator",
                    chat_id_of(chat),
                )
            try:
                prompt = await send_text(
                    ctx.bot,
                    chat_id_of(chat),
                    self.verify_prompt(0, locale),
                    reply_markup=self.verify_keyboard(0, locale),
                )
                await db.groups_db.add_pending(
                    chat_id_of(chat), chat.title or "", owner_id, prompt.id
                )
            except Exception:
                log.exception("Join prompt send failed for %d", chat_id_of(chat))


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
        )

    def connected_blind_message(self, locale: str | None = None) -> str:
        """Blind-replay warning shown instead of the success message."""
        return t(
            "connecting.state.connected_blind",
            locale,
            community=self.community_name,
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
        """Return True when the member's admin rights cover every required permission."""
        # * Kurigram keeps admin rights under ChatMember.privileges; a flat
        # * getattr on the member returns False for every right, which used to
        # * block every connect path. A missing privileges object means no rights.
        privileges = getattr(member, "privileges", None)
        if privileges is None:
            return False
        return all(getattr(privileges, name, False) for name in self.required_perms)


connection = BuildConnection(cfg.community_name)
