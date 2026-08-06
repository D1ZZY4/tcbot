# Risk and Operation Budget

Context7 lookups need a finite budget, but one fixed number is not appropriate for every
question. Choose the smallest budget that can answer the question reliably.

## Risk tiers

### Low risk

Examples:

- one library, one stable concept
- a general API usage question with a clearly specified version
- a documentation lookup where a single fetch is likely to answer the question

Use a budget of up to **3 operations**:

1. resolve the library, unless an exact ID was provided
2. fetch the documentation
3. one focused retry or second concept only when necessary

### Medium risk

Examples:

- framework configuration
- version-sensitive setup
- an error involving a specific library
- two tightly related concepts in one library

Use a budget of up to **5 operations** when the extra calls have a clear purpose. State what
remains unchecked if the budget runs out.

### High risk

Examples:

- authentication or authorization behavior
- payments, billing, or data migration
- security-sensitive configuration
- a breaking-version migration
- multiple libraries whose compatibility matters

Use a budget of up to **7 operations** only when the extra verification is necessary. Prefer
official or version-specific documentation, and state which version and source were checked.

## Rules for increasing the budget

- Do not increase the budget merely because a query was vague or poorly written.
- Do not retry the same failed query more than once without changing the query or mode.
- Count resolution, fetches, retries, and alternate-library checks as operations.
- Stop when the remaining uncertainty is not worth another call, then report it honestly.
- Never use the adaptive budget to bypass approval for network access, setup, installation, or
  authentication.