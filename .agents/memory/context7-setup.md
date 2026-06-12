---
name: Context7 CLI setup
description: How ctx7 CLI is installed and configured in this Replit project
---

## Rule
Use `ctx7` CLI (npm package `ctx7`) to fetch live library docs. The binary auto-reads `CONTEXT7_API_KEY` from the environment — no prefix or manual export needed.

**Why:** The `@context7/cli` package does not exist on npm. The `context7` package (v1.0.3) installs as `c7` and hits a dead API (404). Only the `ctx7` package has the correct `library` and `docs` subcommands.

**How to apply:**
```bash
# Resolve library ID
ctx7 library "python-telegram-bot" "your question"

# Fetch docs
ctx7 docs "/python-telegram-bot/python-telegram-bot" "your specific question"
```

## Installed location
- Installed via: `npm install -g ctx7`
- Binary: `/home/runner/workspace/.config/npm/node_global/bin/ctx7`

## MCP config files
Both `.agents/mcp.json` and `.roo/mcp.json` use `${CONTEXT7_API_KEY}` placeholder (not hardcoded). Secret `CONTEXT7_API_KEY` is stored in Replit Secrets.

## Verified library IDs (June 2026)
| Library | ID | Benchmark |
|---|---|---|
| python-telegram-bot | `/python-telegram-bot/python-telegram-bot` | 86.8 |
| python-telegram-bot (alt) | `/websites/python-telegram-bot_en_stable` | 71.3 |
| motor | `/mongodb/motor` | 85.86 |
