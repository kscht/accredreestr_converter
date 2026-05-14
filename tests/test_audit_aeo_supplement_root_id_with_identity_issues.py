"""tools/audit_aeo_supplement_root_id_with_identity_issues.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(inp: Path, outp: Path) -> dict:
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_aeo_supplement_root_id_with_identity_issues.py"),
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
    return json.loads(outp.read_text(encoding="utf-8"))


def test_issue_cert_classifies_supplement_aeo_ids(tmp_path: Path) -> None:
    """Строка с проблемой EduOrgINN; два приложения — same и different Id AEO."""
    row = {
        "Id": "cert-1",
        "EduOrgINN": "",
        "EduOrgOGRN": "1027700132195",
        "ActualEducationOrganization": {"Id": "root-aeo", "INN": "7700000000", "OGRN": "1027700132195"},
        "Supplements": [
            {
                "ActualEducationOrganization": {
                    "Id": "root-aeo",
                    "INN": "7700000000",
                    "OGRN": "1027700132195",
                }
            },
            {
                "ActualEducationOrganization": {
                    "Id": "other-aeo",
                    "INN": "7700000001",
                    "OGRN": "1027700132196",
                }
            },
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.json"
    data = _run(inp, outp)
    assert data["certificates_with_any_identity_issue"] == 1
    b = data["when_certificate_has_identity_issue_supplement_aeo_dict_cards"]
    assert b["total_cards"] == 2
    assert b["same_ActualEducationOrganization_Id_as_root"] == 1
    assert b["different_ActualEducationOrganization_Id_from_root"] == 1
    assert b["incomparable_Id_missing_on_root_or_supplement_aeo"] == 0


def test_no_issue_cert_not_counted(tmp_path: Path) -> None:
    row = {
        "Id": "clean",
        "EduOrgINN": "7700000000",
        "EduOrgOGRN": "1027700132195",
        "ActualEducationOrganization": {"Id": "a", "INN": "7700000000", "OGRN": "1027700132195"},
        "Supplements": [
            {"ActualEducationOrganization": {"Id": "b", "INN": "7700000001", "OGRN": "1027700132196"}},
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.json"
    data = _run(inp, outp)
    assert data["certificates_with_any_identity_issue"] == 0
    assert (
        data["when_certificate_has_identity_issue_supplement_aeo_dict_cards"][
            "total_cards"
        ]
        == 0
    )


def test_inn_ogrn_issue_subset_and_case_insensitive_id(tmp_path: Path) -> None:
    row = {
        "Id": "c2",
        "EduOrgINN": "7700000000",
        "EduOrgOGRN": "1027700132195",
        "ActualEducationOrganization": {
            "Id": "AAAA1111-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
            "INN": "7700000000",
            "OGRN": "1027700132195",
        },
        "Supplements": [
            {
                "ActualEducationOrganization": {
                    "Id": "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "INN": "",
                    "OGRN": "1027700132195",
                }
            },
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.json"
    data = _run(inp, outp)
    sub = data["when_certificate_has_identity_issue_and_supplement_aeo_has_inn_or_ogrn_issue"]
    assert sub["total_cards"] == 1
    assert sub["same_ActualEducationOrganization_Id_as_root"] == 1


def test_help() -> None:
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_aeo_supplement_root_id_with_identity_issues.py"),
            "--help",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "Id" in r.stdout
