# Changelog Style Rules

This file defines how project changelogs and release notes are structured, written, and maintained.

The goal is to produce professional, human-readable release documentation that explains what changed, why it matters, and what users or contributors need to know.

Changelogs document meaningful project changes, not development activity, implementation history, or automated progress reports.

Code conventions live in [`code-style.md`](code-style.md), comment and general Markdown conventions live in [`comment-style.md`](comment-style.md), and validation requirements live in [`tooling-skills-use.md`](tooling-skills-use.md).

---

## Documentation Structure

Use a central changelog with individual documents for published releases.

```text
project/
├── CHANGELOG.md
└── docs/
    └── releases/
        ├── v2.1.0.md
        ├── v2.0.0.md
        └── v1.0.0.md
```

### Root `CHANGELOG.md`

The root changelog is the central entry point for project history.

It contains:

- An `Unreleased` section for meaningful changes not yet included in a published release.
- An index of published releases linking to their individual release notes.
- Release groups organized by major version when the history becomes sufficiently large.

The root changelog must not duplicate complete release descriptions.

### Individual Release Notes

Each published version has its own document under `docs/releases/`.

Use the exact version number as the filename:

- `v1.0.0.md`
- `v1.2.0.md`
- `v2.0.0.md`

Each document describes exactly one published release.

Do not create individual release files for unpublished versions or individual patch releases unless the project genuinely needs separate release documentation for them.

---

## Voice and Tone

Write like a professional software project maintaining public release documentation, never like an automated development report.

- Use professional, natural, precise, and concise English.
- Prefer reader-focused explanations over implementation descriptions.
- State what changed and why it matters.
- Keep each bullet focused on one independent change.
- Explain observable outcomes and practical consequences.
- Avoid marketing language, exaggerated claims, generic praise, and generated filler.
- Maintain consistent terminology across all release documents.
- Prefer short sentences without removing important context.
- Never describe how development work was performed.

Write for the relevant audience:

- Operators and administrators.
- End users.
- Developers and integrators.
- Translators and documentation contributors.

A reader should understand the practical significance of a change without needing to inspect the implementation.

## Entry Writing Rules

### Standard Entry Shape

Use a descriptive bold lead followed by relevant context.

```markdown
- **What changed, plainly** (`relevant/path.py`): One or two short sentences explaining the observable outcome and why it matters.
```

Rules:

- Start with a specific, descriptive, action-oriented bold lead.
- Include relevant file paths in parentheses immediately after the bold lead when they provide useful traceability.
- Follow the lead with one or two short explanatory sentences.
- Describe the resulting behavior, not the development process.
- Use one bullet per independent change.
- Avoid combining unrelated changes into one entry.
- Avoid repeating information already documented elsewhere.
- Include additional context only when it helps readers understand functionality, compatibility, or upgrade requirements.

### Reader Perspective

Prefer:

```markdown
- **Improve configuration error reporting** (`config.py`): Invalid settings now identify the affected configuration key, making troubleshooting more straightforward.
```

Avoid:

```markdown
- **Refactor configuration handling** (`config.py`): Reorganized several internal classes and helpers.
```

The first describes a meaningful outcome. The second only describes implementation activity.

Internal refactoring, code cleanup, dependency updates, and architectural changes belong in the changelog only when they produce a meaningful documented outcome for users or contributors.

### One Idea Per Bullet

Each bullet must describe one coherent change.

When multiple independent changes exist, write separate entries.

Do not combine unrelated features, bug fixes, configuration changes, and documentation updates into a single entry.

### Behavior Changes

Explicitly identify observable behavior changes when existing functionality behaves differently.

Use this format:

```markdown
- **Describe the behavior change** (`relevant/path.py`): Invalid values now produce an explicit error instead of being silently ignored. Behavior changes: invalid configuration values are rejected.
```

Rules:

- Include `Behavior changes:` only when observable behavior actually changes.
- Explain the previous and new behavior when that distinction matters.
- Identify relevant consequences for operators, users, and integrations.
- Do not add behavior callouts for internal refactoring or implementation-only changes.
- The absence of a behavior callout means no existing user-visible behavior has intentionally changed.

### Compatibility and Impact Notes

Preserve specific details that help readers understand compatibility and upgrade implications.

Examples:

- Existing labels and callback signatures remain unchanged.
- Previously supported callbacks continue to work.
- Existing configurations remain compatible.
- In-flight operations continue using their original configuration.
- Keyboard layouts and interaction patterns remain unchanged.
- Existing ranking and ordering guarantees are preserved.

Never claim compatibility without evidence.

Include exact numbers when they describe meaningful observable behavior, including:

- Limits and thresholds.
- Timeouts and expiration periods.
- Supported counts and capacity.
- Retry behavior.
- Concurrency limits.
- Version and runtime requirements.

Numbers must describe actual application behavior, not development or validation results.

### File Path References

File paths provide traceability without turning changelog entries into implementation reports.

