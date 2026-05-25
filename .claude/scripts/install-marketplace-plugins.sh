#!/bin/bash
# Install the curated set of official Claude Code marketplace plugins.
#
# These are the OFFICIAL plugins from https://claude.com/plugins, installed via
# `claude plugin install <slug>@claude-plugins-official`. They are SEPARATE from
# the wshobson community plugins symlinked into .claude/plugins/.
#
# Verified against the actual marketplace cache at:
#   ~/.claude/plugins/cache/claude-plugins-official/
#
# Idempotent — re-run any time.
#
# Customize: comment out lines for plugins you don't need.

set -euo pipefail

if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: 'claude' CLI not on PATH. Install Claude Code first." >&2
    exit 1
fi

MARKETPLACE="claude-plugins-official"

# Curated set — all 41 plugins available in the official marketplace at time of writing.
# Trim this list to suit the repo. Headline picks for our stack are at the top.
PLUGINS=(
    # === Headline / always-on ===
    superpowers           # brainstorming + subagent-driven dev + code review
    skill-creator         # write your own skills
    feature-dev           # focused feature development
    code-review           # AI code review with confidence-based filtering
    code-simplifier       # refines recently modified code
    pr-review-toolkit     # multi-faceted PR analysis
    commit-commands       # git workflow automation
    claude-code-setup     # bootstrap helpers
    ralph-loop            # autonomous "do until done" runs

    # === Memory / context ===
    remember              # persistent memory across sessions
    session-report        # session summaries
    context7              # live documentation lookup
    serena                # semantic code search

    # === LSPs (uncomment per repo language) ===
    typescript-lsp
    pyright-lsp

    # === Repo / VCS / docs ===
    github
    figma

    # === Browser / testing ===
    playwright
    chrome-devtools-mcp

    # === Security ===
    security-guidance

    # === Cloud / deploy ===
    vercel
    cloudflare
    terraform

    # === Databases / data ===
    supabase
    data-engineering
    postman

    # === API integrations ===
    # stripe                # uncomment if needed
    slack
    telegram
    linear
    atlassian

    # === Monitoring ===
    sentry
    posthog

    # === Web / content ===
    firecrawl

    # === AI / ML / agents ===
    huggingface-skills
    atomic-agents

    # === Developer / SDK tooling ===
    agent-sdk-dev
    plugin-dev
    mcp-server-dev
    hookify

    # === Design / scaffolding ===
    frontend-design
    playground
)

installed="$(claude plugin list 2>/dev/null | awk '{print $1}' || true)"

for p in "${PLUGINS[@]}"; do
    # Strip leading whitespace and trailing comments
    p="$(echo "$p" | sed 's/[[:space:]]*#.*$//' | xargs)"
    [ -z "$p" ] && continue

    if printf '%s\n' "$installed" | grep -qx "$p"; then
        printf "  ✓ %s (already installed)\n" "$p"
        continue
    fi
    printf "  → installing %s\n" "$p"
    claude plugin install "${p}@${MARKETPLACE}" 2>&1 | tail -2 || \
        echo "    (failed — check 'claude plugin list' and marketplace cache)"
done

echo
echo "═══ done ═══"
echo "Restart Claude Code if any plugin requires it."
echo "Verify: claude plugin list"
