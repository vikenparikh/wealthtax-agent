#!/bin/bash
# PreToolUse hook for Bash. Reads tool input from stdin (JSON), exits 2 to BLOCK,
# 0 to ALLOW. Stderr is shown back to the model as the block reason.
#
# Wired in .claude/settings.json under hooks.PreToolUse.
#
# Catches:
#   - rm -rf on dangerous paths (/, $HOME, project root, /opt/app, /var)
#   - git push --force / -f to main / master / production / release branches
#   - sudo rm / sudo mkfs / dd of=/dev/...
#   - prod DB resets (supabase db reset --linked, dropdb prod*, TRUNCATE on prod schema)
#
# Allowlist sentinel: prefix the command with `# ACK-DANGEROUS` to bypass.
# Use sparingly and only when you've thought it through.

set -euo pipefail

RED="\033[0;31m"; YEL="\033[0;33m"; NC="\033[0m"

# tool_input is on stdin as JSON; pull .command
INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))' 2>/dev/null || true)"

[ -z "$CMD" ] && exit 0

# Explicit user override
if printf '%s' "$CMD" | grep -qE '# ?ACK-DANGEROUS'; then
    exit 0
fi

block() {
    printf "${RED}BLOCKED:${NC} %s\n" "$1" >&2
    printf "${YEL}Command:${NC} %s\n" "$CMD" >&2
    printf "${YEL}Override:${NC} re-run with %s# ACK-DANGEROUS%s appended if intentional.\n" "$RED" "$NC" >&2
    exit 2
}

# 1. rm -rf on dangerous paths
if printf '%s' "$CMD" | grep -qE 'rm[[:space:]]+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-rf|-fr)'; then
    # Extract target paths (everything after rm -rf that doesn't start with -)
    if printf '%s' "$CMD" | grep -qE 'rm[[:space:]]+-[a-zA-Z]*[rf][a-zA-Z]*[[:space:]]+(/|/\*|\$HOME|~|\$\{?HOME\}?|/Users/[^/]+/?$|/opt(/app)?/?$|/var/?$|/etc/?$|\.\./?\.\.)'; then
        block "rm -rf on a system or home root path"
    fi
    # Project root rm -rf .  or  rm -rf *
    if printf '%s' "$CMD" | grep -qE 'rm[[:space:]]+-[a-zA-Z]*[rf][a-zA-Z]*[[:space:]]+(\.|\*)[[:space:]]*$'; then
        block "rm -rf . or rm -rf * at cwd — would wipe project root"
    fi
fi

# 2. git push --force to protected branches
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+push'; then
    if printf '%s' "$CMD" | grep -qE 'push.*(--force([^-]|$)|--force-with-lease|[[:space:]]-f([[:space:]]|$))'; then
        if printf '%s' "$CMD" | grep -qE '(main|master|production|prod|release/)'; then
            block "git push --force to a protected branch (main/master/production/release/*)"
        fi
        # Force push without a branch arg = push current; refuse unless ACKed
        if ! printf '%s' "$CMD" | grep -qE 'push.*(origin|upstream)[[:space:]]+[a-zA-Z0-9_/-]+'; then
            block "git push --force without explicit non-protected branch arg"
        fi
    fi
fi

# 3. sudo rm of system dirs, mkfs, dd to a block device
if printf '%s' "$CMD" | grep -qE 'sudo[[:space:]]+rm.*(-rf|-fr).*(/|/etc|/var|/opt|/usr)'; then
    block "sudo rm -rf of a system directory"
fi
if printf '%s' "$CMD" | grep -qE '(^|[^a-z])mkfs(\.|[[:space:]])'; then
    block "mkfs — filesystem format"
fi
if printf '%s' "$CMD" | grep -qE 'dd[[:space:]]+.*of=/dev/'; then
    block "dd writing to a block device"
fi

# 4. Production DB destruction
if printf '%s' "$CMD" | grep -qE 'supabase[[:space:]]+db[[:space:]]+reset.*--linked'; then
    block "supabase db reset --linked would wipe production data. Use a local/dev DB."
fi
if printf '%s' "$CMD" | grep -qiE '(dropdb|drop[[:space:]]+database).*(prod|production|live)'; then
    block "Dropping a production database"
fi

exit 0
