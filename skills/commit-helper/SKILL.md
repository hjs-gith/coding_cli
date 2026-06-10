---
name: commit-helper
description: Stage changes and write a clean, conventional git commit message.
---

# Commit Helper

Help the user create a well-formed git commit.

Steps:
1. Run `git status --porcelain` to see what has changed. If nothing has changed,
   tell the user there is nothing to commit and stop.
2. Run `git diff --staged` (and `git diff` for unstaged work) to understand the
   changes.
3. If nothing is staged, ask the user whether to stage everything with
   `git add -A`, or stage only specific files they name.
4. Draft a commit message in the Conventional Commits style:
   - A summary line: `type(scope): short imperative summary` (max ~72 chars).
     Common types: feat, fix, docs, refactor, test, chore.
   - A blank line, then a short body explaining the *why* if it is not obvious.
5. Show the proposed message to the user and ask for confirmation.
6. On approval, commit with `git commit -m "<summary>" -m "<body>"`.

Never push unless the user explicitly asks. Never include secrets in the message.
