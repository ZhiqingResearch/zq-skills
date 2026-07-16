# zq-skills

A collection of [Agent Skills](https://github.com/vercel-labs/skills) installable with `npx skills`.
Works with Claude Code, Cursor, Codex, OpenCode, and 70+ other agents.

## Install

Install every skill in this repo:

```bash
npx skills add ZhiqingResearch/zq-skills
```

List what's available without installing:

```bash
npx skills add ZhiqingResearch/zq-skills --list
```

Install into a specific agent (the CLI auto-detects installed agents, but you can force one):

```bash
npx skills add ZhiqingResearch/zq-skills --agent claude-code
```

## Skills

| Skill | Description |
| ----- | ----------- |
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
