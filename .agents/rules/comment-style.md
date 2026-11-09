# Comment and Documentation Style Rules

This file defines standards for inline comments, docstrings, section dividers, and Markdown documentation for TCF Bot.

The goal is to keep code explanations concise, accurate, useful, and maintainable while ensuring project documentation remains consistent.

Code conventions and architecture live in [`code-style.md`](code-style.md), changelog and release documentation rules live in [`changelog-style.md`](changelog-style.md), and tooling and validation requirements live in [`docs/operations/ci-cd.md`](../../docs/operations/ci-cd.md).

This file owns comment and general Markdown conventions. Referenced documents own their respective specialized requirements.

---

## Goals

Comments should explain intent, constraints, risks, or non-obvious behavior.

They should not restate what the code already makes obvious.

Prefer clear names, small functions, and well-defined interfaces over explanatory comments that compensate for unclear code.

Every comment must provide information that cannot be understood as easily from the surrounding code, documentation, or function signature.

## Expert Standard: Concise, Dense, Never Redundant

Use the fewest words necessary to explain the relevant contract.

- Prefer one idea per comment.
- Keep ordinary comments short and close to the code they explain.
- Use direct, natural, professional language.
- Explain why a decision exists, not what an obvious statement does.
- Do not add comments merely to make code look documented.
- Use multiple lines only when security, ordering, failure semantics, races, or migration constraints require additional context.
- Delete stale, speculative, and redundant explanations.

Conciseness must never remove important correctness or safety information.

### Restatement Patterns to Remove

Bad:

```python
# q.answer() and the edit are independent; run in parallel.
await answer_and_edit(q, text, reply_markup=kb)
```

Good:

```python
await answer_and_edit(q, text, reply_markup=kb)
```

The helper's documentation already owns its contract. Do not repeat it at every call site.

Bad:

```python
# Group / supergroup context.
if chat.type in ("group", "supergroup", "forum"):
```

The comment simply repeats the condition.

Bad:

```python
# The main function that starts the entire bot application.
# Configures PTB Application and registers all handlers.
def main() -> None:
    """Configure and start the PTB application..."""
```

The comments duplicate the function's name and docstring.

### Single Source of Truth

- One explanation must have one authoritative home.
- A helper or function docstring owns its documented contract.
- Call sites stay silent unless the call site introduces a specific risk or additional constraint.
- When compressing comments, relocate an important contract instead of deleting it without replacement.
- Place shared contracts in the owning constant, table, class docstring, helper docstring, or relevant `docs/` page.
- When the same rationale appears at three or more sites, move it to the appropriate shared documentation and remove redundant copies.
- Never allow comments and documentation to contradict actual behavior.

### Concurrency Comments

A `gather()` over hand-written coroutines must include a short explanation of why the operations are independent and safe to execute concurrently.

This is necessary because the safety precondition may not be apparent from the call itself.

Concurrency mechanics, failure behavior, cancellation, and timeout requirements belong in [`asyncio-gather-rules.md`](asyncio-gather-rules.md). Do not repeat those rules in inline comments.

### Critical Information Must Remain

Never remove essential explanations concerning:

- Security and authorization constraints.
- Execution ordering and sequencing requirements.
- Failure and retry semantics.
- Race conditions and synchronization.
- Resource ownership and cleanup.
- Migration and compatibility requirements.
- Non-obvious operational constraints.

These explanations take precedence over arbitrary brevity targets.

---

## Better Comments Prefixes

Use the following prefixes in inline Python comments and, when useful, inside docstrings.

| Prefix | Purpose |
|---|---|
| `# ! WARNING:` | Dangerous behavior or security-sensitive constraints. |
| `# ! CRITICAL:` | Correctness or safety requirements that must not be ignored. |
| `# ?` | Questions, uncertainty, or follow-up investigation. |
| `# TODO:` | Deferred work with sufficient context for a future maintainer. |
| `# *` | Important notes, highlights, or non-obvious design intent. |
| `# //` | Temporary review marker identifying existing dead or commented-out code for removal. |

### Examples

```python
# ! WARNING: This operation invalidates every active session.
# ! CRITICAL: This check prevents non-staff users from approving appeals.
# ? Should this use fan_out() after the group count grows further?
# TODO: Add a migration once old ban documents no longer omit proof_link.
# * Telegram albums arrive as separate updates; debounce before final upload.
```

