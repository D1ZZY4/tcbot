#!/usr/bin/env python3
# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Seed operator-local rule documents into the bot's community rules feature.

The application reads one content locale (``en-US``); rule bodies have no
locale column, so seeding an ``id-ID`` version would create content the bot
cannot display. This script publishes the parsed ``rules/*.md`` documents as
a single new version in the working locale, leaving exactly one published
version and no open draft.

Usage:

    uv run python scripts/seed_rules.py --dry-run
    uv run python scripts/seed_rules.py --user-id 123456789

The database URL is read from ``config.env``/``.env`` or the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import find_dotenv, load_dotenv

if TYPE_CHECKING:
    from collections.abc import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import rules_import  # noqa: E402
from tcbot import database as db  # noqa: E402
from tcbot.database import engine as db_engine  # noqa: E402
from tcbot.utils.logger import get_logger  # noqa: E402

log = get_logger("tcbot.seed_rules")

# * The catalogue keys created by get_or_create_community_set(); documents
# * map to one of these so the channel renderer groups them correctly.
_CATEGORIES = {
    "sanksi": "conduct",
    "pengelola": "conduct",
    "spam": "spam",
    "promosi": "spam",
    "penipuan": "safety",
    "doxing-dan-privasi": "safety",
    "identitas": "safety",
    "cheat": "conduct",
    "mod-apk-dan-bajakan": "content",
    "module-root": "content",
    "konten-pornografi-nsfw": "content",
    "materi-pengujian": "content",
    "karya-dan-atribusi": "content",
    "perundungan-dan-kebencian": "safety",
    "politik": "other",
    "transaksi": "other",
    "out-off-topic": "other",
}


def _category(filename: str) -> str:
    return _CATEGORIES.get(Path(filename).stem, "other")


async def _seed(folder: Path, user_id: int, *, dry_run: bool) -> int:
    parsed = rules_import.parse_rules(folder)
    items = [
        (_category(filename), title, body)
        for filename, pairs in parsed.items()
        for title, body in pairs
    ]
    if not items:
        print(f"No rule documents found in {folder}")
        return 0
    print(f"Parsed {len(items)} rule items from {len(parsed)} documents")
    if dry_run:
        for category, title, _ in items[:10]:
            print(f"  [{category}] {title}")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")
        return 0

    await db_engine.connect()
    try:
        rule_set = await db.rules_db.get_or_create_community_set()
        set_id = int(rule_set["id"])
        draft = await db.rules_db.open_draft(set_id, user_id)
        version_id = int(draft["id"])
        for category, title, body in items:
            await db.rules_db.add_item(version_id, category, title, body)
        await db.rules_db.promote_version(version_id, user_id)
        published = await db.rules_db.published_version(set_id)
        if published is None:
            raise RuntimeError("seed produced no published version")
        print(
            f"Published version {published['version_number']} with {len(items)} items"
        )
        return 0
    finally:
        await db_engine.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run one seed operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="parse only, no writes")
    parser.add_argument(
        "--user-id",
        type=int,
        default=0,
        help="Telegram user id recorded as creator/publisher (0 uses OWNER_ID)",
    )
    parser.add_argument(
        "--rules-dir",
        type=Path,
        default=_ROOT / "rules",
        help="folder of rule Markdown documents",
    )
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv("config.env") or find_dotenv(".env"))
    user_id = args.user_id or int(os.environ.get("OWNER_ID", "0") or 0)
    folder = args.rules_dir
    if not folder.is_dir():
        print(f"Rules folder not found: {folder}")
        return 1
    if not args.dry_run and user_id <= 0:
        print("OWNER_ID or --user-id must be a positive Telegram user id")
        return 1
    return asyncio.run(_seed(folder, user_id, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
