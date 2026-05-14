"""tools/audit_dataset_status.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_status_histograms(tmp_path: Path) -> None:
    rows = [
        {"Id": "1", "StatusName": "Действующее", "TypeName": "А"},
        {"Id": "2", "StatusName": "Недействующее", "TypeName": "А"},
        {"Id": "3", "StatusName": None},
    ]
    inp = tmp_path / "in.jsonl"
    inp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_status.py"),
            str(inp),
            "-o",
            str(outp),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["certificate_lines_total"] == 3
    assert data["histograms"]["StatusName"]["Действующее"] == 1
    assert data["histograms"]["StatusName"]["Недействующее"] == 1
    assert data["histograms"]["StatusName"]["<null>"] == 1
    assert data["histograms"]["TypeName"]["А"] == 2


def test_audit_status_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_dataset_status.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "StatusName" in r.stdout
