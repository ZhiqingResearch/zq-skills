# zq-skills

A collection of [Agent Skills](https://github.com/vercel-labs/skills) installable with `npx skills`.
Works with Claude Code, Cursor, Codex, OpenCode, and 70+ other agents.

## Install

The `npx skills` CLI auto-detects which coding agents you have installed and
installs into them; add `--agent <name>` to target one explicitly.

```bash
# List available skills without installing
npx skills add ZhiqingResearch/zq-skills --list

# Install every skill in this repo
npx skills add ZhiqingResearch/zq-skills

# Install a single skill by its frontmatter `name`
npx skills add ZhiqingResearch/zq-skills --skill zq-commit

# Install a single skill into a specific agent
npx skills add ZhiqingResearch/zq-skills --skill zq-commit --agent claude-code
```

Notes:

- `--skill` matches the `name` in a skill's frontmatter, not its folder name.
  Quote names containing spaces: `--skill "My Skill"`.
- Omitting `--skill` installs all skills in the repo.
- Common `--agent` values: `claude-code`, `cursor`, `codex`, `github-copilot`,
  `gemini-cli`, `windsurf`, `zed`, `continue`, `cline`, `opencode`, `universal`
  — [73 agents supported in total](https://github.com/vercel-labs/skills).

## Skills

| Skill | Description |
| ----- | ----------- |
| [`zq-amazon-listing-fill`](skills/zq-amazon-listing-fill/SKILL.md) | Fill an Amazon flat-file listing template for a batch of UPCs via Keepa + web search, highlighting inferred values. |
| [`zq-commit`](skills/zq-commit/SKILL.md) | Write clear, conventional git commit messages from a staged diff. |
| [`zq-changelog`](skills/zq-changelog/SKILL.md) | Generate a changelog section from merged commits, with a helper script. |

## Repository layout

```
zq-skills/
├── skills/
│   ├── zq-commit/
│   │   └── SKILL.md
│   └── zq-changelog/
│       ├── SKILL.md
│       ├── reference.md          # progressive-disclosure detail
│       └── scripts/
│           └── collect_commits.sh
├── scripts/
│   └── validate-skills.mjs       # frontmatter/structure linter
└── .github/workflows/ci.yml
```

The `skills/<name>/SKILL.md` layout is what the `npx skills` CLI discovers. See
each skill's `SKILL.md` for details.

## Authoring a new skill

1. Create `skills/<name>/SKILL.md` with `name` + `description` frontmatter.
2. Keep `SKILL.md` short; move long reference material into a sibling `reference.md`
   and link to it (progressive disclosure keeps the agent's context small).
3. Put any bundled scripts/assets under `skills/<name>/scripts/`.
4. Run `node scripts/validate-skills.mjs` before committing.

## License

MIT — see [LICENSE](LICENSE).
