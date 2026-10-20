"""Keep the bilingual work-item records consistent."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_work_items_and_index_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_docs.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
