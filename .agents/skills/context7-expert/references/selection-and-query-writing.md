# Library Selection and Query Writing

Shared by both `mcp-mode.md` and `cli-mode.md`, the resolve/fetch mechanics differ by mode but
these criteria are identical either way.

## Result fields to weigh

Each resolved library result typically includes:

- **Library ID**: the Context7-compatible identifier, format `/org/project`.
- **Name**: the library or package name.
- **Description**: a short summary.
- **Code Snippets**: how many code examples are available.
- **Source Reputation**: authority indicator, High, Medium, Low, or Unknown.
- **Benchmark Score**: quality indicator, 100 is the highest.
- **Versions**: available versions, if any. Use one matching what the user specified, format
  `/org/project/version`.

## Selection process

1. Analyze the query to understand what library or package the user actually wants.
2. Select the best match based on:
   - Name similarity to the query, exact matches prioritized
   - Description relevance to the query's intent
   - Documentation coverage, prefer libraries with higher code snippet counts
   - Source reputation, prefer High or Medium over Low or Unknown
   - Benchmark score, higher is better
3. If multiple good matches exist, acknowledge that briefly but proceed with the most
   relevant one rather than stalling on the ambiguity.
4. If no good match exists, say so clearly and suggest query refinements instead of guessing.
5. For genuinely ambiguous queries (the library name alone could mean two unrelated things),
   ask for clarification before proceeding with a best-guess match.
6. When multiple matches are otherwise similar, prefer the official or primary package over
   community forks.
7. If the user mentioned a version, prefer a version-specific library ID when one's available
   from the resolution results.

## Writing good queries

The query directly affects result quality, in both the resolve step and the fetch step.

- Be specific and describe what to look up in the library's documentation, not the broader
  task you're trying to accomplish.
- Keep each query to a single concept. If the question spans multiple distinct topics, run a
  separate fetch call per concept instead of combining them, unless the question is
  specifically about how the concepts interact with each other.
- Never include sensitive or confidential information (API keys, passwords, credentials,
  personal data, proprietary code) in a query.

| Quality | Example |
|---------|---------|
| Good | "How to set up authentication with JWT in Express.js" |
| Good | "React useEffect cleanup function with async operations" |
| Bad, too vague | "auth" |
| Bad, too vague | "hooks" |
| Bad, too broad | "routing and auth and caching in Next.js" |

Vague one-word queries return generic, low-value results. Multi-topic queries dilute ranking
and return shallow results for every topic at once instead of a deep result for one.
