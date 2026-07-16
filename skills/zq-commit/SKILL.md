---
name: zq-commit
description: Write clear, conventional git commit messages from a staged diff. Use when the user asks to commit changes, write a commit message, or clean up commit history.
---

# zq-commit

Produce a well-structured commit message for the currently staged changes.

## Steps

1. Inspect what is staged:
   ```bash
   git diff --cached --stat
   git diff --cached
   ```
2. Group the changes by intent. If the diff mixes unrelated concerns, say so and
   suggest splitting into multiple commits instead of one.
3. Write the message in Conventional Commits form:

   ```
   <type>(<optional scope>): <summary in imperative mood, <=72 chars>

   <body: what changed and WHY, wrapped at 72 cols. Omit if the summary is enough.>
   ```

   Common `<type>` values: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`.

## Rules

- Summary line is imperative ("add", not "added"/"adds"), no trailing period.
- The body explains *why*, not a restatement of the diff.
- Never invent changes that aren't in the diff.
- Do not run `git commit` unless the user explicitly asks you to.
