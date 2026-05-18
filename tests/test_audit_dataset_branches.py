"""tools/audit_dataset_branches.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from tools.audit_dataset_branches import (  # noqa: E402
    audit_certificate_row,
    build_branch_hit_record,
    is_branch_supplement_by_diff_aeo_id,
    is_same_entity_supplement_by_aeo_id,
    iter_branch_supplements,
)


def test_rule_diff_aeo_id_unit() -> None:
    root = {"Id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeaaaa"}
    same = {"Id": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEAAAA"}
    branch = {"Id": "bbbbbbbb-cccc-dddd-eeee-ffffffffbbbb"}
    assert is_branch_supplement_by_diff_aeo_id(root, same) is False
    assert is_same_entity_supplement_by_aeo_id(root, same) is True
    assert is_branch_supplement_by_diff_aeo_id(root, branch) is True
    assert is_branch_supplement_by_diff_aeo_id(root, {"Id": ""}) is False
    assert is_branch_supplement_by_diff_aeo_id(root, {}) is False


def test_audit_certificate_row_counts() -> None:
    row = {
        "Id": "cert-1",
        "ActualEducationOrganization": {"Id": "root-id"},
        "Supplements": [
            {"ActualEducationOrganization": {"Id": "root-id"}},
            {"ActualEducationOrganization": {"Id": "branch-id"}},
            {"ActualEducationOrganization": {}},
        ],
    }
    per = audit_certificate_row(row)
    assert per["branch_by_diff_aeo_id"] == 1
    assert per["same_aeo_id_as_root"] == 1
    assert per["incomparable_aeo_id"] == 1
    assert per["has_any_branch"] is True
    hits = list(iter_branch_supplements(row))
    assert len(hits) == 1
    assert hits[0][0] == 1


def test_audit_branches_cli_on_fixture(tmp_path: Path) -> None:
    src = ROOT / "tests" / "fixtures" / "branch_supplement_aeo_inn_gap_minimal.jsonl"
    outp = tmp_path / "audit.json"
    branch_out = tmp_path / "branches.jsonl"
    prob_out = tmp_path / "problem.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_branches.py"),
            str(src),
            "-o",
            str(outp),
            "--limit",
            "10",
            "-b",
            str(branch_out),
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
    assert data["certificate_lines_total"] == 2
    assert data["certificates_with_any_branch_by_rule_1"] == 1
    assert data["supplement_aeo_branch_by_diff_Id_rule_1"] == 1
    assert data["supplement_aeo_same_Id_as_root"] == 1
    branch_lines = [ln for ln in branch_out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(branch_lines) == 1
    rec = json.loads(branch_lines[0])
    assert rec["record_kind"] == "branch_supplement_diff_aeo_id_v1"
    assert rec["rule_id"] == "diff_aeo_id"
    assert rec["certificate_id"] == "cert-gap-1"
    prob_lines = [ln for ln in prob_out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(prob_lines) == 1
    assert json.loads(prob_lines[0])["Id"] == "cert-gap-1"


def test_build_branch_hit_record() -> None:
    row = {
        "Id": "c",
        "EduOrgFullName": "Head",
        "ActualEducationOrganization": {"Id": "r", "INN": "1"},
        "Supplements": [{"Number": "2", "ActualEducationOrganization": {"Id": "s"}}],
    }
    sup = row["Supplements"][0]
    rec = build_branch_hit_record(
        row,
        supplement_index=0,
        sup=sup,
        root_aeo=row["ActualEducationOrganization"],
        sup_aeo=sup["ActualEducationOrganization"],
    )
    assert rec["root_aeo_id"] == "r"
    assert rec["supplement_aeo_id"] == "s"
    assert rec["supplement_meta"]["Number"] == "2"


def test_audit_branches_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_dataset_branches.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "diff_aeo_id" in r.stdout or "филиал" in r.stdout