- Include relevant paths immediately after the bold lead.
- Prefer project-relative paths.
- Include only paths that help identify the affected area.
- Do not list every modified file.
- Do not expose unnecessary internal identifiers.
- Omit paths that provide no meaningful context.

---

## Banned Language

Never include development-process information or unnecessary implementation terminology in user-facing changelog entries.

### Tool Names and Validation Results

Do not mention development tools, validation tools, or their execution results.

Examples:

- `ruff`, `pyright`, `pytest`.
- `test suite`, `full suite`.
- Test counts such as `37 new tests` or `92 passed`.
- Coverage percentages.
- Formatter, linter, type-checker, and validation summaries.

### Process Narration

Do not describe development, auditing, implementation, or verification activity.

Avoid terms and expressions such as:

- `Verified`.
- `Verified against`.
- `Audit`.
- `Zero findings`.
- `Golden`.
- `Harness`.
- `Stub`.
- `Fake`.
- `Compileall`.
- `All checks passed`.
- `Successfully tested`.
- `Validation completed`.

### Implementation Jargon

Avoid unnecessary internal terminology and code-specific expressions.

Examples:

- Internal function, class, and variable names.
- Placeholder names such as `{window}` and `{limit}`.
- Expressions such as `Safe`, `plain=True`, and `pre()`.
- Internal flags and temporary identifiers.
- Implementation-specific expressions that do not help readers understand the result.

Describe the resulting functionality or observable behavior instead.

### Generic Filler

Avoid statements that communicate no specific information.

Examples:

- "Various improvements."
- "Minor fixes and enhancements."
- "General cleanup."
- "Improved overall quality."
- "Several internal changes."
- "Better performance and stability."

Such statements are acceptable only when accompanied by specific, meaningful details explaining what actually improved.

---

## Categories

Use consistent category names across the root changelog and individual release documents.

### Standard Categories

| Category | Purpose |
|---|---|
| `Added` | Newly introduced features, capabilities, and functionality. |
| `Changed` | Changes to existing functionality or observable behavior. |
| `Fixed` | Resolved bugs, defects, and incorrect behavior. |
| `Removed` | Functionality, compatibility, or components that are no longer available. |
| `Documentation` | Meaningful changes to user-facing and contributor documentation. |

### Additional Categories

Use these categories when the changes justify them.

| Category | Purpose |
|---|---|
| `Improved` | Meaningful improvements to usability, performance, reliability, or other observable qualities. |
| `Deprecated` | Functionality that remains available but is scheduled for future removal. |
| `Security` | Security-related fixes and improvements. |
| `Breaking Changes` | Incompatible changes that require user or integration adjustments. |

### Category Rules

- Do not create empty headings.
- Do not force changes into unrelated categories.
- Do not document the same change under multiple categories.
- Prefer `Changed` for modifications to existing functionality.
- Use `Improved` when a meaningful improvement deserves separate visibility.
- Use `Fixed` for resolved defects and incorrect behavior.
- Use `Breaking Changes` when compatibility is intentionally broken.
- Use `Security` for changes with a genuine security impact.
- Use `Deprecated` when functionality remains available but has an announced removal path.
- Use `Removed` when functionality is no longer available.
- Use `Documentation` for meaningful documentation changes.
- Document migration requirements alongside the corresponding breaking changes.

Do not introduce new categories without a clear documentation need.

---

## Root Changelog Format

The root `CHANGELOG.md` follows this general structure:

```markdown
# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

### Changed

### Fixed

## Releases

### v2.x

- [2.1.0](docs/releases/v2.1.0.md)
- [2.0.0](docs/releases/v2.0.0.md)

### v1.x

- [1.5.0](docs/releases/v1.5.0.md)
- [1.0.0](docs/releases/v1.0.0.md)
```

The example categories are illustrative. Include only categories containing actual entries.

Rules:

- Keep `Unreleased` at the top.
- Keep the release index below `Unreleased`.
- List published versions in descending version order.
- Group releases by major version when useful.
- A flat release list is acceptable when the release history is still small.
- Link every published version to its corresponding release document.
- Do not duplicate complete release notes in the root changelog.
- Do not create unnecessary index categories.
- Keep relative links accurate and project-relative.

### Unreleased

`Unreleased` contains meaningful changes that have not yet been included in a published release.

- Add entries as changes become ready to document.
- Use the same writing and category rules as published release notes.
- Keep entries focused on actual behavior and practical outcomes.
- Remove duplicate, obsolete, and irrelevant entries.
- Do not include speculative features or unconfirmed behavior.
- Do not create a separate `Unreleased` file.

The `Unreleased` section remains available after every published release.

---

## Individual Release Notes Format

Every published release receives its own document.

Use this structure as the reference:

