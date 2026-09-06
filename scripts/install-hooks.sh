#!/bin/sh
# Activate the fail-safe git hooks (.githooks/pre-commit, .githooks/pre-push).
# core.hooksPath is local git config and is NOT cloned, so run this once
# after every fresh clone:  ./scripts/install-hooks.sh
set -e
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
echo "Git hooks activated: $(git config core.hooksPath) (pre-commit, pre-push)"
