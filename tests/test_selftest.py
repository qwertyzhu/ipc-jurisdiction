"""CI wrapper: the engine's --selftest is the source of truth."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jurisdiction.py"


def test_selftest_passes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "passed" in result.stdout
    assert "FAIL" not in result.stdout
