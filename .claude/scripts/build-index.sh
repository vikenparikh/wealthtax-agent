#!/bin/bash
# Generate .claude/INDEX.md — a one-page topic graph for this repo.
#
# Strategy:
#   1. Inspect top-level dirs to infer service / module map
#   2. Scan docs/ for titled markdown files (first H1 line)
#   3. Pull h1 from README.md, ARCHITECTURE.md
#   4. List code language stats so the reader knows the surface area
#   5. Group everything under topics
#
# Output is markdown to stdout. The orchestrator writes it to .claude/INDEX.md.
# Idempotent — rebuild any time.

set -euo pipefail

REPO_ROOT="$(pwd)"
REPO_NAME="$(basename "$REPO_ROOT")"

title_of() {
    local f="$1"
    [ -f "$f" ] || { echo ""; return; }
    head -n 30 "$f" | awk '/^# / { sub(/^# +/,""); print; exit }'
}

first_para_of() {
    local f="$1"
    [ -f "$f" ] || { echo ""; return; }
    awk '/^[^#[:space:]]/ { print; exit }' "$f" | head -c 200
}

list_top_dirs() {
    find . -maxdepth 1 -mindepth 1 -type d -not -name '.*' -not -name 'node_modules' \
        -not -name '__pycache__' -not -name 'venv' -not -name '.venv' -not -name 'dist' \
        -not -name 'build' -not -name '.next' | sed 's|^\./||' | sort
}

list_docs() {
    if [ -d docs ]; then
        find docs -maxdepth 3 -name '*.md' -not -path '*/node_modules/*' 2>/dev/null | sort || true
    fi
}

count_files() {
    find . -name "$1" -not -path '*/node_modules/*' -not -path '*/.git/*' \
        -not -path '*/__pycache__/*' -not -path '*/.next/*' -not -path '*/dist/*' \
        2>/dev/null | wc -l | tr -d ' '
}

# === HEADER ===
cat <<EOF
# INDEX — $REPO_NAME

