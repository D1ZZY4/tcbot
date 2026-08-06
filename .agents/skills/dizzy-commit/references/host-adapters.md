# Host and Upstream Adapters

The core skill is Git-provider neutral. This reference records optional conventions that may
apply when a repository uses a particular hosting service or workflow.

## Generic rule

Use the repository's configured remote and upstream branch:

```bash
git remote -v
git branch --show-current
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
```

Do not assume the remote is named `origin`, the default branch is `main`, or the host is GitHub.
Do not rewrite public history on a protected or shared branch without explicit instruction.

## GitHub-style trailers

Some hosts recognize `Co-authored-by: Name <email>` trailers. Use one only when:

- the repository or user explicitly allows co-author trailers,
- the provider supplied the identity for this purpose, and
- the email is verified and wrapped in angle brackets.

Never invent a provider email or infer one from a username.

## Provider-specific behavior

GitHub, GitLab, Bitbucket, and self-hosted Git servers may differ in protected branches,
review requirements, trailer handling, and push permissions. Treat those details as adapters.
Read the repository's own contribution or hosting instructions before pushing or creating a
pull request.

## Identity changes

Changing `user.name`, `user.email`, signing configuration, credentials, or remotes is a separate
mutating operation. Explain the change, confirm the target, and get explicit approval first.