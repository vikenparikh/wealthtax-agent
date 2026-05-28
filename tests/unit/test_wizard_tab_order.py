"""P2-AC12 — wizard tab/field order is enforced by ``scripts/check_tab_order.sh``.

The script reads ``intake/wizard.py``'s ``WIZARD_STEPS`` and verifies the steps
appear in logical DOM order (jurisdiction → residency → income → deductions →
review). Exits 0 when in order, 1 with a diff when not.

We exercise both paths here so the contract is testable from pytest, not just
from a manual invocation.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_tab_order.sh"


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/check_tab_order.sh must be executable"


def test_passes_against_current_wizard() -> None:
    """Real wizard.py — must already be in correct order."""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_tab_order.sh failed against current wizard.py:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def _write_fake_wizard(tmp_path: Path, steps: list[str]) -> Path:
    target = tmp_path / "src" / "wealthtax_agent" / "intake" / "wizard.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "from typing import List\n\nWIZARD_STEPS: List[str] = [\n"
    body += "".join(f'    "{s}",\n' for s in steps)
    body += "]\n"
    target.write_text(body)
    return target


def test_fails_when_steps_swapped(tmp_path: Path) -> None:
    """Swapping income before residency must trigger exit 1 with a clear diff."""
    fake = _write_fake_wizard(
        tmp_path,
        [
            "jurisdiction_year",
            "income_sources",      # out of place
            "residency_days",      # should be step 2
            "deductions_credits",
            "review_submit",
        ],
    )
    env = {**os.environ, "WIZARD_FILE": str(fake)}
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "FAIL" in result.stderr
    assert "residency_days" in result.stderr
    assert "income_sources" in result.stderr


def test_fails_when_review_not_last(tmp_path: Path) -> None:
    """Review must be the final step — anything else is a violation."""
    fake = _write_fake_wizard(
        tmp_path,
        [
            "jurisdiction_year",
            "residency_days",
            "income_sources",
            "review_submit",        # moved before deductions — wrong
            "deductions_credits",
        ],
    )
    env = {**os.environ, "WIZARD_FILE": str(fake)}
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "FAIL" in result.stderr


def test_fails_on_count_mismatch(tmp_path: Path) -> None:
    """Adding or removing a step is also a contract violation."""
    fake = _write_fake_wizard(
        tmp_path,
        [
            "jurisdiction_year",
            "residency_days",
            "income_sources",
            # missing deductions_credits + review_submit
        ],
    )
    env = {**os.environ, "WIZARD_FILE": str(fake)}
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "FAIL" in result.stderr
    assert "3 entries, expected 5" in result.stderr


def test_fails_when_wizard_file_missing(tmp_path: Path) -> None:
    """Pointed at a non-existent file → exit 1, clear error message."""
    env = {**os.environ, "WIZARD_FILE": str(tmp_path / "does_not_exist.py")}
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "cannot find" in result.stderr.lower()


def test_runs_without_bash_strict_failures() -> None:
    """``set -euo pipefail`` should not trip on the happy path."""
    # Re-run the real wizard and inspect stderr — must be empty on success.
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == "", f"unexpected stderr on happy path: {result.stderr!r}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_uses_bash_shebang() -> None:
    """Portable shebang — must be ``#!/usr/bin/env bash``, not ``#!/bin/sh``."""
    first_line = SCRIPT.read_text().splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", (
        f"script must use 'env bash' shebang for portability; got {first_line!r}"
    )