### Prefix Rules

- Use exactly one space after `#`.
- Write `# ! WARNING:` or `# ! CRITICAL:` for warning and critical comments.
- Use `# ?` only when genuine uncertainty or a follow-up decision exists.
- TODOs must include enough context for a future maintainer to understand the task and its reason.
- Remove completed, obsolete, or unsupported TODOs.
- Use `# *` for meaningful design intent, not ordinary code narration.
- Treat `# //` as a temporary review marker only. Remove the marked dead or commented-out code before committing.
- Never use `# //` to temporarily disable working code.
- Do not use double-hash comments such as `## note` in Python modules.

Do not apply prefixes mechanically. Ordinary comments do not need a prefix.

---

## Docstrings

### Module Docstrings

Every Python module requires a single-line module docstring.

Example:

```python
"""Federation ban commands and handler registration."""
```

Module header ordering, copyright requirements, and future imports are defined in [`code-style.md`](code-style.md).

### Function and Method Docstrings

Use function and method docstrings when their purpose, constraints, side effects, or return behavior are not sufficiently clear from their names and signatures.

Rules:

- Explain purpose and non-obvious behavior.
- Document important constraints, side effects, and return contracts when relevant.
- Keep straightforward one-line helpers free of unnecessary docstrings.
- Use multi-line docstrings only when additional detail provides real value.
- Keep docstrings accurate when behavior changes.
- Avoid duplicating type annotations in prose.
- Do not describe implementation details that are obvious from the function body.
- Do not use Sphinx `:param:` or `:returns:` tags.
- Do not use Markdown tables inside Python docstrings.

### Class and Complex Workflow Documentation

Class docstrings should explain responsibility, ownership, and relevant constraints.

For complex workflows, document:

- The purpose of the workflow.
- Important state or lifecycle constraints.
- Non-obvious ordering requirements.
- Side effects or external interactions.
- Important failure and recovery behavior.

Do not turn docstrings into full implementation walkthroughs.

---

## Section Dividers

Use section divider comments for top-level organization in medium and large Python modules.

Prefer the following canonical divider forms:

```python
# ────────────────────────────────── H1 ───────────────────────────────── #
# ────────────────────────── H2 ────────────────────────── #
# ~~~~~~~~~~~~~~~~~~~~~~~~~ H3 ~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
# ~~~~~~~~~~~~~~~~~ H4 ~~~~~~~~~~~~~~~~~ #
```

### Divider Hierarchy

- H1: Module-level sections.
- H2: Major functional blocks.
- H3: Related sub-groups.
- H4: Rare minor groupings.

Use only the levels needed by the module.

Rules:

- Do not add dividers to very small modules.
- Keep section names short and descriptive.
- Use the canonical divider structure consistently.
- Do not hand-type malformed or arbitrarily styled divider lines.
- Do not create unnecessary nesting of section levels.
- Group related functions under meaningful responsibilities.

Common section names include:

- `Handlers`
- `Commands`
- `Retrieval`
- `Mutations`
- `Role CRUD`
- `Role Resolution`
- `Collection Helpers`
- `Utilities`

Section dividers provide navigation, not an excuse to create artificial sections for every function.

---

## Inline Comments and Constants

- Keep comments short and close to the code they explain.
- Explain why, not what an obvious assignment does.
- Use natural, direct sentences.
- Prefer a well-named helper over a long inline explanation.
- Update or remove comments when code changes.
- Add a `# *` comment above a non-obvious module-level constant when its purpose or constraint is not clear from its name.
- Do not comment obvious constants.
- Use handler labels only when they improve readability.
- Do not retain commented-out implementations, obsolete alternatives, or historical code fragments.
- Keep comments focused on the smallest relevant code scope.

A comment must remain accurate and useful independently of temporary implementation details.

---

## Comments on Localized Code

Localization-related comments should explain decisions that are not obvious from the send path.

When the locale or rendering mode is unclear, explain:

- Who reads the message.
- Why the message uses the selected locale or rendering mode.
- Why the selected behavior matters.

Example:

```python
# * Plain alert: Telegram never parses it, so an escaped template would show raw backslashes.
```

Rules:

