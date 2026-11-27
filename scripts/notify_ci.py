#!/usr/bin/env python3
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Send the CI status notice as a rich message through Kurigram."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyrogram import Client  # noqa: E402

from tcbot.modules.helper.rich.block import html_message  # noqa: E402
from tcbot.modules.helper.rich.formats import heading, paragraph  # noqa: E402
from tcbot.modules.helper.rich.link import link  # noqa: E402
from tcbot.modules.helper.rich.send_msg import send_rich  # noqa: E402


async def _notify() -> None:
    """Send one rich status message to the configured owner."""
    token = os.getenv("BOT_TOKEN", "")
    owner = os.getenv("OWNER_ID", "")
    api_id = os.getenv("API_ID", "")
    api_hash = os.getenv("API_HASH", "")
    run_url = os.getenv("CI_RUN_URL", "")
    if not all((token, owner, api_id, api_hash)) or token.startswith("test:"):
        return
    try:
        receiver = int(owner)
        payload = html_message(
            heading("Dependency Update"),
            paragraph("Dependencies updated"),
            paragraph("Result: PR created"),
            link("View workflow", run_url) if run_url else "",
        )
        async with Client(
            "tcbot-ci-notify",
            api_id=int(api_id),
            api_hash=api_hash,
            bot_token=token,
            in_memory=True,
            no_updates=True,
        ) as client:
            await send_rich(client, receiver, payload)
    except Exception as exc:
        # * Never print the token or the raw exception text: either can carry
        # * a credential-bearing URL from the transport.
        print(f"CI notification failed: {type(exc).__name__}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(_notify())
