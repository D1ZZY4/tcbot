---
name: create-subagents
description: >-
  Create custom subagents for specialized AI tasks. Use when you want to create
  a new type of subagent, set up task-specific agents, configure code reviewers,
  debuggers, or domain-specific assistants with custom prompts.
disable-model-invocation: true
---

# Creating Custom Subagents

This skill guides you through creating custom subagents for project-local use. Subagents are specialized AI assistants that run in isolated contexts with custom prompts.

## Before You Begin: Understand the Concept

Subagents help you:
- **Preserve context** by isolating exploration from your main conversation
- **Specialize behavior** with focused system prompts for specific domains
- **Reuse configurations** across projects

## Subagent Locations

For IDE-neutral use, create subagent files in these locations:

| Location | Scope | Priority |
|----------|-------|----------|
| `.agents/agents/` | Current project | Higher |
| `~/.agents/agents/` | All your projects | Lower |

## Subagent File Format

Create a `.md` file with YAML frontmatter and a markdown body (the system prompt):

```markdown
---
name: your-subagent-name
description: Brief description of what this subagent does and when to use it
---

# Your Subagent Name

## Instructions
Clear, step-by-step guidance for the AI.

## Examples
Concrete examples of using this subagent.
```

### Required Fields

| Field | Description |
|-------|-------------|
| `name` | Unique identifier (lowercase letters and hyphens only) |
| `description` | When to delegate to this subagent (be specific!) |

## Writing Effective Descriptions

The description is **critical** — the AI uses it to decide when to delegate.

### Description Best Practices

1. **Write in third person** (the description is injected into the system prompt):
   - ✅ Good: "Processes Excel files and generates reports"
   - ❌ Avoid: "I can help you process Excel files"
   - ❌ Avoid: "You can use this to process Excel files"

2. **Be specific and include trigger terms**:
   - ✅ Good: "Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction."
   - ❌ Vague: "Helps with documents"

3. **Include both WHAT and WHEN**:
   - WHAT: What the subagent does (specific capabilities)
   - WHEN: When the AI should use it (trigger scenarios)

## Subagent Creation Workflow

### Step 1: Decide the Scope

- **Project-level** (`.agents/agents/`): For codebase-specific agents shared with team
- **User-level** (`~/.agents/agents/`): For personal agents across all projects

### Step 2: Create the File

```bash
# For project-level
mkdir -p .agents/agents
touch .agents/agents/my-agent.md

# For user-level
mkdir -p ~/.agents/agents
touch ~/.agents/agents/my-agent.md
```

### Step 3: Define Configuration

Write the frontmatter with the required fields (`name` and `description`).

### Step 4: Write the System Prompt

The body becomes the system prompt. Be specific about:
- What the subagent should do when invoked
- The workflow or process to follow
- Output format and structure
- Any constraints or guidelines

### Step 5: Test the Subagent

Ask the AI to use your new subagent:

```
Use the my-subagent subagent to [task description]
```

## Best Practices

1. **Design focused subagents**: Each should excel at one specific task
2. **Write detailed descriptions**: Include trigger terms so the AI knows when to delegate
3. **Check into version control**: Share project subagents with your team

## Troubleshooting

### Subagent Not Found
- Ensure file is in `.agents/agents/` or `~/.agents/agents/`
- Check file has `.md` extension
- Verify YAML frontmatter syntax is valid