- Translator guidance belongs in TOML header comments next to the relevant translation keys, not in Python comments.
- Document placeholders, send paths, and intended audiences where translators can find them.
- Do not explain the internationalization engine in code comments.
- Refer to [`i18n/README.md`](../../i18n/README.md) for translation contracts and to [`code-style.md`](code-style.md) for implementation rules.
- Keep translation guidance synchronized with actual message behavior.

---

## Em Dashes

The em dash character (U+2014) is forbidden in every tracked project file.

This restriction applies to:

- Python source code.
- Inline comments and docstrings.
- String literals, including bot replies, audit logs, and error messages.
- Markdown documentation.
- YAML and INI files.
- Agent instructions and skill documentation.
- Other tracked text-based project files.

Use a standard hyphen (`-`), comma, colon, period, or restructure the sentence instead.

The canonical section dividers in this file use the box-drawing character U+2500 (`─`), which is a different character and remains allowed.

Scan before committing. The result must be empty:

```bash
rg -n $'\u2014' .
```

Do not interpret a code fence, example, string literal, or generated text as an exemption from this rule.

---

## Markdown Documentation

These conventions apply to project-maintained Markdown documentation, especially files under `.agents/` and `docs/`.

### Language and Writing

- Write documentation in English only.
- Use clear, professional, natural, and concise language.
- Prefer descriptive headings, short paragraphs, and focused bullet lists.
- Avoid unnecessary repetition, generic filler, and overly verbose explanations.
- Keep terminology consistent across related documents.
- Describe current behavior accurately.
- Clearly distinguish implemented behavior from planned or aspirational behavior.
- Keep documentation synchronized with actual project structure and behavior.

Specialized documentation follows its owning style guide:

- Changelog and release notes follow [`changelog-style.md`](changelog-style.md).
- Code and architecture guidance follows [`code-style.md`](code-style.md).
- General Markdown presentation and comment conventions follow this file.

### Formatting

- Use meaningful heading hierarchy.
- Use fenced code blocks with appropriate language identifiers when helpful.
- Use inline code for paths, identifiers, commands, configuration keys, and literal values.
- Prefer project-relative paths for internal references.
- Validate relative Markdown links whenever linked files or directories change.
- Use tables only when they make structured comparisons or reference information easier to understand.
- Avoid excessive nested lists and deeply nested heading structures.
- Keep examples accurate and consistent with current project conventions.

### Documentation Boundaries

- Keep public documentation separate from agent-only rules.
- Do not place private operational instructions in public-facing documentation.
- Do not include real credentials, private chat IDs, or production-only links.
- Do not expose secrets or sensitive deployment configuration in examples.
- Use clearly identifiable placeholders for values that must be supplied by the environment.
- Update related documentation when paths, behavior, interfaces, or repository structure changes.
- Remove obsolete instructions when their underlying behavior or requirement no longer exists.

### Prohibited Documentation Practices

Do not:

- Comment out dead code.
- Add vague TODOs such as `# TODO: fix later`.
- Use Sphinx-style docstring tags.
- Explain obvious code.
- Restate a helper's documented contract at its call sites.
- Hand-type malformed section dividers.
- Add comments that contradict established code or architecture rules.
- Duplicate specialized documentation rules in unrelated style guides.
- Present planned functionality as implemented functionality.
- Leave broken relative links or outdated examples.

---

## Final Review

Before considering comments or documentation complete, ensure that:

- Every comment communicates information that is not already obvious.
- Comments explain intent, constraints, risks, or non-obvious behavior.
- Security, ordering, failure, race, and migration contracts remain documented.
- Docstrings accurately describe their associated modules, classes, and functions.
- Module docstrings follow the one-line requirement.
- Section dividers follow the canonical hierarchy.
- Better Comments prefixes are used only for their intended purposes.
- Localized-code comments remain relevant to the actual send path.
- Markdown headings, code fences, links, and examples are consistent.
- Public documentation and agent-only instructions remain separated.
- No real credentials or sensitive operational identifiers appear.
- No em dash characters appear anywhere in tracked files.

Use `git diff --check` to identify whitespace issues and review changed comments in their actual code context.

If a comment only repeats what the code already says, remove it.

If a comment carries a necessary contract, preserve it in the appropriate authoritative location.

The final result must make the code easier to understand without making the codebase dependent on redundant explanations.
