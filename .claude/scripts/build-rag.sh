#!/bin/bash
# Search fallback for when INDEX.md + KG don't route the question.
#
# No embeddings, no Ollama, no model files. Just:
#   1. Build a one-page file listing (paths + first H1 + frontmatter)
#   2. Query: grep the listing for keywords, then hand the matching files
#      and the question to `claude -p` for reasoning
#
# Why not embeddings? — we're already using `claude` for everything else;
# a local embedding daemon adds infra without paying for itself at our repo sizes.
# The KG + INDEX give us deterministic routing; this layer is the soft-search fallback.
#
# Usage:
#   bash .claude/scripts/build-rag.sh build                  # build the file listing
#   bash .claude/scripts/build-rag.sh query "how does X work?"
#   bash .claude/scripts/build-rag.sh status
#   bash .claude/scripts/build-rag.sh clean

set -euo pipefail

REPO_ROOT="$(pwd)"
RAG_DIR="$REPO_ROOT/.claude/rag"
LISTING="$RAG_DIR/listing.txt"

CMD="${1:-help}"; shift || true

ensure_claude() {
    if ! command -v claude >/dev/null 2>&1; then
        echo "ERROR: 'claude' CLI not on PATH. Install Claude Code first." >&2
        exit 1
    fi
}

case "$CMD" in
    build)
        mkdir -p "$RAG_DIR"
        echo "Scanning files..."

        # Wildcard-prefixed excludes catch nested copies (e.g. dashboard/node_modules).
        # Pull all candidate files first.
        find . -type f \( -name '*.md' -o -name '*.py' -o -name '*.ts' -o -name '*.tsx' \
            -o -name '*.js' -o -name '*.jsx' -o -name '*.go' -o -name '*.rs' \
            -o -name '*.sh' -o -name '*.yaml' -o -name '*.yml' -o -name '*.toml' \) \
            -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/.next/*' \
            -not -path '*/dist/*' -not -path '*/build/*' -not -path '*/__pycache__/*' \
            -not -path '*/.venv/*' -not -path '*/venv/*' -not -path '*/vendor/*' \
            -not -path './.claude/*' \
            -not -path '*/data/*' -not -path '*/datasets/*' -not -path '*/models/*' \
            -not -path '*/logs/*' -not -path '*/.pytest_cache/*' -not -path '*/.ruff_cache/*' \
            -not -path '*/worktrees/*' -not -path '*/target/*' \
            -not -path '*/.playwright-mcp/*' \
            -not -path '*/forks/*' -not -path './.venv-*' -not -path '*/.venv-*/*' \
            -not -path '*/site-packages/*' -not -path '*/.tox/*' -not -path '*/coverage/*' \
            > "$RAG_DIR/files.txt"

        N=$(wc -l < "$RAG_DIR/files.txt" | tr -d ' ')
        echo "Building listing for $N files..."

        # For each file, capture: path | first H1 (or first non-blank line) | frontmatter tags
        python3 <<'PYEOF' > "$LISTING"
import os, re, sys

files_path = ".claude/rag/files.txt"
with open(files_path) as f:
    files = [l.strip() for l in f if l.strip()]

def first_h1(text):
    for line in text.splitlines()[:40]:
        if line.startswith("# "):
            return line[2:].strip()
    return ""

def first_nonblank(text):
    for line in text.splitlines()[:40]:
        s = line.strip()
        if s and not s.startswith(("#!", "//", "/*", "*", "<!--", '"""', "'''")):
            return s[:120]
    return ""

def frontmatter_tags(text):
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    fm = text[4:end]
    m = re.search(r'^tags:\s*\[(.*?)\]', fm, re.MULTILINE)
    return m.group(1).strip() if m else ""

for p in files:
    try:
        if os.path.getsize(p) > 500_000:
            continue
        with open(p, errors="ignore") as fh:
            text = fh.read(8000)
    except Exception:
        continue
    title = first_h1(text) or first_nonblank(text)
    tags = frontmatter_tags(text)
    line = p
    if title:
        line += f" | {title}"
    if tags:
        line += f" | [{tags}]"
    print(line)
PYEOF

        L=$(wc -l < "$LISTING" | tr -d ' ')
        cat > "$RAG_DIR/manifest.json" <<EOF
{"backend": "grep+claude", "n_files": $N, "n_indexed": $L, "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
EOF
        echo "Indexed $L files (of $N candidates) into $LISTING"
        ;;

    query)
        ensure_claude
        Q="${1:-}"
        [ -z "$Q" ] && { echo "usage: $0 query '<question>'" >&2; exit 1; }
        [ -f "$LISTING" ] || { echo "Not built. Run: $0 build" >&2; exit 1; }

        # Extract candidate keywords from question (longer than 3 chars, not stopwords)
        KEYWORDS=$(python3 -c "
import re
stop = set('the a an is are was were be been being do does did has have had it its this that they them with for from into about where what when which how why who'.split())
q = '''$Q'''
# Split CamelCase / snake_case into parts so 'RiskChain' yields 'Risk' + 'Chain'
words = re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,}', q)
parts = []
for w in words:
    parts.append(w)
    # CamelCase split: RiskChain -> Risk, Chain
    splits = re.findall(r'[A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z])|[a-z]+', w)
    parts.extend(s for s in splits if len(s) >= 3 and s.lower() != w.lower())
kept = [p for p in set(parts) if p.lower() not in stop and len(p) >= 3]
print('|'.join(kept))
")
        if [ -z "$KEYWORDS" ]; then
            echo "No keywords extracted; falling back to whole listing." >&2
            CANDIDATES="$(cat "$LISTING")"
        else
            CANDIDATES="$(grep -iE "$KEYWORDS" "$LISTING" | head -40 || true)"
            if [ -z "$CANDIDATES" ]; then
                # No keyword hit — pass top 40 of the listing as context
                CANDIDATES="$(head -40 "$LISTING")"
                echo "(no keyword match; passing top 40 of listing to Claude)" >&2
            fi
        fi

        # Hand the listing + question to claude -p for reasoning
        PROMPT="You are answering a search query against a repository. The user's question is:

$Q

Below is a candidate listing of files (path | one-line summary | tags) that might be relevant. Pick the 3-5 most relevant files. Briefly explain why each is a match. Output as a ranked list with format: \`<rank>. \<path\> — <why>\`. Do not invent paths.

Listing:
$CANDIDATES"
        claude -p "$PROMPT"
        ;;

    status)
        if [ -f "$RAG_DIR/manifest.json" ]; then
            cat "$RAG_DIR/manifest.json"
        else
            echo "Not built. Run: bash .claude/scripts/build-rag.sh build"
        fi
        ;;

    clean)
        rm -rf "$RAG_DIR"
        echo "Cleaned $RAG_DIR"
        ;;

    help|*)
        head -n 20 "$0" | grep '^#' | sed 's/^# //'
        ;;
esac
