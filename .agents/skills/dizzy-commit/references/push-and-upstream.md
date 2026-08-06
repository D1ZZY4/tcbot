# Push and Upstream Safety

Pushing changes is a separate mutation from creating a commit. Treat it as an explicit,
repository-aware operation, even when the user asked to commit and push in the same sentence.

## Inspect before pushing

```bash
git remote -v
git branch --show-current
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
git status --short
```

- Use the configured remote and upstream. Never assume the remote is named `origin` or that the
  branch is `main`.
- Confirm the current branch and destination before pushing.
- Check repository contribution or hosting guidance for protected branches, review requirements,
  and required checks.
- Do not push ignored files, uncommitted changes, or an unintended branch.

## Safety boundaries

- Push only after explicit user approval.
- Never force-push, delete a remote branch, rewrite public history, or change remotes without
  explicit, operation-specific instruction.
- Do not change Git identity, signing, credentials, or upstream configuration as part of a normal
  push.
- If no upstream is configured, explain the destination that would be needed and ask before
  creating or changing tracking configuration.

## Verify after pushing

After a successful push, confirm the local status and upstream:

```bash
git status --short
git branch -vv
```

Report the branch and remote that were updated. If the push fails, preserve the local commits and
report the provider's error instead of retrying with a destructive or force option.