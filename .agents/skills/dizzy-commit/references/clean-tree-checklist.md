# Working Tree Review Before Finishing

Before declaring any task complete or ending a session, inspect the working tree:

```bash
git status --short
```

If the output is not empty:

1. Distinguish changes made during this task from pre-existing user work.
2. Report the remaining files and their ownership.
3. Commit only after explicit user approval, or leave the changes in place when the user
   intentionally wants them uncommitted.
4. Never use `git checkout -- <file>` or `git clean -fd` to force a clean tree. Destructive
   cleanup requires explicit, file-specific confirmation.

## Checklist before done

- [ ] `git status --short` was inspected
- [ ] `git diff --stat` was inspected when changes exist
- [ ] `git diff --cached --stat` was inspected when staged changes exist
- [ ] Remaining changes were reported or explicitly approved for commit
- [ ] Any remaining dirty files are pre-existing user work or were explicitly kept
