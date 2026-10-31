#!/bin/zsh
# Continue the UI revamp in a headless Claude Code run when the interactive
# session has stopped, e.g. because its usage credit ran out (TASKS "UI revamp",
# ADR-102). Run hourly by launchd (com.eulerlab.uirevamp).
#
# It does nothing unless:
#   - data/cache/ui-revamp.active exists (delete it to stop for good);
#   - that file has not been touched for 90 minutes: the interactive session and
#     each run touch it, so a live session is never raced;
#   - no other run holds the lock.
#
# A run may edit files and run only the commands allowed below. It commits on
# the ui-revamp branch and never pushes. Output: data/cache/ui-revamp-logs/.

set -u
REPO="/Users/avneesh/EulerLab"
FLAG="$REPO/data/cache/ui-revamp.active"
LOCK="$REPO/data/cache/ui-revamp.lock"
LOGS="$REPO/data/cache/ui-revamp-logs"
QUIET_MINUTES=90

# launchd starts with a bare PATH: uv lives in ~/.local/bin and the working
# node in nvm (Homebrew's node 20.5 is missing its icu4c library). The first
# unattended run (2026-10-28) could not run `make verify` without these.
NODE_BIN=$(ls -d "$HOME"/.nvm/versions/node/v20*/bin 2>/dev/null | sort -V | tail -1)
export PATH="$HOME/.local/bin:${NODE_BIN:+$NODE_BIN:}/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO" || exit 0
[ -f "$FLAG" ] || exit 0
# Quiet long enough? (find prints the file only if older than the limit.)
[ -n "$(find "$FLAG" -mmin +$QUIET_MINUTES 2>/dev/null)" ] || exit 0
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

mkdir -p "$LOGS"
CLAUDE=$(ls -d "$HOME"/.vscode/extensions/anthropic.claude-code-*-darwin-arm64 2>/dev/null \
  | sort -V | tail -1)/resources/native-binary/claude
[ -x "$CLAUDE" ] || { echo "$(date) no claude binary" >> "$LOGS/missing.log"; exit 0; }

touch "$FLAG"
git checkout -q ui-revamp 2>/dev/null || exit 0

PROMPT='You are continuing the EulerLab UI revamp unattended; the operator approved it and asked not to be asked for permission. Read CLAUDE.md, then the "UI revamp" section of TASKS.md and docs/DECISIONS/ADR-102-ui-revamp.md. If a row is DOING, an earlier run or session was cut off: finish that screen, building on the uncommitted changes in the working tree. Otherwise take the first row whose status is TODO, set it to DOING, and revamp that screen following the rules in that section. Keep behaviour and data the same; change presentation only. Touch data/cache/ui-revamp.active every few steps. Then run `make verify`; if it is green, set the row to DONE with one line of what changed, update docs/ARCHITECTURE.md if behaviour changed, and commit on the ui-revamp branch with a conventional message ending "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>". If it is red and you cannot fix it, revert your changes to that screen, mark the row BLOCKED with the reason, and commit that. Never push, never run make gate or make validate, never edit gates.py or mandate.yaml. If no TODO rows remain except T-4263, stop and leave T-4263 for the operator.'

"$CLAUDE" -p "$PROMPT" \
  --permission-mode acceptEdits \
  --allowedTools "Read" "Edit" "Write" "Glob" "Grep" \
    "Bash(make verify)" "Bash(uv run:*)" "Bash(npx tsc:*)" "Bash(npx next lint:*)" \
    "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git add:*)" \
    "Bash(git commit:*)" "Bash(git checkout -- :*)" "Bash(touch:*)" "Bash(ls:*)" \
  >> "$LOGS/$(date +%Y-%m-%d_%H%M).log" 2>&1

touch "$FLAG"
