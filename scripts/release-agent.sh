#!/usr/bin/env bash
# Weekly unattended release: headless Claude runs scripts/release-agent.md
# locally, so the tag is GPG-signed by the maintainer's gpg-agent.
# In -p mode, any tool call needing approval outside this list is denied.
set -euo pipefail
cd "$(dirname "$0")/.."

exec claude -p "$(cat scripts/release-agent.md)" \
  --allowedTools \
  "Read" "Grep" "Glob" \
  "Bash(uv run scripts/release.py:*)" \
  "Bash(git fetch:*)" "Bash(git describe:*)" "Bash(git log:*)" "Bash(git diff:*)" "Bash(git show:*)" \
  "Bash(gh run list:*)" "Bash(gh run watch:*)" "Bash(gh run view:*)" \
  "Bash(gh release view:*)" "Bash(gh release edit:*)" \
  "Bash(envchain ntfy-claude ntfy publish:*)"
