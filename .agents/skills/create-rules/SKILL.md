---
name: create-rules
description: >-
  Create project rules for persistent AI guidance. Use when you want to create a
  rule, add coding standards, set up project conventions, configure
  file-specific patterns, create rule files, or asks about agent rules.
disable-model-invocation: true
---

# Creating Project Rules

Create project rules in `.agents/rules/` to provide persistent context for the AI agent.

## Gather Requirements

Before creating a rule, determine:

1. **Purpose**: What should this rule enforce or teach?
2. **Scope**: Should it always apply, or only for specific files?
3. **File patterns**: If file-specific, which glob patterns?

### Inferring from Context

If you have previous conversation context, infer rules from what was discussed. You can create multiple rules if the conversation covers distinct topics or patterns. Don't ask redundant questions if the context already provides the answers.

### Required Questions

If the user hasn't specified scope, ask:
- "Should this rule always apply, or only when working with specific files?"

If they mentioned specific files and haven't provided concrete patterns, ask:
- "Which file patterns should this rule apply to?" (e.g., `**/*.ts`, `backend/**/*.py`)

## Rule File Format

Rules are `.md` files in `.agents/rules/` with YAML frontmatter:

```
.agents/rules/
  coding-standards.md
  api-conventions.md
  code-style.md
```

### File Structure

```markdown
---
description: Brief description of what this rule does
globs: **/*.ts  # File pattern for file-specific rules
alwaysApply: false  # Set to true if rule should always apply
---

# Rule Title

Your rule content here...
```

### Frontmatter Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | What the rule does (shown in agent picker) |
| `globs` | string | File pattern - rule applies when matching files are open |
| `alwaysApply` | boolean | If true, applies to every session |

### Rule Configurations

#### Always Apply

For universal standards that should apply to every conversation:

```yaml
---
description: Core coding standards for the project
alwaysApply: true
---
```

#### Apply to Specific Files

For rules that apply when working with certain file types:

```yaml
---
description: TypeScript conventions for this project
globs: **/*.ts
alwaysApply: false
---
```

### Best Practices

#### Keep Rules Concise

- **Under 50 lines**: Rules should be concise and to the point
- **One concern per rule**: Split large rules into focused pieces
- **Actionable**: Write like clear internal docs
- **Concrete examples**: Ideally provide concrete examples of how to fix issues

### Example Rules

#### Error Handling

```markdown
---
description: Error handling conventions
globs: **/*.py
alwaysApply: false
---

# Error Handling

\`\`\`python
# ❌ BAD
try:
  await fetchData()
except:
  pass

# ✅ GOOD
try:
  await fetchData()
except Exception as e:
  logger.error('Failed to fetch', { error: e })
  raise FetchError('Unable to retrieve data', { cause: e })
\`\`\`
```

#### Type Hints

```markdown
---
description: Type hinting conventions
globs: **/*.py
alwaysApply: true
---

# Type Hints

- Use built-in generics: `list[str]`, `dict[str, int]`
- Never use `List`, `Dict`, `Optional`, `Union`
- Import from `__future__`: `from __future__ import annotations`

Example:
\`\`\`python
from __future__ import annotations
from typing import TypeAlias

UserId: TypeAlias = int
UserDict: TypeAlias = dict[str, str | int]

def get_user(user_id: UserId) -> UserDict:
    return {"id": user_id, "name": "Alice"}
\`\`\`
```

### Checklist

- [ ] File is `.md` format in `.agents/rules/`
- [ ] Frontmatter configured correctly
- [ ] Content under 500 lines
- [ ] Includes concrete examples
