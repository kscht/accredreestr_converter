"""tools/audit_dataset_edu_program_levels.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_edu_program_levels_kinds(tmp_path: Path) -> None:
    # 1: нет программ
    r1 = {"Id": "1", "Supplements": [{"Number": "1", "EducationalPrograms": []}]}
    # 2: все уровни пустые
    r2 = {
        "Id": "2",
        "Supplements": [{"EducationalPrograms": [{"Id": "a"}, {"EduLevelName": "  "}]}],
    }
    # 3: только школа
    r3 = {
        "Id": "3",
        "Supplements": [
            {
                "EducationalPrograms": [
                    {"Id": "p1", "EduLevelName": "Начальное общее образование"},
                ]
            }
        ],
    }
    # 4: только не школа
    r4 = {
        "Id": "4",
        "Supplements": [
            {
                "EducationalPrograms": [
                    {"Id": "p1", "EduLevelName": "Среднее профессиональное образование"},
                ]
            }
        ],
    }
    # 5: смесь
    r5 = {
        "Id": "5",
        "Supplements": [
            {
                "EducationalPrograms": [
                    {"Id": "p1", "EduLevelName": "Среднее общее образование"},
                    {"Id": "p2", "EduLevelName": "Высшее образование - бакалавриат"},
                ]
            }
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in (r1, r2, r3, r4, r5)) + "\n",
        encoding="utf-8",
    )
    outp = tmp_path / "audit.json"
    out_non = tmp_path / "non.jsonl"
    out_sch = tmp_path / "sch.jsonl"
    out_mix = tmp_path / "mix.jsonl"
    out_empty = tmp_path / "empty.jsonl"
    out_empty_prog = tmp_path / "empty_prog.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_dataset_edu_program_levels.py"),
            str(inp),
            "-o",
            str(outp),
            "--limit",
            "10",
            "-p",
            str(out_non),
            "--school-jsonl",
            str(out_sch),
            "--mixed-jsonl",
            str(out_mix),
            "--empty-level-jsonl",
            str(out_empty),
            "--empty-program-jsonl",
            str(out_empty_prog),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["certificate_lines_total"] == 5
    b = data["certificates_by_program_level_kind"]
    assert b["no_educational_programs"] == 1
    assert b["all_program_levels_empty"] == 1
    assert b["school_levels_only"] == 1
    assert b["non_school_levels_only"] == 1
    assert b["mixed_school_and_other"] == 1

    assert data["school_sector_program_objects_subtotal"] == 2
    assert data["school_sector_histogram"]["Начальное общее образование"] == 1
    assert data["school_sector_histogram"]["Среднее общее образование"] == 1
    assert data["certificates_with_any_empty_EduLevelName_program"] == 1
    assert data["by_kind_if_has_empty_edulevel"] == {"all_program_levels_empty": 1}
    assert data["exports"]["empty_EduLevelName_jsonl"] == str(out_empty.resolve())
    assert data["exports"]["empty_EduLevelName_program_objects_jsonl"] == str(out_empty_prog.resolve())
    assert len(data["examples_certificates_with_empty_EduLevelName_program"]) == 1

    assert len(out_empty.read_text(encoding="utf-8").strip().splitlines()) == 1
    assert json.loads(out_empty.read_text(encoding="utf-8").splitlines()[0])["Id"] == "2"

    empty_prog_lines = out_empty_prog.read_text(encoding="utf-8").strip().splitlines()
    assert len(empty_prog_lines) == 2
    w0 = json.loads(empty_prog_lines[0])
    assert w0["certificate_id"] == "2"
    assert w0["supplement_index"] == 0
    assert w0["program_index_in_supplement"] == 0
    assert w0["program"]["Id"] == "a"
    w1 = json.loads(empty_prog_lines[1])
    assert w1["program_index_in_supplement"] == 1
    assert w1["program"].get("EduLevelName") in (None, "  ")

    non_first = json.loads(out_non.read_text(encoding="utf-8").splitlines()[0])
    assert non_first["Id"] == "4"
    assert len(out_sch.read_text(encoding="utf-8").strip().splitlines()) == 1
    sch_first = json.loads(out_sch.read_text(encoding="utf-8").splitlines()[0])
    assert sch_first["Id"] == "3"
    assert len(out_mix.read_text(encoding="utf-8").strip().splitlines()) == 1
    assert json.loads(out_mix.read_text(encoding="utf-8").splitlines()[0])["Id"] == "5"


def test_audit_edu_program_levels_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_dataset_edu_program_levels.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "EduLevelName" in r.stdout
    assert "school-jsonl" in r.stdout
    assert "empty-level-jsonl" in r.stdout
    assert "empty-program-jsonl" in r.stdout
