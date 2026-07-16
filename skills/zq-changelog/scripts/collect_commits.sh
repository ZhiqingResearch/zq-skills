#!/usr/bin/env bash
# Print commits since the most recent tag as "<short-hash>\t<subject>".
# Falls back to the full history when the repo has no tags.
set -euo pipefail

if last_tag=$(git describe --tags --abbrev=0 2>/dev/null); then
  range="${last_tag}..HEAD"
else
  echo "warning: no tags found; showing full history" >&2
  range="HEAD"
fi

git log --no-merges --pretty=format:'%h%x09%s' "$range"
