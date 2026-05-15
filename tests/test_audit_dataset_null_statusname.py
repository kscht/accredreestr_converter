"""tools/audit_dataset_null_statusname.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_null_statusname_counts_and_examples(tmp_path: Path) -> None:
    rows = [
        {"Id": "a", "StatusName": "Действующее"},
        {"Id": "b"},  # missing StatusName
        {"Id": "c", "StatusName": None},
        {"Id": "d", "StatusName": "  "},
        {
            "Id": "e",
            "StatusName": "Действующее",
            "Supplements": [
                {"Number": "1"},
                {"StatusName": None, "Number": "2"},
            ],
        },
    ]
    inp = tmp_path / "in.jsonl"
    inp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    full_out = tmp_path / "root_null.jsonl"
    prob_out = tmp_path / "problem.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_null_statusname.py"),
            str(inp),
            "-o",
            str(outp),
            "--limit",
            "50",
            "-f",
            str(full_out),
            "-p",
            str(prob_out),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["certificate_lines_total"] == 5
    assert data["root_StatusName_nullish_lines"] == 3
    assert data["root_StatusName_nullish_by_kind"]["missing"] == 1
    assert data["root_StatusName_nullish_by_kind"]["json_null"] == 1
    assert data["root_StatusName_nullish_by_kind"]["empty_string"] == 1
    assert data["supplement_StatusName_nullish_hits"] == 2
    assert data["certificate_lines_with_any_supplement_StatusName_nullish"] == 1
    assert data["certificate_lines_with_StatusName_nullish_root_or_supplement_union"] == 4
    assert data["problem_jsonl_output"] == str(prob_out.resolve())

    ids_root = {ex["certificate_id"] for ex in data["examples_root_StatusName_nullish"]}
    assert ids_root == {"b", "c", "d"}

    full_lines = [ln for ln in full_out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(full_lines) == 3
    parsed = [json.loads(ln) for ln in full_lines]
    assert {p["Id"] for p in parsed} == {"b", "c", "d"}

    prob_lines = [ln for ln in prob_out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(prob_lines) == 4
    prob_ids = {json.loads(ln)["Id"] for ln in prob_lines}
    assert prob_ids == {"b", "c", "d", "e"}


def test_audit_null_statusname_limit_zero(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"Id": "x"}, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_null_statusname.py"),
            str(inp),
            "-o",
            str(outp),
            "--limit",
            "0",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["root_StatusName_nullish_lines"] == 1
    assert data["certificate_lines_with_StatusName_nullish_root_or_supplement_union"] == 1
    assert data["problem_jsonl_output"] is None
    assert data["examples_root_StatusName_nullish"] == []
    assert data["examples_supplement_StatusName_nullish"] == []


def test_audit_null_statusname_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_dataset_null_statusname.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "StatusName" in r.stdout
    assert "problem-jsonl" in r.stdout
    assert "certificate_lines_StatusName_nullish.jsonl" in r.stdout
