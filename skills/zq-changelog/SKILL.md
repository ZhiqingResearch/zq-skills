---
name: zq-changelog
description: Generate a changelog section from merged git commits since the last tag. Use when the user asks to write release notes, a changelog, or a "what changed" summary for a version.
---

# zq-changelog

Turn recent git history into a human-readable changelog section grouped by change type.

## Steps

1. Collect the commits since the last release tag with the bundled helper:
   ```bash
   bash scripts/collect_commits.sh
   ```
   It prints one commit per line as `<hash>\t<subject>` for everything after the
   most recent tag (or the whole history if there are no tags).

2. Bucket each commit by its Conventional Commit type into these sections, in order:
   **Features**, **Fixes**, **Performance**, **Refactors**, **Docs**, **Other**.
   Skip empty sections.

3. Emit Markdown like:

   ```markdown
   ## <next version> — <YYYY-MM-DD>

   ### Features
   - Short, user-facing description (#PR if known)

   ### Fixes
   - ...
   ```

## Rules

- Write for *users*, not developers — describe the effect, not the implementation.
- Merge duplicate/near-duplicate commits into one line.
- Never fabricate version numbers or dates; ask the user if the next version is unknown.

For type→section mapping details and edge cases, see [reference.md](reference.md).
