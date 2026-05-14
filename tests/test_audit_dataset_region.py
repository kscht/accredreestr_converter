"""tools/audit_dataset_region.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_OUTSIDE = (
    "образовательные учреждения, находящиеся за пределами Российской Федерации"
)


def test_audit_region_outside_rf_and_hist(tmp_path: Path) -> None:
    rows = [
        {"Id": "1", "RegionName": "Москва"},
        {"Id": "2", "RegionName": _OUTSIDE},
        {"Id": "3"},
    ]
    inp = tmp_path / "in.jsonl"
    inp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_region.py"),
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
    assert data["outside_rf_pseudo_region"] == 1
    assert data["histograms"]["RegionName"][_OUTSIDE] == 1
    assert data["histograms"]["RegionName"]["Москва"] == 1
    assert data["histograms"]["RegionName"]["<null>"] == 1


def test_audit_region_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_dataset_region.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "RegionName" in r.stdout
