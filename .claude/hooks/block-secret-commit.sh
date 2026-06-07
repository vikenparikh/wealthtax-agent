#!/bin/bash
# PreToolUse hook for Bash. Scans `git commit` / `git add` commands and the
# current staged diff for secret-shaped strings. Blocks (exit 2) on match.
#
# Triggers only on git commands. Other Bash commands pass through.
#
# Sentinel to bypass: append `# ACK-SECRET` to the command. Use only when
# you're sure the matched string is a placeholder or test fixture.

set -euo pipefail

RED="\033[0;31m"; YEL="\033[0;33m"; NC="\033[0m"

INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))' 2>/dev/null || true)"

[ -z "$CMD" ] && exit 0

# Only inspect git commit / git push paths
if ! printf '%s' "$CMD" | grep -qE 'git[[:space:]]+(commit|push|add[[:space:]]+(-A|--all|\.))'; then
    exit 0
fi

if printf '%s' "$CMD" | grep -qE '# ?ACK-SECRET'; then
    exit 0
fi

# Look at staged diff. If nothing staged, also check working-tree diff
# (covers `git add . && git commit` chained).
DIFF="$(git diff --cached 2>/dev/null || true)"
[ -z "$DIFF" ] && DIFF="$(git diff 2>/dev/null || true)"
[ -z "$DIFF" ] && exit 0

# Strip lines that are removals or context — only added lines matter
ADDED="$(printf '%s' "$DIFF" | grep -E '^\+[^+]' || true)"
[ -z "$ADDED" ] && exit 0

PATTERNS=(
  'AKIA[0-9A-Z]{16}'                                     # AWS access key id
  'aws_secret_access_key[[:space:]]*=[[:space:]]*[A-Za-z0-9/+=]{40}'  # AWS secret
  'sk-ant-(api|admin)[0-9a-zA-Z_-]{20,}'                # Anthropic API key
  'sk-[A-Za-z0-9]{20,}'                                  # OpenAI / generic sk- key
  'ghp_[A-Za-z0-9]{30,}'                                 # GitHub PAT (classic)
  'github_pat_[A-Za-z0-9_]{40,}'                         # GitHub PAT (fine-grained)
  'xox[abprs]-[A-Za-z0-9-]{10,}'                         # Slack token
  'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}'  # JWT
  '-----BEGIN ((RSA|EC|OPENSSH|DSA|PGP) )?PRIVATE KEY-----'        # Private key
  'AIza[0-9A-Za-z_-]{35}'                                # Google API key
  'glpat-[0-9A-Za-z_-]{20}'                              # GitLab PAT
  'hf_[A-Za-z0-9]{30,}'                                  # HuggingFace token
)

MATCHED=""
for pat in "${PATTERNS[@]}"; do
    HIT="$(printf '%s' "$ADDED" | grep -E -e "$pat" 2>/dev/null | head -3 || true)"
    if [ -n "$HIT" ]; then
        MATCHED+="  pattern: $pat\n$HIT\n\n"
    fi
done

if [ -n "$MATCHED" ]; then
    printf "${RED}BLOCKED:${NC} commit appears to contain secrets.\n" >&2
    printf "${YEL}Matches:${NC}\n%b" "$MATCHED" >&2
    printf "${YEL}Fix:${NC} move secrets to .env (gitignored), use git-secrets/git filter-repo to scrub history, then retry.\n" >&2
    printf "${YEL}Override:${NC} append %s# ACK-SECRET%s if this is a test fixture or placeholder.\n" "$RED" "$NC" >&2
    exit 2
fi

exit 0
