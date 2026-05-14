"""tools/audit_dataset_identity_fields.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_identity_fields_per_certificate_and_supplement(tmp_path: Path) -> None:
    c1 = {
        "Id": "c1",
        "EduOrgINN": "7700000000",
        "EduOrgOGRN": "bad-ogrn",
        "ActualEducationOrganization": {
            "Id": "shared-aeo",
            "INN": "7700000001",
            "OGRN": "1027700132195",
        },
        "Supplements": [
            {
                "ActualEducationOrganization": {
                    "Id": "shared-aeo",
                    "INN": "",
                    "OGRN": "1030000000000",
                }
            },
        ],
    }
    c2 = {"Id": "c2", "Supplements": []}
    inp = tmp_path / "in.jsonl"
    inp.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in (c1, c2)) + "\n",
        encoding="utf-8",
    )
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
            str(inp),
            "-o",
            str(outp),
            "--max-samples",
            "10",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["certificate_lines_total"] == 2

    edu_inn = data["per_certificate"]["EduOrgINN"]
    assert edu_inn["nonempty_digits_only_after_clean"] == 1
    assert edu_inn["missing_or_empty"] == 1
    assert edu_inn["would_drop_if_require_nonempty"] == 1

    edu_ogrn = data["per_certificate"]["EduOrgOGRN"]
    assert edu_ogrn["nonempty_not_digits_only_after_clean"] == 1
    assert "c1" in edu_ogrn["sample_nonempty_not_digit_only_ids"]

    root_inn = data["per_certificate"]["root_ActualEducationOrganization_INN"]
    assert root_inn["nonempty_digits_only_after_clean"] == 1
    assert root_inn["missing_or_empty"] == 1

    root_ogrn = data["per_certificate"]["root_ActualEducationOrganization_OGRN"]
    assert root_ogrn["missing_or_empty"] == 1
    assert root_ogrn["nonempty_digits_only_after_clean"] == 1

    sup = data["per_supplement_aeo_card"]
    assert sup["supplement_aeo_cards_total"] == 1
    assert sup["INN"]["missing_or_empty"] == 1
    assert sup["OGRN"]["nonempty_digits_only_after_clean"] == 1
    assert sup["INN_missing_or_empty_with_same_aeo_Id_as_root"] == 1
    assert sup["OGRN_missing_or_empty_with_same_aeo_Id_as_root"] == 0
    assert sup["INN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 1
    assert sup["OGRN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 0
    assert data["per_certificate"]["root_INN_missing_or_empty_borrowable_from_supplement_aeo_same_uid"] == 0
    assert data["per_certificate"]["root_OGRN_missing_or_empty_borrowable_from_supplement_aeo_same_uid"] == 0


def test_supplement_aeo_uid_case_insensitive_id(tmp_path: Path) -> None:
    """Совпадение ActualEducationOrganization.Id без учёта регистра UUID."""
    row = {
        "Id": "cert-1",
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
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    sup = data["per_supplement_aeo_card"]
    assert sup["INN_missing_or_empty_with_same_aeo_Id_as_root"] == 1
    assert sup["INN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 1


def test_supplement_aeo_head_uid_mismatch_not_same_org(tmp_path: Path) -> None:
    """При непустом HeadEduOrgId с обеих сторон расхождение с корнем — не «та же ОО»."""
    uid = "11111111-2222-3333-4444-555555555555"
    row = {
        "Id": "cert-head",
        "ActualEducationOrganization": {
            "Id": uid,
            "HeadEduOrgId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "INN": "7700000000",
            "OGRN": "1027700132195",
        },
        "Supplements": [
            {
                "ActualEducationOrganization": {
                    "Id": uid,
                    "HeadEduOrgId": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                    "INN": "",
                    "OGRN": "1027700132195",
                }
            },
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    sup = data["per_supplement_aeo_card"]
    assert sup["INN_missing_or_empty_with_same_aeo_Id_as_root"] == 0


def test_supplement_ogrn_missing_same_aeo_id_as_root(tmp_path: Path) -> None:
    row = {
        "Id": "cert-ogrn",
        "ActualEducationOrganization": {"Id": "org-same", "INN": "7700000000", "OGRN": "1027700132195"},
        "Supplements": [
            {"ActualEducationOrganization": {"Id": "org-same", "INN": "7700000000"}},
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    sup = data["per_supplement_aeo_card"]
    assert sup["OGRN_missing_or_empty_with_same_aeo_Id_as_root"] == 1
    assert sup["INN_missing_or_empty_with_same_aeo_Id_as_root"] == 0
    assert sup["OGRN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 1
    assert sup["INN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 0


def test_root_inn_borrowable_from_supplement_same_uid(tmp_path: Path) -> None:
    row = {
        "Id": "cert-root-borrow",
        "EduOrgINN": "7700000000",
        "EduOrgOGRN": "1027700132195",
        "ActualEducationOrganization": {"Id": "org-same", "OGRN": "1027700132195"},
        "Supplements": [
            {
                "ActualEducationOrganization": {
                    "Id": "org-same",
                    "INN": "7700000001",
                    "OGRN": "1027700132195",
                }
            },
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    assert data["per_certificate"]["root_INN_missing_or_empty_borrowable_from_supplement_aeo_same_uid"] == 1
    assert data["per_certificate"]["root_OGRN_missing_or_empty_borrowable_from_supplement_aeo_same_uid"] == 0


def test_supplement_inn_not_borrow_if_root_inn_not_digits_only(tmp_path: Path) -> None:
    row = {
        "Id": "cert-bad-root-inn",
        "ActualEducationOrganization": {
            "Id": "org-same",
            "INN": "not-digits",
            "OGRN": "1027700132195",
        },
        "Supplements": [
            {"ActualEducationOrganization": {"Id": "org-same", "INN": "", "OGRN": "1027700132195"}},
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    sup = json.loads(outp.read_text(encoding="utf-8"))["per_supplement_aeo_card"]
    assert sup["INN_missing_or_empty_with_same_aeo_Id_as_root"] == 1
    assert sup["INN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 0


def test_supplement_inn_borrow_from_eduorg_when_root_aeo_inn_invalid(tmp_path: Path) -> None:
    row = {
        "Id": "cert-eduorg-inn-donor",
        "EduOrgINN": "770000000099",
        "ActualEducationOrganization": {
            "Id": "org-same",
            "INN": "not-digits",
            "OGRN": "1027700132195",
        },
        "Supplements": [
            {"ActualEducationOrganization": {"Id": "org-same", "INN": "", "OGRN": "1027700132195"}},
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    sup = json.loads(outp.read_text(encoding="utf-8"))["per_supplement_aeo_card"]
    assert sup["INN_missing_or_empty_with_same_aeo_Id_as_root"] == 1
    assert sup["INN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 1


def test_supplement_inn_borrow_from_eduorg_only_no_root_aeo_inn(tmp_path: Path) -> None:
    row = {
        "Id": "cert-eduorg-only",
        "EduOrgINN": "770000000088",
        "EduOrgOGRN": "1027700132195",
        "ActualEducationOrganization": {
            "Id": "org-same",
            "OGRN": "1027700132195",
        },
        "Supplements": [
            {"ActualEducationOrganization": {"Id": "org-same", "INN": "", "OGRN": "1027700132195"}},
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    sup = json.loads(outp.read_text(encoding="utf-8"))["per_supplement_aeo_card"]
    assert sup["INN_missing_same_uid_supplement_could_borrow_from_root_aeo"] == 1


def test_root_inn_borrowable_from_eduorg_without_supplement_inn(tmp_path: Path) -> None:
    row = {
        "Id": "cert-root-eduorg",
        "EduOrgINN": "770000000077",
        "EduOrgOGRN": "1027700132195",
        "ActualEducationOrganization": {"Id": "org-same", "OGRN": "1027700132195"},
        "Supplements": [
            {"ActualEducationOrganization": {"Id": "org-same", "OGRN": "1027700132195"}},
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "audit.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_identity_fields.py"),
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
    pc = json.loads(outp.read_text(encoding="utf-8"))["per_certificate"]
    assert pc["root_INN_missing_or_empty_borrowable_from_supplement_aeo_same_uid"] == 1


def test_identity_fields_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_dataset_identity_fields.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "EduOrgINN" in r.stdout
