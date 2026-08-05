# Clean Working Tree Before Finishing

Before declaring any task complete or ending a session, always verify the working tree is
fully clean:

```bash
git status --short
```

The output must be completely empty. If it is not:

1. Every modified or new file must either be committed (with a proper Conventional Commit,
   scope and body both required) or intentionally discarded with `git checkout -- <file>` /
   `git clean -fd`.
2. Never leave staged or unstaged changes sitting in the working tree. Some platforms
   (Replit, CI runners) will auto-commit leftover changes at session end with a generated
   message that violates commit discipline, including em dashes, en dashes, and no scope.
3. There is no exception for "minor" or "trivial" leftover changes. Every change either gets
   its own focused commit or gets reverted.

## Checklist before done

- [ ] `git status --short` returns empty output
- [ ] `git diff --stat` returns empty output
- [ ] `git diff --cached --stat` returns empty output
