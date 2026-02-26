from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_verify_arch_sync_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_arch_sync.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
