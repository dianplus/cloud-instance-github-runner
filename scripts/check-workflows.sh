#!/usr/bin/env bash
# Simple local checker for GitHub workflows in this repo.
# It runs actionlint (which in turn can use shellcheck if available).

set -euo pipefail

if command -v actionlint >/dev/null 2>&1; then
  echo "Running actionlint on GitHub workflows..."
  actionlint
  echo "✓ actionlint completed successfully"
  exit 0
fi

cat <<'EOF'
Error: actionlint not found in PATH.

To install actionlint locally, you can use one of the following methods:

- Go (requires Go toolchain):
    go install github.com/rhysd/actionlint/cmd/actionlint@latest

- Homebrew (macOS):
    brew install actionlint

After installation, re-run:
    ./scripts/check-workflows.sh
EOF

exit 1
