"""tools/scan_jsonl_placeholder_scalars.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scan_finds_zero_and_dash(tmp_path: Path) -> None:
    row = {
        "Id": "x",
        "RegNumber": "0",
        "PostAddress": "—",
        "Supplements": [
            {
                "Id": "s1",
                "EducationalPrograms": [
                    {"Id": "p1", "Qualification": "0", "ProgrammName": "00"},
                ],
            }
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "scan_jsonl_placeholder_scalars.py"),
            str(inp),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    body = r.stdout.strip().splitlines()
    assert any("only_zeros" in ln and "Qualification" in ln for ln in body)
    assert any("only_zeros" in ln and "RegNumber" in ln for ln in body)
    assert any("dash_only" in ln and "PostAddress" in ln for ln in body)
    assert any("only_zeros" in ln and "ProgrammName" in ln and "00" in ln for ln in body)


def test_classify_unit() -> None:
    import importlib.util

    path = ROOT / "tools" / "scan_jsonl_placeholder_scalars.py"
    spec = importlib.util.spec_from_file_location("scan_ph", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cl = mod.classify_placeholder

    assert cl("0") == "only_zeros"
    assert cl("000") == "only_zeros"
    assert cl("-") == "dash_only"
    assert cl("Н/Д") == "empty_marker"
    assert cl("Бакалавр") is None
    assert cl("01") is None
