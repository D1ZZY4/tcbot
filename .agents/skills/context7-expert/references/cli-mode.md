# CLI Mode

Full detail for when no Context7 MCP server is connected but a shell/bash tool is available.
Uses the `ctx7` CLI via `npx`, so no global install is required for it to work.

## Running commands

Prefer running through `npx` so it always resolves to the latest CLI without needing a global
install first:

```bash
npx ctx7@latest library <name> "<query>"
npx ctx7@latest docs <libraryId> "<query>"
```

A global install is fine too if it's already present or the user prefers a bare `ctx7`
command, but don't require it, `npx` works out of the box.

```bash
npm install -g ctx7@latest    # optional
```

## Step 1: Resolve a library

```bash
npx ctx7@latest library "Next.js" "How to set up app router with middleware"
```

You MUST run this first to get a valid library ID, UNLESS the user already gave one directly
in `/org/project` or `/org/project/version` format.

- Use the library's proper official name and punctuation ("Next.js" not "nextjs",
  "Customer.io" not "customerio", "Three.js" not "threejs"). If results look wrong, try an
  alternate spelling before rewriting the whole query.
- Always pass a query argument, it's required and directly affects ranking.
- Do not include sensitive or confidential information (API keys, passwords, credentials,
  personal data, proprietary code) in the query.

For the selection criteria once results come back, see `selection-and-query-writing.md`.

Library IDs require a leading `/`, for example `/facebook/react`, not `facebook/react`.

### Version-specific IDs

```bash
# General (latest indexed)
npx ctx7@latest docs /vercel/next.js "How to set up app router"

# Version-specific
npx ctx7@latest docs /vercel/next.js/v14.3.0-canary.87 "How to set up app router"
```

The available versions are listed in the `library` command's output, use the closest match to
whatever the user specified.

## Step 2: Query documentation

```bash
npx ctx7@latest docs /facebook/react "How to clean up useEffect with async operations"
```

See `selection-and-query-writing.md` for query-writing rules, they apply the same way here as
in MCP mode.

The output contains two kinds of content: code snippets (titled, language-tagged blocks) and
info snippets (prose explanations with breadcrumb context).

Useful flags for scripting or filtering large output:

```bash
npx ctx7@latest library react "How to use hooks for state management" --json | jq '.[0].id'
npx ctx7@latest docs /facebook/react "How to use hooks" --json
npx ctx7@latest docs /vercel/next.js "middleware for route protection" | grep -A5 "middleware"
```

## Call budget

Do not run `library` or `docs` more than 3 times total per question. If you still don't have
what you need after 3 attempts, use the best result you have and say so.

## Authentication

Works without authentication. For higher rate limits:

```bash
# Option A: environment variable
export CONTEXT7_API_KEY=your_key

# Option B: OAuth login
npx ctx7@latest login
```

```bash
npx ctx7@latest login               # opens browser for OAuth
npx ctx7@latest login --no-browser  # prints a URL instead
npx ctx7@latest logout              # clear stored tokens
npx ctx7@latest whoami              # show current login status
```

## Error handling

If a command fails with a quota error ("Monthly quota reached" or "quota exceeded"):

1. Tell the user their Context7 quota is exhausted, plainly.
2. Suggest authenticating for higher limits: `npx ctx7@latest login`.
3. If they can't or don't want to authenticate, answer from training knowledge and clearly
   note it may be outdated.

Never silently fall back to training data, always say why Context7 wasn't used.

## Common mistakes to avoid

- Library IDs require a `/` prefix, `/facebook/react` not `facebook/react`
- Always resolve first, `npx ctx7@latest docs react "hooks"` fails without a valid ID from
  the `library` step
- Use descriptive queries, not single words, `"React useEffect cleanup function"` not
  `"hooks"`
- One topic per query, split multi-concept questions into separate `docs` calls per concept,
  unless the question is specifically about how the concepts interact
- Never put sensitive information (API keys, passwords, credentials) in a query
