# Rule: Use Context7 for Library Documentation

Use Context7 MCP to fetch current documentation whenever you need accurate
method signatures, class constructors, config keys, async API behavior, version
migration details, or setup instructions for any library in this project --
even ones you think you know well. Training data may not reflect the installed
version. Prefer Context7 over web search for library docs.

Do not use for: refactoring business logic, writing custom TCF Bot logic from
scratch, debugging non-library issues, code review, or general Python concepts.

## Steps

1. Call `resolve-library-id` with the library name (as it appears in
   `pyproject.toml`) and your specific question as the query. Skip this step
   only if you already have an exact library ID in `/org/project` format.

2. Pick the best match from results by: exact name match, description
   relevance, benchmark score (higher is better), and source reputation
   (High/Medium preferred). If results do not look right, try alternate names
   (e.g., `"telegram"` instead of `"python-telegram-bot"`) or rephrase the
   query. When the installed version is pinned in `uv.lock`, prefer
   version-specific IDs when available.

3. Call `query-docs` with the selected library ID and your full question as the
   query (not single keywords).

4. Apply the fetched docs. If the version described differs from what is
   installed, note the discrepancy and inspect the installed source as
   fallback (see SKILL.md). Record significant findings in
   `.agents/memory/decisions.md`.

## Non-Negotiable Cases

Always run a Context7 lookup before writing any code for these:

- `python-telegram-bot`: handler registration, filter composition, Application
  lifecycle, ConversationHandler states, JobQueue API.
- `motor`: AsyncIOMotorClient, AsyncIOMotorCollection, cursor methods, session
  handling.
- `pydantic`: model validators, field types, model_config (v1 vs v2 differ
  completely).
- `ruff`: rule codes, pyproject.toml config keys, per-file ignores syntax.

## MCP Server Configuration

```json
"mcpServers": {
  "context7": {
    "type": "http",
    "url": "https://mcp.context7.com/mcp",
    "headers": {
      "CONTEXT7_API_KEY": "ctx7sk-dd2eaf71-a84c-41be-9bf0-37dd32e68c61"
    }
  }
}
```