#!/usr/bin/env node
// Lint every skills/**/SKILL.md for the conventions the `npx skills` CLI expects:
//   - valid YAML-ish frontmatter delimited by ---
//   - required `name` (lowercase, hyphen/number) and `description`
//   - unique `name` across the repo
//   - non-empty body after the frontmatter
// Zero dependencies so CI needs no install step.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = process.cwd();
const SKILLS_DIR = join(ROOT, "skills");

/** Recursively collect every SKILL.md path under skills/. */
function findSkillFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...findSkillFiles(full));
    else if (entry === "SKILL.md") out.push(full);
  }
  return out;
}

/** Parse the leading `---`-delimited frontmatter block. Returns {ok, fields, body}. */
function parseFrontmatter(text) {
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) return { ok: false };
  const fields = {};
  for (const line of match[1].split(/\r?\n/)) {
    const m = line.match(/^([A-Za-z0-9_.-]+):\s*(.*)$/);
    if (m) fields[m[1]] = m[2].replace(/^["']|["']$/g, "").trim();
  }
  return { ok: true, fields, body: match[2].trim() };
}

const errors = [];
const seenNames = new Map();

let files = [];
try {
  files = findSkillFiles(SKILLS_DIR);
} catch {
  console.error("No skills/ directory found.");
  process.exit(1);
}

if (files.length === 0) errors.push("No SKILL.md files found under skills/.");

for (const file of files) {
  const rel = relative(ROOT, file);
  const fm = parseFrontmatter(readFileSync(file, "utf8"));

  if (!fm.ok) {
    errors.push(`${rel}: missing or malformed --- frontmatter block.`);
    continue;
  }
  const { name, description } = fm.fields;

  if (!name) errors.push(`${rel}: missing required 'name' field.`);
  else if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(name))
    errors.push(`${rel}: 'name' must be lowercase words separated by hyphens (got "${name}").`);
  else if (seenNames.has(name))
    errors.push(`${rel}: duplicate name "${name}" (also in ${seenNames.get(name)}).`);
  else seenNames.set(name, rel);

  if (!description) errors.push(`${rel}: missing required 'description' field.`);
  else if (description.length < 20)
    errors.push(`${rel}: 'description' is very short — describe WHAT it does and WHEN to use it.`);

  if (!fm.body) errors.push(`${rel}: body after frontmatter is empty.`);
}

if (errors.length) {
  console.error("✗ Skill validation failed:\n");
  for (const e of errors) console.error("  - " + e);
  process.exit(1);
}

console.log(`✓ ${files.length} skill(s) valid: ${[...seenNames.keys()].join(", ")}`);
