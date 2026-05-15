"""tools/extract_unique_edu_level_names.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_extract_unique_edu_level_names_minimal(tmp_path: Path) -> None:
    src = tmp_path / "certs.jsonl"
    src.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "Id": "c1",
                        "Supplements": [
                            {
                                "EducationalPrograms": [
                                    {"EduLevelName": "  А  ", "ProgrammName": "P1"},
                                    {"EduLevelName": "А"},
                                    {"ProgrammName": "no level"},
                                    {"EduLevelName": ""},
                                    {"EduLevelName": None},
                                    {"EduLevelName": "Б"},
                                ]
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps({"Id": "c2", "Supplements": []}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    outp = tmp_path / "vocab.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_edu_level_names.py"),
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
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["format_version"] == 1
    assert data["certificate_lines_total"] == 2
    assert data["educational_program_objects_total"] == 6
    assert data["educational_programs_nonempty_edu_level_name"] == 3
    assert data["educational_programs_empty_or_missing_edu_level_name"] == 3
    assert data["unique_edu_level_names"] == ["А", "Б"]
    assert data["histogram_EduLevelName"]["А"] == 2
    assert data["histogram_EduLevelName"]["Б"] == 1


def test_extract_unique_edu_level_names_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "extract_unique_edu_level_names.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "EduLevelName" in r.stdout
