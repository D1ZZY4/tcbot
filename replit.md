# TCF Bot - Replit Deployment Guide

Deploying TCF Bot on Replit requires specific configuration for secrets,
keep-alive, and Kurigram long polling. This guide covers Replit-only setup.

For general project documentation, see [`README.md`](README.md).
For contributor rules and code style, see [`AGENTS.md`](AGENTS.md).

---

## Replit Secrets

Do not use `config.env` on Replit. Store all secrets in the Replit Secrets
manager (the lock icon in the sidebar).

Required secrets:

- `BOT_TOKEN`: Telegram bot token from BotFather.
- `DATABASE_URL`: PostgreSQL connection string.
- `OWNER_ID`: Telegram user ID for the initial federation Owner.
- `PROOFS`: Evidence destination; boot refuses without a negative group or channel chat ID.
- `API_ID`: Telegram API ID for MTProto identity lookups; boot refuses without it.
- `API_HASH`: Telegram API hash matching `API_ID`; boot refuses without it.

Optional secrets:

- `REDIS_URL`: Redis connection URL for L2 cache.
- `PORT`: Flask keep-alive port. Use a local port that the `[[ports]]`
  mapping in `.replit` publishes. The repository maps the default `5000`;
  a polling client only reaches the value you configure, so add a mapping for
  a different `PORT`. An unset or invalid value falls back to `5000`, which
  the same file publishes.

Replit Secrets are injected as environment variables at runtime. They are
never committed to the repository and do not require a `.env` file.

---

## Run Command

The Replit run command is:

```bash
uv run python -m tcbot
```

This starts the bot in Kurigram long-polling mode.

---

## Replit-Specific Configuration

### Keep-Alive Server

The Flask keep-alive server binds to `${BIND_HOST}:${PORT}`. `BIND_HOST`
defaults to `0.0.0.0`, which is what Replit's proxy expects. The bot starts
this server automatically before connecting to Telegram.

Set `PORT` to a local port the `[[ports]]` mapping in `.replit` publishes.
An unmapped port still binds locally, but the health endpoints become
unreachable through the Replit proxy. Polling needs no inbound port.

If `PORT` is unset, invalid, or outside `1..65535`, the application defaults
to `5000`, and the `5000` mapping in `.replit` publishes that default.

### Transport

The bot always uses Kurigram long polling. No public URL, dev domain, or update
registration with Telegram is required. Replication is achieved by running
exactly one process per bot token.

### Nix Configuration

Ensure the `.replit` file contains (TOML array form):

```toml
[deployment]
run = ["uv", "run", "python", "-m", "tcbot"]
```

For Python 3.14, the Replit Nix `modules` already pins `python-3.14` (`modules = ["nix", "python-3.14", "nodejs-24"]`). If using a custom `pyproject.toml`, ensure the Replit Python version meets `requires-python = ">=3.14"`.

---

## Dependencies

Install dependencies with:

```bash
uv sync --frozen
```

The `uv.lock` file ensures reproducible installs on Replit. Do not commit
`config.env` with real credentials.

---

## Deployment Checklist

- [ ] `BOT_TOKEN` set in Replit Secrets.
- [ ] `DATABASE_URL` set in Replit Secrets.
- [ ] `OWNER_ID` set in Replit Secrets.
- [ ] `PROOFS` set to the evidence group or channel.
- [ ] `API_ID` set in Replit Secrets.
- [ ] `API_HASH` set in Replit Secrets.
- [ ] Run command is `uv run python -m tcbot`.
- [ ] `uv sync --frozen` has been run after dependency changes.
- [ ] Flask keep-alive is running on the assigned `PORT`.
- [ ] Bot status shows connected in Telegram.

---

## Troubleshooting

### Bot does not start

Check the Replit console output for missing environment variables. Ensure all
required secrets are set in the Replit Secrets manager.

### Bot does not receive updates

Confirm a single bot process is running; two clients polling the same token conflict.

### Keep-alive not responding

Ensure the Flask server is listening on `${BIND_HOST}:${PORT}` (`BIND_HOST`
defaults to `0.0.0.0`) and that the Replit proxy is forwarding to the correct
port. The `/health` endpoint should return
JSON with subsystem status.

### PostgreSQL connection errors

Verify `DATABASE_URL` is correct and that the PostgreSQL instance is
reachable from the Replit environment. Use a managed instance with a public
connection string, and allow the Replit outbound addresses in the provider's
network allowlist.

---

## Local Development vs Replit

| Aspect | Local Development | Replit Deployment |
|---|---|---|
| Secrets | `config.env` file | Replit Secrets manager |
| Transport | Kurigram long polling | Kurigram long polling |
| Dependencies | `uv sync --frozen` | `uv sync --frozen` |
| Run command | `uv run python -m tcbot` | `uv run python -m tcbot` |
| PostgreSQL | Local or managed | Managed or external |
| Redis | Optional local | Optional external |