> One-page context graph. Read this BEFORE reading anything else in this repo.
> Rebuild with: \`bash .claude/scripts/build-index.sh > .claude/INDEX.md\`
>
> Generated $(date -u +%Y-%m-%dT%H:%MZ).

EOF

# === ABOUT ===
ROOT_TITLE="$(title_of README.md)"
ARCH_TITLE="$(title_of ARCHITECTURE.md)"
[ -z "$ROOT_TITLE" ] && ROOT_TITLE="$REPO_NAME"

echo "## About"
echo
echo "**$ROOT_TITLE**"
echo
ROOT_DESC="$(first_para_of README.md)"
[ -n "$ROOT_DESC" ] && echo "$ROOT_DESC" && echo

# === TOP-LEVEL MAP ===
echo "## Top-level layout"
echo
echo "| Dir | Purpose |"
echo "|-----|---------|"
for d in $(list_top_dirs); do
    purpose=""
    case "$d" in
        src|lib|app) purpose="primary source" ;;
        tests|test|__tests__|spec) purpose="test suite" ;;
        docs) purpose="docs (see Documents below)" ;;
        scripts) purpose="operational scripts" ;;
        infra|infrastructure|deploy|deployment) purpose="infra / deploy" ;;
        config|configs) purpose="config files" ;;
        data|datasets) purpose="data files" ;;
        models|model) purpose="ML model artifacts" ;;
        notebooks) purpose="jupyter notebooks" ;;
        public|static|assets) purpose="static assets" ;;
        api) purpose="API layer" ;;
        web|frontend|dashboard|ui) purpose="frontend" ;;
        backend|server) purpose="backend" ;;
        mobile|ios|android) purpose="mobile" ;;
        agents) purpose="agent definitions" ;;
        examples|example) purpose="usage examples" ;;
        bin) purpose="executables / entry points" ;;
        .claude) purpose="Claude config (this dir)" ;;
        .github) purpose="CI / workflows" ;;
        *) purpose="" ;;
    esac
    # Augment with a child-readme if present
    if [ -f "$d/README.md" ] && [ -z "$purpose" ]; then
        purpose="$(title_of "$d/README.md")"
    fi
    [ -z "$purpose" ] && purpose="—"
    printf -- "| %s | %s |\n" "[$d]($d/)" "$purpose"
done

# === DOCUMENTS ===
DOCS="$(list_docs)"
if [ -n "$DOCS" ]; then
    echo
    echo "## Documents"
    echo
    echo "| Path | Title |"
    echo "|------|-------|"
    while IFS= read -r f; do
        t="$(title_of "$f")"
        [ -z "$t" ] && t="(untitled)"
        printf -- "| %s | %s |\n" "[$f]($f)" "$t"
    done <<< "$DOCS"
fi

# === KEY FILES ===
echo
echo "## Key files at root"
echo
for f in README.md ARCHITECTURE.md CLAUDE.md CHANGELOG.md CONTRIBUTING.md Makefile docker-compose.yml Dockerfile pyproject.toml package.json requirements.txt; do
    if [ -f "$f" ]; then
        t="$(title_of "$f" 2>/dev/null || true)"
        [ -z "$t" ] && t="—"
        printf -- "- [%s](%s) — %s\n" "$f" "$f" "$t"
    fi
done

# === CODE SURFACE ===
echo
echo "## Code surface"
echo
PY=$(count_files '*.py')
TS=$(count_files '*.ts')
TSX=$(count_files '*.tsx')
JS=$(count_files '*.js')
JSX=$(count_files '*.jsx')
GO=$(count_files '*.go')
RS=$(count_files '*.rs')
SH=$(count_files '*.sh')
MD=$(count_files '*.md')
[ "$PY"  != "0" ] && echo "- Python: $PY files"
[ "$TS"  != "0" ] && echo "- TypeScript: $TS files"
[ "$TSX" != "0" ] && echo "- TSX: $TSX files"
[ "$JS"  != "0" ] && echo "- JavaScript: $JS files"
[ "$JSX" != "0" ] && echo "- JSX: $JSX files"
[ "$GO"  != "0" ] && echo "- Go: $GO files"
[ "$RS"  != "0" ] && echo "- Rust: $RS files"
[ "$SH"  != "0" ] && echo "- Shell: $SH files"
[ "$MD"  != "0" ] && echo "- Markdown: $MD files"

# === MEMORY POINTERS ===
echo
echo "## Memory pointers"
echo
echo "- Active focus: [.claude/memory-bank/activeContext.md](.claude/memory-bank/activeContext.md)"
echo "- Past sessions: [.claude/memory-bank/progress.md](.claude/memory-bank/progress.md)"
echo "- Decisions log: [.claude/memory-bank/decisions.md](.claude/memory-bank/decisions.md)"
echo "- Glossary: [.claude/memory-bank/glossary.md](.claude/memory-bank/glossary.md)"

# === RUNBOOK HINTS ===
echo
echo "## How to run things"
echo
[ -f Makefile ]            && echo "- Make targets: \`make help\` or inspect [Makefile](Makefile)"
[ -f docker-compose.yml ]  && echo "- Compose: \`docker compose up -d\` (see [docker-compose.yml](docker-compose.yml))"
[ -f package.json ]        && echo "- Node scripts: \`npm run\` (see [package.json](package.json))"
[ -f pyproject.toml ]      && echo "- Python: see [pyproject.toml](pyproject.toml)"
[ -f requirements.txt ]    && echo "- Python deps: [requirements.txt](requirements.txt)"

# === SHARED CONTENT ===
echo
echo "## Claude shared content (symlinked from root)"
echo
echo "- Hooks: [.claude/hooks/](.claude/hooks/) (block-dangerous, block-secret-commit)"
echo "- Rules: [.claude/rules/](.claude/rules/) (safety, style)"
echo "- Skills: [.claude/skills-shared/](.claude/skills-shared/) (graphify, tdd, handoff, …)"
echo "- Agents: [.claude/agents-shared/](.claude/agents-shared/)"
echo "- Plugins: [.claude/plugins/](.claude/plugins/) — 49 wshobson plugins covering python/frontend/k8s/security/ML/…"
echo
echo "Edit the root copies at \`~/Downloads/Projects/.claude/\` to update every repo at once."
