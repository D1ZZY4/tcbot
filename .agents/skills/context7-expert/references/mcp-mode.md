# MCP Mode

Full detail for when a Context7 MCP server is connected and its tools appear directly in the
tool list.

## Tool name variance

Context7's MCP tools have gone by more than one name across versions and forks. Check the
actual tool list rather than assuming one fixed name:

- **Resolve step**: usually `resolve-library-id`, but confirm against what's actually
  available.
- **Fetch step**: usually `get-library-docs` in most current deployments, but some versions
  and integrations expose it as `query-docs`. Use whichever one is actually present.

Never guess a tool name and call it blind, check the tool list first. If somehow both a
resolve-style and a fetch-style tool are present under different names than expected, use the
one whose description matches "resolve a library name to an ID" and "fetch documentation for a
library ID" respectively.

## Step 1: Resolve the library ID

Call the resolve tool with:

- **Library name**: extracted from the user's question, using the library's proper official
  name and punctuation (for example, "Next.js" not "nextjs", "Three.js" not "threejs").
- **Query**: the user's actual question or intent, not just the library name alone. This is
  required and directly affects relevance ranking.

Do not include any sensitive or confidential information (API keys, passwords, credentials,
personal data, proprietary code) in the query.

Skip this step only when the user already gave an exact ID in `/org/project` or
`/org/project/version` format.

For the full selection criteria once results come back, see
`selection-and-query-writing.md`.

## Step 2: Fetch the documentation

Call the fetch tool with:

- **Library ID**: the exact ID selected in Step 1, e.g. `/vercel/next.js`.
- **Query**: scoped to a single concept, see `selection-and-query-writing.md` for what makes
  a query good versus too vague or too broad.

If the question spans multiple distinct concepts (routing and auth and caching, for example),
make a separate fetch call per concept with the same library ID, rather than combining them
into one, unless the question is specifically about how the concepts interact with each
other. Combined queries dilute ranking and return shallow results for every topic at once.

## Step 3: Use the documentation

- Answer using the current, fetched information, not what you remember from training.
- Include relevant code examples straight from the docs.
- Mention the library version when it's relevant to the answer, especially if the user asked
  about a specific version.

## Error handling

This matters as much in MCP mode as it does in CLI mode, don't skip it just because there's no
CLI output to parse. If a call fails, times out, returns an empty or clearly unhelpful result,
or the server reports a rate limit or quota issue:

1. Tell the user plainly what happened, don't just go silent about it.
2. Try once more with a more specific query if the failure looked like a ranking/relevance
   miss rather than an outage.
3. If it's still not working after a couple of attempts (see the 3-call cap in SKILL.md), fall
   back to training knowledge and clearly say the answer might be outdated, rather than
   presenting it with the same confidence as a Context7-backed answer.

Never silently fall back to training data without saying so. The user should always be able to
tell whether an answer came from live docs or from training knowledge.
