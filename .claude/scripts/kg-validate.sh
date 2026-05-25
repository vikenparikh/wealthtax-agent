#!/bin/bash
# Validate the knowledge graph at .claude/kg/.
#
# Checks:
#   1. Every concept file has frontmatter with `concept:` matching the filename.
#   2. Every `related:` link resolves to an existing concept.
#   3. Every `files:` path exists (warn — files can be moved during refactor).
#   4. `index.md` lists every non-archived concept (no orphans).
#
# Exit code: 0 if clean, 1 if errors, 2 if warnings only.

set -uo pipefail

KG="${1:-.claude/kg}"
[ -d "$KG" ] || { echo "no $KG dir — run knowledge-graph skill first"; exit 0; }
[ -d "$KG/concepts" ] || { mkdir -p "$KG/concepts"; }

errors=0
warns=0

# Helper: extract frontmatter field
fm_field() {
    awk -v key="$2" '
        /^---$/ { count++; if (count==2) exit; next }
        count==1 {
            split($0, a, ":")
            if (a[1] == key) { sub("^[^:]*:[[:space:]]*", ""); print; exit }
        }' "$1"
}

# 1. Validate each concept
for f in "$KG"/concepts/*.md; do
    [ -f "$f" ] || continue
    base="$(basename "$f" .md)"
    [ "$base" = "_archived" ] && continue
    fm="$(fm_field "$f" "concept")"
    if [ -z "$fm" ]; then
        echo "ERROR: $f missing frontmatter 'concept:' field"
        errors=$((errors+1))
    elif [ "$fm" != "$base" ]; then
        echo "ERROR: $f has concept:$fm but filename is $base.md"
        errors=$((errors+1))
    fi
done

# 2. Related links resolve
for f in "$KG"/concepts/*.md; do
    [ -f "$f" ] || continue
    related="$(fm_field "$f" "related")"
    # related is bracketed list like [a, b, c]
    related="${related//[\[\]]/}"
    IFS=',' read -ra arr <<< "$related"
    for r in "${arr[@]}"; do
        r="$(echo "$r" | xargs)"  # trim
        [ -z "$r" ] && continue
        if [ ! -f "$KG/concepts/$r.md" ]; then
            echo "ERROR: $f references missing concept: $r"
            errors=$((errors+1))
        fi
    done
done

# 3. Files referenced still exist
for f in "$KG"/concepts/*.md; do
    [ -f "$f" ] || continue
    files="$(fm_field "$f" "files")"
    files="${files//[\[\]]/}"
    IFS=',' read -ra arr <<< "$files"
    for p in "${arr[@]}"; do
        p="$(echo "$p" | xargs)"
        [ -z "$p" ] && continue
        if [ ! -e "$p" ]; then
            echo "WARN: $f references missing file: $p"
            warns=$((warns+1))
        fi
    done
done

# 4. Index lists every concept
if [ -f "$KG/index.md" ]; then
    for f in "$KG"/concepts/*.md; do
        [ -f "$f" ] || continue
        base="$(basename "$f" .md)"
        if ! grep -q "$base" "$KG/index.md"; then
            echo "WARN: $base not listed in $KG/index.md"
            warns=$((warns+1))
        fi
    done
else
    echo "WARN: $KG/index.md missing — graph has no entry point"
    warns=$((warns+1))
fi

echo
echo "Validation: $errors error(s), $warns warning(s)"
[ "$errors" -gt 0 ] && exit 1
[ "$warns" -gt 0 ] && exit 2
exit 0
