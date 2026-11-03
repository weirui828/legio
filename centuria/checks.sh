#!/usr/bin/env bash
# The project's checks. Exit 0 only when the branch is fit to review.
#
# The gate runs this from the project root with a job's worktree as the
# working directory. Keep it fast, deterministic and non-interactive: no watch
# modes, no prompts, and nothing that rewrites files (no --fix, no snapshot
# updates). It must exit non-zero on any failure, so keep `set -euo pipefail`.
#
# Replace the block below with this project's real commands, for example:
#
#   npm ci --prefer-offline
#   npm run lint
#   npm run typecheck
#   npm test -- --run
#   npm run build
set -euo pipefail

echo "centuria: .centuria/checks.sh has no checks yet." >&2
echo "centuria: put this project's lint, typecheck, test and build here." >&2
exit 1
