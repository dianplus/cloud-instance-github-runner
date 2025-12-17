#!/bin/bash
# Update CHANGELOG.md with a new release version
# Usage: ./scripts/update-changelog.sh <version>
# Example: ./scripts/update-changelog.sh 1.0.2
# Example: ./scripts/update-changelog.sh v1.0.2

set -e

VERSION_INPUT="${1:-}"

if [ -z "$VERSION_INPUT" ]; then
    echo "Error: Version is required"
    echo "Usage: $0 <version>"
    echo "Example: $0 1.0.2"
    echo "Example: $0 v1.0.2"
    exit 1
fi

# Normalize version (remove 'v' prefix if present)
VERSION="${VERSION_INPUT#v}"

# Validate version format (semantic versioning)
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$ ]]; then
    echo "Error: Invalid version format. Expected semantic version (e.g., 1.0.2 or 1.0.2-rc.1)"
    exit 1
fi

VERSION_V="v${VERSION}"
RELEASE_DATE=$(date +%Y-%m-%d)
REPO_URL="https://github.com/dianplus/cloud-instance-github-runner"

echo "Updating CHANGELOG.md to version $VERSION..."

# Check if CHANGELOG.md exists
if [ ! -f "CHANGELOG.md" ]; then
    echo "Error: CHANGELOG.md not found"
    exit 1
fi

# Check if [Unreleased] section exists
if ! grep -q "^## \[Unreleased\]" CHANGELOG.md; then
    echo "Error: [Unreleased] section not found in CHANGELOG.md"
    exit 1
fi

# Get the latest version before replacing Unreleased (for link generation)
LATEST_VERSION=$(grep -E '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' CHANGELOG.md | head -1 | sed -E 's/^## \[([0-9]+\.[0-9]+\.[0-9]+)\].*/\1/' || echo "")

# Step 1: Replace [Unreleased] with version and date
sed -i.bak "s/^## \[Unreleased\]/## [$VERSION] - $RELEASE_DATE/" CHANGELOG.md
rm -f CHANGELOG.md.bak
echo "✓ Updated CHANGELOG.md: Replaced [Unreleased] with [$VERSION] - $RELEASE_DATE"

# Step 2: Add new [Unreleased] section at the top (after the header)
# Find the line number of the first version entry
FIRST_VERSION_LINE=$(grep -n "^## \[" CHANGELOG.md | head -1 | cut -d: -f1)
if [ -n "$FIRST_VERSION_LINE" ]; then
    # Insert [Unreleased] section before the first version entry
    sed -i.bak "${FIRST_VERSION_LINE}i\\
## [Unreleased]\\
\\
### Added\\
\\
### Changed\\
\\
### Fixed\\
" CHANGELOG.md
    rm -f CHANGELOG.md.bak
    echo "✓ Added new [Unreleased] section to CHANGELOG.md"
fi

echo ""
echo "✓ Successfully updated CHANGELOG.md:"
echo "   - Released version: [$VERSION] - $RELEASE_DATE"
echo "   - Added new [Unreleased] section"
