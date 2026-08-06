# Message Style Rules

Full detail for Step 3 in SKILL.md.

## Format

```
<type>(<scope>): <short imperative summary>

<body, when required by policy or change complexity, markdown>
```

## Subject line

- Scope is policy-controlled. Use `type(scope): summary` when repository policy requires it or
  when a meaningful scope is clear. Do not invent a scope just to satisfy a generic template.
- Pick the scope from the area actually changed: a module name, package, folder, feature, or
  component. Examples: `feat(api)`, `fix(auth)`, `docs(readme)`, `refactor(ui)`. Keep it
  short, lowercase, one word or short-hyphenated when possible.
- Imperative mood: "add", "fix", "remove", never "added", "adds", "adding"
- Short and punchy: aim 50 characters or less, soft cap around 72
- No trailing period
- No em dashes, ever. Not in the subject, not in the body, not anywhere in a commit message.
  Use a comma, colon, period, or parentheses instead.
- En dashes (Unicode U+2013) are allowed when used as normal punctuation. They must not
  replace the plain ASCII hyphens required by a literal command, flag, or path. For example,
  `--recurse-submodules` must keep its two ASCII hyphens or it will break when copied and
  pasted into a terminal. Double check any line containing a command or path before putting
  it into the message.
- No emoji, ever. Not even if it seems fitting or the project uses them elsewhere.
- Follow the repository's documented commit language or the user's explicit preference.

## Body: policy- and complexity-dependent

- Add a body when repository policy requires it or when the change is non-trivial. Explain the
  why in a sentence or two whenever the diff does not make it obvious. A subject-only commit is
  acceptable for a genuinely trivial change when project policy allows it.
- Must use Markdown formatting: bullets (`-`), inline code, bold, headers all fine. A body
  that is a single unformatted sentence is fine content-wise, but reach for Markdown structure
  (bullets, code spans) whenever there is more than one point to make.
- Explain what and why, not how.
- Write it like a senior developer's commit, not a changelog or an AI status update. Don't
  enumerate every single file, asset, or doc that was touched as a checklist. Group related
  files into one bullet if they're the same concern (for example, "update 8 READMEs to point
  at the renamed LICENSE file" is one bullet, not eight). A body with more than about 4 to 5
  bullets is a sign the commit itself should have been split, not that the body needs more
  lines. If you catch yourself listing filenames one after another with no synthesis, stop and
  compress it into what actually changed conceptually.
- No em dashes or emoji in the body either. En dashes are allowed as normal punctuation;
  literal commands, flags, and paths must still use plain ASCII hyphens.
- Wrap prose around 72 characters.
- Reference issues at the end when relevant: `Closes #42`, `Refs #17`.
- Breaking changes, security fixes, data migrations, and reverts always get a fuller body.
  Never compress these into a one-liner.

## Never include

- "This commit does X", "I", "we", "now", "currently"
- Inline prose like "As requested by..." or "Generated with X", use the `Co-authored-by`
  trailer instead (see below) rather than mentioning AI involvement in the subject or body
- Any emoji, under any circumstance
- Any em dash, under any circumstance
- Any word or phrase prohibited by the resolved repository or user policy
- Generic AI summaries like "Update documentation" or "Address findings from audit"

## AI co-author trailer

If the work was done with an agentic coding tool and that provider supplies an official
co-author identity for the agent, it's fine
to add a `Co-authored-by` trailer at the very end of the body, after everything else,
including any issue references. This is standard git practice, not an AI summary. Format
(illustrative only, use whatever real address the tool actually provides, and the actual
specific model/version that did the work):

```
Co-authored-by: <specific model name and version> <the agent's actual noreply address>
```

Rules for this trailer:

- **Canonical format**: `Co-authored-by: Name <email>`, capital `C`, lowercase everything
  else. This is the conventional casing used by common Git tooling, so it's the default to
  write.
- **Casing is not functionally required, but stay consistent anyway.** Git trailer keys are
  case-insensitive per the trailer spec, so `Co-Authored-By` or other casing variants are
  still recognized as the same trailer by Git tooling, a differently-cased trailer is not
  actually broken. Default to the canonical casing above regardless, for consistency across
  the project's history, not because the alternative fails.
- **The email must be wrapped in angle brackets**, `<email>`, never bare. This part is
  functionally required: a trailer without the brackets is not a valid trailer at all and
  won't be recognized as co-authorship by Git tooling, it'll just look like plain text sitting
  at the end of the commit.
 - Not valid, missing brackets: `Co-authored-by: Agent model/version provider-address`
 - Valid, canonical casing: `Co-authored-by: Agent model/version <provider-address>`
 - Valid, non-canonical casing but still recognized: `Co-Authored-By: Agent model/version
   <provider-address>`, still write the canonical casing by default even though this
  works, for consistency
- Only use an email the provider actually issued for this purpose, never invent one.
- **Use the specific model name and version, not just the generic tool name.** A specific model
  name and version tells a future reader more than a bare tool name, since different models and
  versions can have different quirks. If a non-default configuration is relevant and known,
  such as an extended context window or reasoning mode, it is fine to note it in parentheses
  after the name. Don't guess or round this information. Only include what is actually known to
  be true for the task, and prefer an unlabeled generic name over a fabricated specific one.
- It goes at the bottom, as its own line, after a blank line separating it from the rest of
  the body. Never woven into a sentence.
- Which tool gets credited, and in what exact name/email format, is up to whichever
  agent actually did the work. If multiple tools contributed, multiple `Co-authored-by`
  lines are fine.
- This trailer is the only acceptable place AI involvement shows up in a commit message.
  Nothing else in the subject or body should reference it.

## Commit type reference

| Type | When to use |
|------|-------------|
| `feat` | New feature or behaviour |
| `fix` | Bug fix |
| `chore` | Tooling, config, deps. No production code change |
| `docs` | Documentation only |
| `refactor` | Restructure without behaviour change |
| `style` | Formatting, whitespace. No logic change |
| `perf` | Performance improvement |
| `test` | Adding or fixing tests |
| `build` | Build system or dependencies |
| `ci` | CI configuration |
| `revert` | Reverting a prior commit |

Breaking change: append `!` after type/scope, explain in body with `BREAKING CHANGE: ...`.
