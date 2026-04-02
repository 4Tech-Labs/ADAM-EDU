#!/usr/bin/env bash
set -euo pipefail

repository_url="${1:-https://github.com/garrytan/gstack.git}"
ref="${2:-main}"

command -v git >/dev/null 2>&1 || {
  echo "Required command not found: git" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCK_FILE="$REPO_ROOT/scripts/agents/gstack.lock.json"
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/adam-gstack-XXXXXX")"

cleanup() {
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

git clone --single-branch --branch "$ref" --depth 1 "$repository_url" "$TEMP_ROOT" >/dev/null
commit="$(git -C "$TEMP_ROOT" rev-parse HEAD)"
version="$(tr -d '\r\n' < "$TEMP_ROOT/VERSION")"
updated_utc="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

cat > "$LOCK_FILE" <<EOF
{
  "repository": "$repository_url",
  "ref": "$ref",
  "commit": "$commit",
  "version": "$version",
  "updated_utc": "$updated_utc"
}
EOF

echo "Pinned gstack lock updated."
echo "  repository: $repository_url"
echo "  ref:        $ref"
echo "  lock:       $LOCK_FILE"
echo "Run bootstrap again before validating local runtimes."
