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
        "ActualEducationOrganization": {"INN": "7700000001", "OGRN": "1027700132195"},
        "Supplements": [
            {"ActualEducationOrganization": {"INN": "", "OGRN": "1030000000000"}},
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
