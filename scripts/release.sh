#!/usr/bin/env bash
# release.sh — tag and release a new version of tether (community edition).
#
# Usage:
#   ./scripts/release.sh --patch        # 0.0.0 → 0.0.1    (or alpha → stable: 0.0.1a2 → 0.0.1)
#   ./scripts/release.sh --minor        # 0.0.1 → 0.1.0
#   ./scripts/release.sh --major        # 0.1.0 → 1.0.0
#   ./scripts/release.sh --alpha        # 0.0.0 → 0.0.1a1, or 0.0.1a1 → 0.0.1a2
#
# Version convention (PEP 440 throughout):
#   pyproject.toml : 0.0.1a1   git tag: v0.0.1a1
#   pyproject.toml : 0.0.1     git tag: v0.0.1
#
# After pushing, GHA creates a GitHub Release for the community edition.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYPROJECT="$REPO_ROOT/pyproject.toml"

# ── Read current version ──────────────────────────────────────────────────────

CURRENT=$(grep '^version = ' "$PYPROJECT" | sed 's/version = "\(.*\)"/\1/')

# Parse:  MAJOR.MINOR.PATCHaN  or  MAJOR.MINOR.PATCH
if [[ "$CURRENT" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(a([0-9]+))?$ ]]; then
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
    ALPHA_N="${BASH_REMATCH[5]:-}"   # empty if not an alpha
else
    echo "ERROR: Cannot parse version in pyproject.toml: '$CURRENT'" >&2
    exit 1
fi

# ── Parse arguments ───────────────────────────────────────────────────────────

usage() {
    cat <<USAGE
Usage: $0 [--major | --minor | --patch | --alpha]

  --major   Bump major (resets minor + patch to 0). Stable release.
  --minor   Bump minor (resets patch to 0). Stable release.
  --patch   Bump patch. If currently on alpha, promotes to stable instead.
  --alpha   Start or increment alpha pre-release.
              Not on alpha: bumps patch, adds a1  (0.0.0  → 0.0.1a1)
              On alpha:     increments alpha N     (0.0.1a1 → 0.0.1a2)

Current version: $CURRENT
USAGE
    exit 1
}

[[ $# -eq 0 ]] && usage

BUMP=""
DO_ALPHA=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --major) BUMP="major"; shift ;;
        --minor) BUMP="minor"; shift ;;
        --patch) BUMP="patch"; shift ;;
        --alpha) DO_ALPHA=true; shift ;;
        *) usage ;;
    esac
done

# ── Compute new version ───────────────────────────────────────────────────────

if $DO_ALPHA; then
    if [[ -n "$ALPHA_N" ]]; then
        NEW_ALPHA_N=$((ALPHA_N + 1))
        NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}a${NEW_ALPHA_N}"
    else
        NEW_PATCH=$((PATCH + 1))
        NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}a1"
    fi
elif [[ "$BUMP" == "patch" ]]; then
    if [[ -n "$ALPHA_N" ]]; then
        NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
    else
        NEW_PATCH=$((PATCH + 1))
        NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
    fi
elif [[ "$BUMP" == "minor" ]]; then
    NEW_MINOR=$((MINOR + 1))
    NEW_VERSION="${MAJOR}.${NEW_MINOR}.0"
elif [[ "$BUMP" == "major" ]]; then
    NEW_MAJOR=$((MAJOR + 1))
    NEW_VERSION="${NEW_MAJOR}.0.0"
else
    usage
fi

GIT_TAG="v${NEW_VERSION}"

# ── Confirm ───────────────────────────────────────────────────────────────────

echo ""
echo "  Current version : $CURRENT"
echo "  New version     : $NEW_VERSION   (pyproject.toml)"
echo "  Git tag         : $GIT_TAG"
echo ""

BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)
echo "  Branch          : $BRANCH"

if [[ ! "$NEW_VERSION" =~ a[0-9]+$ && "$BRANCH" != "main" ]]; then
    echo ""
    echo "  WARNING: releasing a stable version from branch '$BRANCH' (not main)."
fi
echo ""
read -r -p "Proceed? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# ── Apply ─────────────────────────────────────────────────────────────────────

cd "$REPO_ROOT"

sed -i "s/^version = \"${CURRENT}\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT"

git add pyproject.toml
git commit -m "chore: release ${GIT_TAG}"
git tag "$GIT_TAG"
git push origin "$BRANCH"
git push origin "$GIT_TAG"

echo ""
echo "Done. GHA will create the GitHub Release."
