#!/bin/bash
# Git pre-commit hook variant of block-secret-commit.sh.
#
# Install with .claude/scripts/install-git-hooks.sh — symlinks this file into
# every repo's .git/hooks/pre-commit. Provides the same secret scan as the
# Claude Code PreToolUse hook, but at the GIT layer — so it fires even when
# committing outside Claude Code (CLI, IDE git, GitHub Desktop, etc.).
#
# Patterns matched on STAGED diff only. Working-tree changes are ignored
# (they're not part of this commit).
#
# Bypass (mirrors the Claude Code sentinel): use `git commit --no-verify`
# OR set GIT_SECRET_ACK=1 in env. Use sparingly.

set -uo pipefail

RED="\033[0;31m"; YEL="\033[0;33m"; NC="\033[0m"

if [ -n "${GIT_SECRET_ACK:-}" ]; then
    exit 0
fi

DIFF="$(git diff --cached 2>/dev/null || true)"
[ -z "$DIFF" ] && exit 0

ADDED="$(printf '%s' "$DIFF" | grep -E '^\+[^+]' || true)"
[ -z "$ADDED" ] && exit 0

PATTERNS=(
  'AKIA[0-9A-Z]{16}'
  'aws_secret_access_key[[:space:]]*=[[:space:]]*[A-Za-z0-9/+=]{40}'
  'sk-ant-(api|admin)[0-9a-zA-Z_-]{20,}'
  'sk-[A-Za-z0-9]{20,}'
  'ghp_[A-Za-z0-9]{30,}'
  'github_pat_[A-Za-z0-9_]{40,}'
  'xox[abprs]-[A-Za-z0-9-]{10,}'
  'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}'
  '-----BEGIN ((RSA|EC|OPENSSH|DSA|PGP) )?PRIVATE KEY-----'
  'AIza[0-9A-Za-z_-]{35}'
  'glpat-[0-9A-Za-z_-]{20}'
  'hf_[A-Za-z0-9]{30,}'
)

MATCHED=""
for pat in "${PATTERNS[@]}"; do
    HIT="$(printf '%s' "$ADDED" | grep -E -e "$pat" 2>/dev/null | head -3 || true)"
    if [ -n "$HIT" ]; then
        MATCHED+="  pattern: $pat\n$HIT\n\n"
    fi
done

if [ -n "$MATCHED" ]; then
    printf "${RED}BLOCKED (pre-commit):${NC} staged changes appear to contain secrets.\n" >&2
    printf "${YEL}Matches:${NC}\n%b" "$MATCHED" >&2
    printf "${YEL}Fix:${NC} move secrets to .env (gitignored), use git-secrets to scrub history, then retry.\n" >&2
    printf "${YEL}Bypass:${NC} GIT_SECRET_ACK=1 git commit ...  (or --no-verify if you're certain).\n" >&2
    exit 1
fi

exit 0
