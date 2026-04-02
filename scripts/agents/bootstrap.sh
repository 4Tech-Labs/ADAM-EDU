#!/usr/bin/env bash
set -euo pipefail

runtime_host="both"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      runtime_host="${2:-}"
      shift 2
      ;;
    --host=*)
      runtime_host="${1#--host=}"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

case "$runtime_host" in
  both|codex|claude) ;;
  *)
    echo "Invalid --host value: $runtime_host (expected both, codex, or claude)" >&2
    exit 1
    ;;
esac

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

json_value() {
  local key="$1"
  sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$LOCK_FILE" | head -n 1
}

remove_path_if_exists() {
  local path="$1"
  [ -e "$path" ] || [ -L "$path" ] || return 0
  rm -rf "$path"
}

copy_tree() {
  local source="$1"
  local destination="$2"

  remove_path_if_exists "$destination"
  mkdir -p "$(dirname "$destination")"
  cp -R "$source" "$destination"
}

clone_gstack_repo() {
  local repository_url="$1"
  local ref="$2"
  local destination="$3"

  mkdir -p "$(dirname "$destination")"
  git clone --single-branch --branch "$ref" --depth 1 "$repository_url" "$destination" >/dev/null
}

ensure_gstack_repo_at_commit() {
  local repository_url="$1"
  local ref="$2"
  local commit="$3"
  local destination="$4"

  if [ -e "$destination" ] && [ ! -d "$destination/.git" ]; then
    remove_path_if_exists "$destination"
  fi

  if [ ! -d "$destination/.git" ]; then
    clone_gstack_repo "$repository_url" "$ref" "$destination"
  else
    local origin
    origin="$(git -C "$destination" remote get-url origin 2>/dev/null || true)"
    if [ "$origin" != "$repository_url" ]; then
      remove_path_if_exists "$destination"
      clone_gstack_repo "$repository_url" "$ref" "$destination"
    fi
  fi

  local current_commit
  current_commit="$(git -C "$destination" rev-parse HEAD)"
  if [ "$current_commit" != "$commit" ]; then
    git -C "$destination" fetch --depth 1 origin "$ref" >/dev/null
    if ! git -C "$destination" rev-parse --verify "${commit}^{commit}" >/dev/null 2>&1; then
      git -C "$destination" fetch --depth 1 origin "$commit" >/dev/null
    fi
    git -C "$destination" checkout --force --detach "$commit" >/dev/null
    git -C "$destination" clean -fdx >/dev/null
  fi
}

clear_codex_runtime() {
  local skills_root="$1"

  mkdir -p "$skills_root"
  shopt -s nullglob
  for path in "$skills_root"/gstack-*; do
    remove_path_if_exists "$path"
  done
  shopt -u nullglob
}

clear_claude_runtime() {
  local skills_root="$1"

  remove_path_if_exists "$skills_root"
  mkdir -p "$skills_root"
}

invoke_gstack_setup() {
  local runtime_path="$1"
  local target_host="$2"

  (
    cd "$runtime_path"
    ./setup --host "$target_host"
  )
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCK_FILE="$REPO_ROOT/scripts/agents/gstack.lock.json"
ADAM_SKILL_ROOT="$REPO_ROOT/.agents/skills/adam-orchestrator"
CODEX_SKILLS_ROOT="$REPO_ROOT/.agents/skills"
CLAUDE_SKILLS_ROOT="$REPO_ROOT/.claude/skills"

require_command git

if [ ! -f "$LOCK_FILE" ]; then
  echo "gstack lock file not found at $LOCK_FILE" >&2
  exit 1
fi

if [ ! -f "$ADAM_SKILL_ROOT/SKILL.md" ]; then
  echo "Tracked adam-orchestrator skill not found at $ADAM_SKILL_ROOT" >&2
  exit 1
fi

repository_url="$(json_value repository)"
ref="$(json_value ref)"
commit="$(json_value commit)"

if [ "$runtime_host" = "both" ] || [ "$runtime_host" = "codex" ]; then
  clear_codex_runtime "$CODEX_SKILLS_ROOT"
  codex_gstack_root="$CODEX_SKILLS_ROOT/gstack"
  ensure_gstack_repo_at_commit "$repository_url" "$ref" "$commit" "$codex_gstack_root"
  invoke_gstack_setup "$codex_gstack_root" "codex"
fi

if [ "$runtime_host" = "both" ] || [ "$runtime_host" = "claude" ]; then
  clear_claude_runtime "$CLAUDE_SKILLS_ROOT"
  claude_gstack_root="$CLAUDE_SKILLS_ROOT/gstack"
  ensure_gstack_repo_at_commit "$repository_url" "$ref" "$commit" "$claude_gstack_root"
  invoke_gstack_setup "$claude_gstack_root" "claude"
  copy_tree "$ADAM_SKILL_ROOT" "$CLAUDE_SKILLS_ROOT/adam-orchestrator"
fi

echo "Agent bootstrap complete."
echo "  repo root: $REPO_ROOT"
echo "  host(s):   $runtime_host"
echo "Restart Codex or Claude if the current session had already loaded skills."
