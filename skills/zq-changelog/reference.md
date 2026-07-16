# zq-changelog reference

Supporting detail for the `zq-changelog` skill. Load this only when you need the
mapping table or hit an edge case.

## Conventional Commit type → changelog section

| Commit type              | Section       |
| ------------------------ | ------------- |
| `feat`                   | Features      |
| `fix`                    | Fixes         |
| `perf`                   | Performance   |
| `refactor`               | Refactors     |
| `docs`                   | Docs          |
| `chore`, `test`, `build`, `ci`, `style` | Other (usually omit from user-facing notes) |
| no recognizable prefix   | Other         |

## Breaking changes

A commit is breaking if either is true:

- the type has a `!` suffix, e.g. `feat!: ...` or `feat(api)!: ...`
- the body/footer contains a `BREAKING CHANGE:` line

Surface all breaking changes in a dedicated `### ⚠ Breaking Changes` section at the
top of the version block, regardless of their type.

## Edge cases

- **No tags in the repo:** `collect_commits.sh` falls back to the full history.
  Warn the user that the changelog spans the entire project.
- **Squash/merge commits:** prefer the PR title (the first line) and ignore the
  auto-generated commit list in the body.
- **Reverts:** pair a `revert:` commit with the commit it reverts and drop both
  from the changelog unless the revert shipped on its own.
