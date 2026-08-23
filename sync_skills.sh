#!/usr/bin/env bash
# Pull the canonical skills repo and re-sync into all three harnesses
# (Claude Code, DSH, Kimi Code). Safe to run on a schedule and from any shell;
# failures are logged, never fatal to the harnesses (they keep their last state).
set -uo pipefail

REPO="$HOME/claude/paper-tools"
export GIT_SSH_COMMAND="ssh -F $HOME/.ssh/config"

cd "$REPO" || exit 1
# Cap the pull so an unreachable network can't stall a SessionStart hook.
timeout 30 git pull --ff-only 2>&1 || \
  echo "sync_skills: git pull skipped (local changes, offline, or slow); installing from current checkout"
bash "$REPO/install_skills.sh"