```markdown
# vX.Y.Z

> Release date: YYYY-MM-DD

Briefly describe the purpose and most significant outcomes of this release.

## Added

- Describe newly introduced functionality.

## Changed

- Describe changes to existing functionality.

## Improved

- Describe meaningful improvements.

## Fixed

- Describe resolved issues.

## Breaking Changes

- **[BREAKING]** Explain the incompatible change and its impact.

### Migration

1. Describe the required migration step.
2. Explain configuration or integration changes.
3. Explain any necessary upgrade action.

## Deprecated

- Describe functionality scheduled for removal.

## Removed

- Describe functionality removed in this release.

## Security

- Describe relevant security changes.

## Documentation

- Describe meaningful documentation changes.

## Compatibility

- Describe relevant runtime, platform, configuration, or integration compatibility.

---

**Previous release:** [vX.Y.Z](vX.Y.Z.md)

**Full changes:** [Compare previous...current](https://github.com/OWNER/REPOSITORY/compare/PREVIOUS...CURRENT)
```

### Release Notes Rules

- Use the exact published version number.
- Use the actual release date in `YYYY-MM-DD` format.
- Keep the opening description concise and specific.
- Include only categories containing meaningful entries.
- Add migration instructions whenever users must take action.
- Include compatibility information only when relevant.
- Add a previous release link when one exists.
- Add comparison links only when reliable repository references are available.
- Never invent release metadata, dates, compatibility claims, migration requirements, or URLs.
- Keep category names and ordering consistent across releases.
- Avoid repeating the same change in multiple sections.

The opening description should summarize the release rather than repeat every category entry.

---

## Breaking Changes and Migration

Breaking changes directly affect upgrade decisions and must be documented clearly.

Rules:

- Mark incompatible changes using `[BREAKING]`.
- Explain what stopped working or what now behaves differently.
- Identify affected users, configurations, interfaces, and integrations.
- Provide migration instructions when an upgrade requires manual changes.
- Explain whether the change is mandatory or whether a compatible alternative exists.
- Identify relevant version compatibility implications.
- Never classify internal refactoring or ordinary improvements as breaking changes.
- Never bury breaking changes inside unrelated entries.

Migration instructions must be actionable and specific.

Do not provide migration steps that have not been established by the actual implementation.

---

## Versioning and Release History

Follow Semantic Versioning (`MAJOR.MINOR.PATCH`) when applicable.

- `MAJOR`: Incompatible changes.
- `MINOR`: Backward-compatible functionality additions.
- `PATCH`: Backward-compatible fixes.

Release documentation rules:

- Use `vX.Y.Z.md` filenames.
- Keep the newest release first in the index.
- Create individual release documents only for published versions.
- Keep each release document focused on exactly one version.
- Keep historical release information accurate.
- Never silently rewrite published release descriptions.
- Correct factual documentation mistakes only when necessary, without changing the historical meaning of the release.

Use `YYYY-MM-DD` for release dates.

---

## Workflow

### 1. Development

- Record meaningful changes under `Unreleased` in the root `CHANGELOG.md`.
- Place each entry under the appropriate category.
- Write entries while the change context is available.
- Describe actual functionality and observable outcomes.
- Avoid development-only details and implementation noise.
- Do not create individual release files for unpublished changes.

### 2. Release Preparation

- Review all accumulated `Unreleased` entries.
- Remove duplicates, obsolete entries, and irrelevant internal changes.
- Ensure every entry describes a real and meaningful change.
- Organize changes using the standard categories.
- Identify breaking changes and migration requirements.
- Confirm version numbers, compatibility information, and release metadata against the actual project state.

### 3. Publishing a Release

Only when a release is actually published:

1. Create `docs/releases/vX.Y.Z.md`.
2. Move the relevant `Unreleased` entries into the release document.
3. Organize and refine the entries using the release notes structure.
4. Add the actual release date and relevant release metadata.
5. Add the published version to the root `CHANGELOG.md` index.
6. Clear the published entries from `Unreleased`.
7. Keep `Unreleased` available for subsequent development.

Do not treat a local version update, development milestone, or unfinished implementation as a published release.

### 4. Historical Integrity

- Never mix unpublished changes with published release notes.
- Never move entries into a release document before the corresponding release is published.
- Never rewrite released history to make changes appear different.
- Never silently remove important historical information.
- Keep release links and version references accurate.
- Preserve the distinction between what was implemented, what was released, and what remains planned.

---

## Final Review

Before considering changelog documentation complete, ensure that:

- Every entry describes an actual, meaningful project change.
- Wording is professional, natural, concise, and human-readable.
- Each bullet communicates one independent change.
- Reader-visible outcomes and practical impacts are clear.
- Relevant behavior changes and compatibility information are preserved.
- Breaking changes include actionable migration guidance.
- No development process narration or tool output is included.
- No generic filler or duplicate entries remain.
- File paths provide useful traceability without unnecessary noise.
- Categories are relevant and contain meaningful entries.
- Version numbers, release dates, and links are accurate.
- The root changelog and individual release documents remain consistent.
- Published release history remains accurate.
- Relative Markdown links are valid.
- Character restrictions follow [`comment-style.md`](comment-style.md).

Use `git diff --check` to check whitespace problems, then review each entry from the reader's perspective.

If a sentence only proves that development work happened instead of informing the reader, remove it.

The final result must read like professional software release documentation, not an engineering activity log.
