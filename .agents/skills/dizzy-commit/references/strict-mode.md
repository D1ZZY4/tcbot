# Strict Mode Rules

Apply these on top of the default rules in SKILL.md when strict mode is active.

## Author policy

Use the repository's configured Git author by default. If repository policy requires a specific
author, verify that policy and ask for approval before changing `user.name`, `user.email`, or
signing configuration. Never invent an identity, provider email, or project-specific address.

Verify the resulting author with:

```bash
git log -1 --format="%an <%ae>"
```

If the author does not satisfy an explicit repository policy and the commit has not been pushed,
stop and ask before amending or changing configuration. Never rewrite a commit that is already
public unless the user explicitly instructs it.

## Rules

- **Language.** Follow the repository's documented commit language or the user's explicit
  preference. Do not impose English when the project uses another convention.
- **Scope.** Require `type(scope): summary` only when repository policy requires it. Otherwise,
  use a meaningful scope when one is clear and do not invent one.
- **Body.** Require a Markdown body when repository policy requires it or when the change is
  non-trivial. Never hide the why for a non-trivial change.
- **No em dashes.** Not in the subject, not in the body, not anywhere in the message. En
  dashes are allowed as normal punctuation, but literal shell commands, flags, and paths must
  keep the plain ASCII hyphens they require. Use a comma, colon, period, or parentheses
  instead of an em dash.
- **No emoji.** Not in the subject, not in the body, ever.
- **One concern per commit.** Must be reversible without losing unrelated work. If you find
  yourself writing "and also," split it.
- **Never bundle unrelated files.** A single commit touching 15+ files across 5 different
  concerns is an AI anti-pattern. Split by concern.
- **Prohibited words.** Apply only the words configured by repository policy or explicitly
  requested by the user.
- **No generic summaries** like "Update agent documentation while refreshing..." or "Address
  findings from audit." Write the actual change. A `Co-authored-by` trailer for an agentic tool
  is still fine when the provider supplied a valid identity.
- **Derive the message from the real diff**, never from a checklist or plan document.
- **Verify before committing.** Run the project's declared and relevant verification commands
  before each commit. If a typecheck, lint, or build command is unavailable or not relevant,
  report that it was skipped. A failing available check means the commit is incomplete.
- **Never amend or squash commits already pushed to the configured upstream** unless explicitly
  instructed. Rewriting public history breaks the branch for everyone.

## Example of a good commit

```
fix(validation): reject unsafe URL schemes

Reject `javascript:` and `data:` URLs in the request schema for
user-controlled links.

Mirror the existing validation used by the related display component.
```

## Another good example, with a breaking change

```
feat(api)!: rename checkout endpoint

BREAKING CHANGE: clients on `/v1/orders` must migrate to `/v1/checkout`
before the documented sunset date. The old route returns 410 after that date.

Consolidates the order flow into one checkout resource so clients only
have one endpoint to poll for status.
```

## Example of a bad commit (do not do this)

```
refactor: combine unrelated maintenance changes

Security:
- Remove an unrelated note from a feedback form
- Add URL scheme guards for user-controlled links

Bug fixes:
- Wire filter variants into a brand filter
- Replace inconsistent shape tokens across several components
...
```

Several unrelated changes in one commit, with no useful scope. Split
them into focused commits, each describing one logical change.
