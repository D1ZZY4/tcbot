# Proof migration runbook

This runbook moves every stored ban proof from the old proof chat into a new
channel and repoints every reference at the new messages. It uses the
one-shot operator script in [`../../scripts/migrate_proofs.py`](../../scripts/migrate_proofs.py).
The bot itself is not part of the script; the script talks to MongoDB and
Telegram directly.

## What gets migrated

- Every ban proof and previous proof stored in the `bans` collection
  (`proof_message_id`, `previous_proof_message_id`).
- Album proofs (media groups) are copied whole; Telegram keeps the album
  grouping when the messages are copied.
- The proof deep-link buttons on the stored ban log messages are rewritten
  (`chat_id`/`message_id` and the `?thread=` suffix are matched, so forum
  links and plain links both hit). Log message text does not contain proof
  links; only buttons need rewriting.
- Old proof links inside copied proof captions (for example the "Previous"
  link on a re-ban proof caption) are rewritten in place.

Kick, mute, and warn proofs are not stored (no message ids in the database),
so there is nothing to repoint for them. The transient "View Proof" buttons
in `/check` cards are rendered per request from `PROOFS` and the stored
message id, so they follow the migration automatically.

## Prerequisites

- The bot is stopped. The script logs in to MTProto with the bot token using
  its own session file, so the bot must not be running (two bot-token MTProto
  logins collide).
- The bot is an administrator of both the old proof chat (read + copy) and
  the new channel (post).
- The bot can edit its own messages in the logs chat (it sent the ban log
  messages, so it can rewrite their buttons).
- The environment provides `BOT_TOKEN`, `MONGODB_URI`, `API_ID`, `API_HASH`,
  and optionally `DB_NAME` (default `tcbot`). The script reads the process
  environment directly (no `config.env` dotenv), so export the variables
  before running rather than relying on the file.

## Steps

Run from the repository root with the production environment loaded:

```bash
uv run python scripts/migrate_proofs.py --help
```

1. Dry run first. It only reads and prints the plan:

   ```bash
   uv run python scripts/migrate_proofs.py \
     --old-proof-chat <OLD_ID> \
     --logs-chat <LOGS_ID>
   ```

   The destination defaults to `-1003997518221`; pass
   `--new-proof-chat` to use a different channel. `--logs-chat` is the
   audit-log destination (the `LOGS` chat, without any thread part).

2. Check the printed count (`bans with proofs` / `pending`) and spot-check
   a few bans. Re-run with `--ban-id <BAN_ID>` to limit the sweep to one
   record, or `--limit N` to try the first N pending records.

3. Apply (with the bot stopped):

   ```bash
   uv run python scripts/migrate_proofs.py \
     --old-proof-chat <OLD_ID> \
     --logs-chat <LOGS_ID> \
     --apply
   ```

   Each finished ban is recorded in `proof_migration_state.json` right after
   its copies land, so an interrupted run resumes without re-copying.
   Keep the state file until the migration is verified.

4. Point the bot at the new channel: set `PROOFS=-1003997518221` in the
   production environment (a plain channel, so no `/thread_id` part).

5. Restart the bot and verify:
   - `/check <user>` shows "View Proof" and the link opens the new channel.
   - An old ban log message in the logs chat now opens the copied proof.
   - A new `/tcban` uploads its proof into the new channel.

## Failures and recovery

- A ban whose old proof message was deleted from the old chat is reported
  ("old proof ... not found (deleted?)") and left untouched; there is
  nothing to copy for it.
- A per-ban error never stops the sweep; the exit code is non-zero when any
  ban failed. Fix the cause and re-run; the state file skips finished bans
  and reuses the recorded copies instead of duplicating messages.
- Flood waits are slept through once (up to 300 seconds). A longer wait
  aborts the run; re-run to resume.
- If the state file is lost, the script cannot tell migrated ids from old
  ones and old-proof lookups fail as "not found" without changing anything.
  It never rewrites a record it could not read back.
