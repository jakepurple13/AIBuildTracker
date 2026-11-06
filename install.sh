#!/usr/bin/env bash
# Install the build-tracker skill for Claude Code.
#
#   curl -fsSL https://raw.githubusercontent.com/jakepurple13/AIBuildTracker/main/install.sh | bash
#   ./install.sh               # from a clone
#   ./install.sh --uninstall
#
# Installs to ${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/build-tracker
set -euo pipefail

REPO="jakepurple13/AIBuildTracker"
BRANCH="${BUILD_TRACKER_BRANCH:-main}"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DEST="$SKILLS_DIR/build-tracker"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$DEST"
  echo "Removed $DEST"
  echo "Tracker data (if any) is in ~/.build-tracker; delete it by hand if you want it gone."
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required (tracker.py runs the page's local server)." >&2
  exit 1
fi

# Use the local checkout if this script runs from one; otherwise download the repo.
SRC=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/skills/build-tracker/SKILL.md" ]]; then
  SRC="$SCRIPT_DIR/skills/build-tracker"
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "Downloading $REPO@$BRANCH..."
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" | tar -xz -C "$TMP"
  SRC="$(find "$TMP" -maxdepth 3 -type d -path '*/skills/build-tracker' | head -n1)"
  [[ -n "$SRC" ]] || { echo "error: skills/build-tracker not found in download." >&2; exit 1; }
fi

mkdir -p "$SKILLS_DIR"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"
chmod +x "$DEST/tracker.py"

echo "Installed build-tracker to $DEST"
echo "Restart Claude Code (or start a new session), then say: \"Set up the build tracker for this work\""
