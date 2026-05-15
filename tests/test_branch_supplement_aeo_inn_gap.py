"""tools/extract_branch_supplement_aeo_inn_gap_jsonl.py и audit_branch_supplement_aeo_inn_gap.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_extract_minimal_fixture(tmp_path: Path) -> None:
    src = ROOT / "tests" / "fixtures" / "branch_supplement_aeo_inn_gap_minimal.jsonl"
    outp = tmp_path / "gap.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_branch_supplement_aeo_inn_gap_jsonl.py"),
            str(src),
            "-o",
            str(outp),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    lines = [x for x in outp.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["record_kind"] == "branch_supplement_aeo_inn_gap_v1"
    assert rec["certificate_id"] == "cert-gap-1"
    assert rec["donor_inn_digits"] == "7700000001"
    assert rec["certificate_EduOrgFullName"] == "Организация на корне сертификата"
    assert rec["certificate_EduOrgShortName"] == "ОКС"
    assert rec["root_AEO_FullName"] == "Корневая AEO полное имя"
    assert rec["root_AEO_ShortName"] == "Корневая AEO кратко"


def test_audit_gap_jsonl(tmp_path: Path) -> None:
    src = ROOT / "tests" / "fixtures" / "branch_supplement_aeo_inn_gap_minimal.jsonl"
    gap = tmp_path / "gap.jsonl"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_branch_supplement_aeo_inn_gap_jsonl.py"),
            str(src),
            "-o",
            str(gap),
        ],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
    )
    rep = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_branch_supplement_aeo_inn_gap.py"),
            str(gap),
            "-o",
            str(rep),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["lines_total"] == 1
    assert data["lines_wrong_or_missing_record_kind"] == 0
    assert data["donor_INN_source_hint"]["root_aeo_had_digit_INN"] == 1


def test_extract_limit(tmp_path: Path) -> None:
    src = ROOT / "tests" / "fixtures" / "branch_supplement_aeo_inn_gap_minimal.jsonl"
    outp = tmp_path / "gap.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_branch_supplement_aeo_inn_gap_jsonl.py"),
            str(src),
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
    assert outp.read_text(encoding="utf-8").strip() == ""

    r2 = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_branch_supplement_aeo_inn_gap_jsonl.py"),
            str(src),
            "-o",
            str(outp),
            "--limit",
            "1",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r2.returncode == 0
    assert len([x for x in outp.read_text(encoding="utf-8").splitlines() if x.strip()]) == 1


def test_extract_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "extract_branch_supplement_aeo_inn_gap_jsonl.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "branch_supplement_aeo_inn_gap" in r.stdout
