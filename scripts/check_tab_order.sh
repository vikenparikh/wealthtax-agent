#!/usr/bin/env bash
# P2-AC12 — verify the 5-step intake wizard fields appear in logical DOM order
# inside intake/wizard.py:
#   1. jurisdiction(_year) before residency(_days)
#   2. residency before income(_sources)
#   3. income before deductions(_credits)
#   4. deductions before review(_submit)
#
# Reads the canonical WIZARD_STEPS list. Exits 0 when in order, exits 1 with a
# diff describing the violation when out of sequence.

set -euo pipefail

WIZARD_FILE="${WIZARD_FILE:-src/wealthtax_agent/intake/wizard.py}"

if [[ ! -f "$WIZARD_FILE" ]]; then
    echo "ERROR: cannot find wizard file at: $WIZARD_FILE" >&2
    exit 1
fi

# Expected logical order — DOM-natural progression through the form.
EXPECTED=(
    "jurisdiction_year"
    "residency_days"
    "income_sources"
    "deductions_credits"
    "review_submit"
)

# Extract the raw step identifiers in declaration order from WIZARD_STEPS.
# Strategy: grab the block between `WIZARD_STEPS` and the closing `]`, then
# pull every quoted string from it. This avoids relying on grep -P (BSD grep
# on macOS does not support it) and survives reordering or trailing comments.
ACTUAL_RAW=$(awk '
    /^WIZARD_STEPS/ { capturing = 1; next }
    capturing && /^\]/ { capturing = 0 }
    capturing { print }
' "$WIZARD_FILE" | grep -oE '"[a-z_]+"' | tr -d '"')

if [[ -z "$ACTUAL_RAW" ]]; then
    echo "ERROR: could not extract WIZARD_STEPS entries from $WIZARD_FILE" >&2
    exit 1
fi

# Read into a bash array.
ACTUAL=()
while IFS= read -r line; do
    ACTUAL+=("$line")
done <<<"$ACTUAL_RAW"

# Length check — bail early with a clear diff if the count is wrong.
if [[ ${#ACTUAL[@]} -ne ${#EXPECTED[@]} ]]; then
    echo "FAIL: WIZARD_STEPS has ${#ACTUAL[@]} entries, expected ${#EXPECTED[@]}" >&2
    echo "--- expected" >&2
    printf '  %s\n' "${EXPECTED[@]}" >&2
    echo "+++ actual" >&2
    printf '  %s\n' "${ACTUAL[@]}" >&2
    exit 1
fi

# Pairwise comparison — report the *first* mismatch as a unified-style diff so
# the operator sees exactly which step is out of sequence.
violations=0
for i in "${!EXPECTED[@]}"; do
    if [[ "${ACTUAL[$i]}" != "${EXPECTED[$i]}" ]]; then
        if (( violations == 0 )); then
            echo "FAIL: wizard tab order violation in $WIZARD_FILE" >&2
            echo "--- expected" >&2
            printf '  %s\n' "${EXPECTED[@]}" >&2
            echo "+++ actual" >&2
            printf '  %s\n' "${ACTUAL[@]}" >&2
        fi
        echo "  step $((i + 1)): expected '${EXPECTED[$i]}', got '${ACTUAL[$i]}'" >&2
        violations=$((violations + 1))
    fi
done

if (( violations > 0 )); then
    exit 1
fi

echo "OK: wizard tab order matches expected DOM sequence (${#EXPECTED[@]} steps)"
exit 0
