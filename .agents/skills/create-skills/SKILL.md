---
name: create-skills
description: >-
  Create agent skills for persistent AI guidance. Use when you want to create a
  skill, add coding standards, set up project conventions, configure
  file-specific patterns, create SKILL.md files, or asks about agent skills.
disable-model-invocation: true
---

# Creating Agent Skills

Create project skills in `.agents/skills/` to provide persistent guidance for the AI agent.

## Gather Requirements

Before creating a skill, determine:

1. **Purpose**: What should this skill help with?
2. **Scope**: Should it be project-local or global?
3. **File patterns**: If file-specific, which glob patterns?

### Inferring from Context

If you have previous conversation context, infer a skill from what was discussed. You can create multiple skills if the conversation covers distinct topics or patterns.

### Required Questions

If the user hasn't specified scope, ask:
- "Should this skill be project-local or global?"

If they mentioned specific files and haven't provided concrete patterns, ask:
- "Which file patterns should this skill apply to?" (e.g., `**/*.ts`, `backend/**/*.py`)

## Skill File Format

Skills are directories in `.agents/skills/` with a `SKILL.md` file:

```
.agents/skills/
  your-skill-name/
    └── SKILL.md
```

### File Structure

```markdown
---
name: your-skill-name
description: Brief description of what this skill does and when to use it
disable-model-invocation: true
---

# Your Skill Name

## Instructions
Clear, step-by-step guidance for the agent.

## Examples
Concrete examples of using this skill.
```

### Required Fields

| Field | Description |
|-------|-------------|
| `name` | Unique identifier (lowercase letters and hyphens only) |
| `description` | When to delegate to this skill (be specific!) |

### Optional Fields

| Field | Description |
|-------|-------------|
| `disable-model-invocation` | Set to `true` so the skill only loads when named explicitly |

## Writing Effective Descriptions

The description is **critical** — the agent uses it to decide when to apply the skill.

### Description Best Practices

1. **Write in third person** (the description is injected into the system prompt):
   - ✅ Good: "Processes Excel files and generates reports"
   - ❌ Avoid: "I can help you process Excel files"
   - ❌ Avoid: "You can use this to process Excel files"

2. **Be specific and include trigger terms**:
   - ✅ Good: "Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction."
   - ❌ Vague: "Helps with documents"

3. **Include both WHAT and WHEN**:
   - WHAT: What the skill does (specific capabilities)
   - WHEN: When the agent should use it (trigger scenarios)

## Skill Creation Workflow

### Step 1: Decide the Scope

- **Project-local** (`.agents/skills/`): For codebase-specific skills shared with team
- **Global** (`~/.agents/skills/`): For personal skills across all projects

### Step 2: Create the Directory Structure

```bash
# For project-local
mkdir -p .agents/skills/your-skill-name

# For global (on systems that support it)
mkdir -p ~/.agents/skills/your-skill-name
```

### Step 3: Define Configuration

Write the `SKILL.md` with the required frontmatter fields (`name` and `description`).

### Step 4: Write the System Prompt

The body becomes the system prompt. Be specific about:
- What the skill should do when invoked
- The workflow or process to follow
- Output format and structure
- Any constraints or guidelines

### Step 5: Test the Skill

Ask the agent to use your new skill:

```
Use the my-skill skill to [task description]
```

## Best Practices

1. **Design focused skills**: Each should excel at one specific task
2. **Write detailed descriptions**: Include trigger terms so the agent knows when to delegate
3. **Check into version control**: Share project skills with your team

## Troubleshooting

### Skill Not Found
- Ensure directory is in `.agents/skills/` or `~/.agents/skills/`
- Check `SKILL.md` has `.md` extension
- Verify YAML frontmatter syntax is valid
