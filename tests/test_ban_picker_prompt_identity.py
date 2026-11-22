# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The rules-picker path records the proof prompt used by stale-tap guards."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from tcbot.modules.helper.pipelines import ban_rules_step
from tcbot.modules.helper.scope import flow_scope

_CHAT = -100
_MESSAGE = 42


def _update_with_edited_prompt() -> tuple[Any, Any, dict[str, Any]]:
    async def _answer(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _edit(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(message_id=_MESSAGE, chat=SimpleNamespace(id=_CHAT))

    query = SimpleNamespace(
        data="rules_step:done",
        message=SimpleNamespace(chat=SimpleNamespace(id=_CHAT), message_id=_MESSAGE),
        answer=_answer,
        edit_message_text=_edit,
    )
    update = cast(
        "Any",
        SimpleNamespace(
            callback_query=query,
            effective_chat=SimpleNamespace(id=_CHAT),
            effective_user=SimpleNamespace(id=7, first_name="Mod"),
            effective_message=None,
        ),
    )
    ctx = cast("Any", SimpleNamespace(user_data={}))
    return update, ctx, flow_scope(ctx, update)


def test_the_callback_prompt_path_records_its_message_identity() -> None:
    update, ctx, scope = _update_with_edited_prompt()
    scope.update(
        {
            "ban_target_id": 99,
            "ban_target_fname": "Target",
            "ban_reason": "reason",
        }
    )

    state = asyncio.run(ban_rules_step._show_proof(update, ctx))

    assert state == ban_rules_step.WAITING_PROOF
    assert scope["ban_prompt_msg_id"] == _MESSAGE
    assert scope["ban_prompt_chat_id"] == _CHAT
