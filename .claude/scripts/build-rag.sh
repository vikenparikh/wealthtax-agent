#!/bin/bash
# Local embedded-RAG fallback for when INDEX.md doesn't route the question.
#
# Uses Ollama for embeddings (default model: nomic-embed-text) + a flat
# numpy file for the store. Zero hosted cost.
#
# Usage:
#   bash .claude/scripts/build-rag.sh build              # index this repo
#   bash .claude/scripts/build-rag.sh query "how does X work?"
#   bash .claude/scripts/build-rag.sh status
#   bash .claude/scripts/build-rag.sh clean
#
# Indexes:
#   - all .md files
#   - top of each source file (first 80 lines) — enough for module headers / imports
# Skips: node_modules, .git, .next, dist, build, __pycache__, vendor, .venv, venv
#
# Storage: .claude/rag/{embeddings.npy, chunks.jsonl, manifest.json}

set -euo pipefail

REPO_ROOT="$(pwd)"
RAG_DIR="$REPO_ROOT/.claude/rag"
EMBED_MODEL="${RAG_EMBED_MODEL:-nomic-embed-text}"

CMD="${1:-help}"; shift || true

ensure_ollama() {
    if ! command -v ollama >/dev/null 2>&1; then
        echo "ERROR: ollama not installed. brew install ollama (mac) or https://ollama.com/install" >&2
        exit 1
    fi
    if ! curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "ERROR: ollama daemon not running. Start it: 'ollama serve' (in another terminal)" >&2
        exit 1
    fi
    if ! ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -q "^${EMBED_MODEL}"; then
        echo "Pulling embedding model: $EMBED_MODEL"
        ollama pull "$EMBED_MODEL"
    fi
}

ensure_python_deps() {
    python3 -c "import numpy" 2>/dev/null || python3 -m pip install --quiet --user numpy
}

case "$CMD" in
    build)
        ensure_ollama
        ensure_python_deps
        mkdir -p "$RAG_DIR"
        echo "Scanning files..."
        FILES_LIST="$RAG_DIR/files.txt"
        # Exclude .claude/ entirely — it carries symlinks into root vendored
        # skill packs (~27k files). Only index repo-owned content.
        # Also skip data/parquet artifacts, model checkpoints, logs.
        # Wildcard-prefixed excludes catch nested copies (e.g. dashboard/node_modules).
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
            > "$FILES_LIST"
        N=$(wc -l < "$FILES_LIST" | tr -d ' ')
        echo "Embedding $N files via $EMBED_MODEL..."

        python3 <<PYEOF
import json, os, subprocess, sys, urllib.request
import numpy as np

REPO = "$REPO_ROOT"
RAG = "$RAG_DIR"
MODEL = "$EMBED_MODEL"

def embed(text: str) -> list[float]:
    payload = json.dumps({"model": MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/embeddings",
        data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["embedding"]

chunks, embs = [], []
with open(os.path.join(RAG, "files.txt")) as f:
    files = [l.strip() for l in f if l.strip()]

for i, path in enumerate(files, 1):
    try:
        if os.path.getsize(path) > 200_000:
            continue  # skip oversize — nomic-embed-text caps at ~8K tokens
        with open(path, errors="ignore") as fh:
            content = fh.read()
    except Exception:
        continue
    if not content.strip():
        continue
    # For markdown, embed whole file (if <8 KB) else head + first section.
    # For code, embed first 80 lines as the "module header".
    if path.endswith(".md"):
        body = content[:8000]
    else:
        body = "\n".join(content.splitlines()[:80])
    if len(body) < 50:
        continue
    try:
        e = embed(body)
    except Exception as ex:
        print(f"  skip {path}: {ex}", file=sys.stderr)
        continue
    chunks.append({"path": path, "preview": body[:300]})
    embs.append(e)
    if i % 25 == 0:
        print(f"  {i}/{len(files)}")

if not embs:
    print("No chunks indexed.", file=sys.stderr); sys.exit(1)

arr = np.array(embs, dtype=np.float32)
arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
np.save(os.path.join(RAG, "embeddings.npy"), arr)
with open(os.path.join(RAG, "chunks.jsonl"), "w") as out:
    for c in chunks: out.write(json.dumps(c) + "\n")
with open(os.path.join(RAG, "manifest.json"), "w") as out:
    json.dump({"model": MODEL, "n": len(chunks), "dim": int(arr.shape[1])}, out, indent=2)
print(f"Indexed {len(chunks)} chunks, dim={arr.shape[1]}")
PYEOF
        ;;

    query)
        Q="${1:-}"
        [ -z "$Q" ] && { echo "usage: $0 query '<question>'" >&2; exit 1; }
        ensure_ollama
        ensure_python_deps
        [ -f "$RAG_DIR/embeddings.npy" ] || { echo "RAG not built. Run: $0 build" >&2; exit 1; }
        K="${RAG_TOP_K:-8}"
        python3 <<PYEOF
import json, os, urllib.request
import numpy as np

RAG = "$RAG_DIR"
MODEL = json.load(open(os.path.join(RAG, "manifest.json")))["model"]
Q = """$Q"""
K = $K

def embed(text):
    payload = json.dumps({"model": MODEL, "prompt": text}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/embeddings",
        data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["embedding"]

q = np.array(embed(Q), dtype=np.float32)
q /= np.linalg.norm(q) + 1e-12
M = np.load(os.path.join(RAG, "embeddings.npy"))
scores = M @ q
top = np.argsort(-scores)[:K]
with open(os.path.join(RAG, "chunks.jsonl")) as f:
    chunks = [json.loads(l) for l in f]
print(f"Top {K} for: {Q!r}\n")
for r, i in enumerate(top, 1):
    print(f"{r}. {scores[i]:.3f}  {chunks[i]['path']}")
PYEOF
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
