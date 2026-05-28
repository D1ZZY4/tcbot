---
name: create-hooks
description: >-
  Create agent hooks for persistent AI behavior. Use when you want to create a
  hook, write hooks.json, add hook scripts, or automate behavior around agent events.
disable-model-invocation: true
---

# Creating Agent Hooks

Create hooks when you want AI to run custom logic before or after agent events. Hooks are scripts or prompt-based checks that exchange JSON over stdin/stdout.

## Gather Requirements

Before you write anything, determine:

1. **Scope**: Should this be a project hook or a user hook?
2. **Trigger**: Which event should run the hook?
3. **Behavior**: Should it audit, deny/allow, rewrite input, inject context, or continue a workflow?
4. **Implementation**: Should it be a command hook (script) or a prompt hook?
5. **Filtering**: Does it need a matcher so it only runs for certain tools, commands, or subagent types?
6. **Safety**: Should failures fail open or fail closed?

Infer these from the conversation when possible. Only ask for the missing pieces.

## Choose the Right Location

For IDE-neutral use, create hook files in these locations:

- **Project hooks**: `.agents/hooks.json` and `.agents/hooks/*`
- **User hooks**: `~/.agents/hooks.json` and `~/.agents/hooks/*`

Path behavior matters:
- **Project hooks** run from the project root, so use paths like `.agents/hooks/my-hook.sh`
- **User hooks** run from `~/.agents/`, so use paths like `./hooks/my-hook.sh` or `hooks/my-hook.sh`

Prefer **project hooks** when the behavior should be shared with the repository and checked into version control.

## Choose the Hook Event

Use the narrowest event that matches the user's goal.

### Common Agent events

- `sessionStart`, `sessionEnd`: set up or audit a session
- `preToolUse`, `postToolUse`, `postToolUseFailure`: work across all tools
- `subagentStart`, `subagentStop`: control or continue Task/subagent workflows
- `beforeShellExecution`, `afterShellExecution`: gate or audit terminal commands
- `beforeMCPExecution`, `afterMCPExecution`: gate or audit MCP tool calls
- `beforeReadFile`, `afterFileEdit`: control file reads or post-process edits
- `beforeSubmitPrompt`: validate prompts before they are sent
- `preCompact`: observe context compaction
- `stop`: handle agent completion
- `afterAgentResponse`, `afterAgentThought`: track agent output or reasoning

### Quick event chooser

- **Block or approve shell commands** -> `beforeShellExecution`
- **Audit shell output** -> `afterShellExecution`
- **Format files after edits** -> `afterFileEdit`
- **Block or rewrite a specific tool call** -> `preToolUse`
- **Add follow-up context after a tool succeeds** -> `postToolUse`
- **Control whether subagents can run** -> `subagentStart`
- **Chain subagent loops** -> `subagentStop`
- **Check prompts for secrets or policy violations** -> `beforeSubmitPrompt`
- **Protect MCP calls** -> `beforeMCPExecution`

## Hooks File Format

Create a `hooks.json` file with schema version 1:

```json
{
  "version": 1,
  "hooks": {
    "afterFileEdit": [
      {
        "command": ".agents/hooks/format.sh"
      }
    ]
  }
}
```

Each hook definition can include:

- `command`: shell command or script path
- `type`: `"command"` or `"prompt"` (defaults to `"command"`)
- `timeout`: timeout in seconds
- `matcher`: filter for when the hook runs
- `failClosed`: block the action when the hook crashes, times out, or returns invalid JSON
- `loop_limit`: mainly for `stop` and `subagentStop` follow-up loops

## Matchers

Use matchers to avoid running the hook on every event.

- `preToolUse` / `postToolUse` / `postToolUseFailure`: match on tool type such as `Shell`, `Read`, `Write`, `Task`, or MCP tools in `MCP: ...` form
- `subagentStart` / `subagentStop`: match on subagent type such as `generalPurpose`, `explore`, or `shell`
- `beforeShellExecution` / `afterShellExecution`: match on the full shell command string
- `beforeReadFile`: match on tool type such as `Read` or `TabRead`
- `afterFileEdit`: match on tool type such as `Write` or `TabWrite`
- `beforeSubmitPrompt`: matches the value `UserPromptSubmit`

Important matcher warning:

- Matchers use JavaScript-style regular expressions, not POSIX/grep syntax
- Do not use POSIX classes like `[[:space:]]`; use JavaScript equivalents like `\s`
- If the matcher is at all tricky, start by getting the hook working without one or with a very simple matcher, then tighten it afterward

## Command Hooks

Command hooks are the default. They receive JSON on stdin and can return JSON on stdout.

Before using a command hook, verify that every executable it depends on will actually run in the hook environment:
- the script itself has a valid shebang and is executable
- any helper binary it calls is already installed and on `$PATH`
- if the script depends on tools like `jq`, `python3`, `node`, or repo-local CLIs, verify that explicitly before finishing

## Minimal Example

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      {
        "command": ".agents/hooks/approve-network.sh",
        "matcher": "curl|wget|nc ",
        "failClosed": true
      }
    ]
  }
}
```

```bash
#!/bin/bash
input=$(cat)
command=$(echo "$input" | jq -r '.command // empty')

if [[ "$command" =~ curl|wget|nc ]]; then
  echo '{
    "permission": "ask",
    "user_message": "This command may make a network request. Please review it before continuing.",
    "agent_message": "A hook flagged this shell command as a possible network call."
  }'
  exit 0
fi

echo '{ "permission": "allow" }'
exit 0
```

Important behavior:
- Exit code `0`: success
- Exit code `2`: block the action, same as returning deny
- Other non-zero exit codes: fail open by default unless `failClosed: true`

Always make hook scripts executable after creating them.

## Prompt Hooks

Prompt hooks are useful when the policy is easier to describe than to script.

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      {
        "type": "prompt",
        "prompt": "Does this command look safe to execute? Only allow read-only operations. Here is the hook input: $ARGUMENTS",
        "timeout": 10
      }
    ]
  }
}
```

Use prompt hooks for lightweight policy decisions. Prefer command hooks when the logic must be deterministic or when the user needs exact, auditable behavior.

## Validation and Troubleshooting

- Agent watches `hooks.json` and reloads on save
- If hooks still do not load, restart Agent
- Double-check relative paths
- If the hook does not appear to load at all, suspect matcher/config parsing first
- If the script runs external commands, verify each one is installed and reachable from the hook process
