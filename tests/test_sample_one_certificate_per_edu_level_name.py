"""tools/sample_one_certificate_per_edu_level_name.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sample_max_fill_prefers_richer_certificate(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.json"
    vocab.write_text(
        json.dumps({"unique_edu_level_names": ["А", "Б"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "in.jsonl"
    src.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "Id": "sparse",
                        "Supplements": [
                            {"EducationalPrograms": [{"EduLevelName": "А"}]},
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "Id": "richer",
                        "RegionName": "Регион",
                        "Supplements": [
                            {
                                "EducationalPrograms": [
                                    {
                                        "EduLevelName": "А",
                                        "ProgrammName": "Программа",
                                        "ProgrammCode": "01.01.01",
                                    }
                                ]
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "Id": "only-b",
                        "Supplements": [{"EducationalPrograms": [{"EduLevelName": "Б"}]}],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "sample_one_certificate_per_edu_level_name.py"),
            str(src),
            "-o",
            str(outp),
            "--vocab",
            str(vocab),
            "--seed",
            "0",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    by = {json.loads(ln)["EduLevelName"]: json.loads(ln) for ln in outp.read_text(encoding="utf-8").strip().splitlines()}
    assert "certificate" not in by["А"]
    assert "certificate_id" not in by["А"]
    assert "certificate_fill_score" not in by["А"]
    pa = by["А"]["programs"]
    assert len(pa) == 1
    assert pa[0]["ProgrammName"] == "Программа"
    assert pa[0]["ProgrammCode"] == "01.01.01"
    assert "EduLevelName" not in pa[0]
    assert "certificate_id" not in by["Б"]
    assert len(by["Б"]["programs"]) == 1


def test_sample_uniform_random_reservoir(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.json"
    vocab.write_text(
        json.dumps({"unique_edu_level_names": ["А", "Б"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    src = tmp_path / "in.jsonl"
    src.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "Id": "c1",
                        "Supplements": [
                            {
                                "EducationalPrograms": [
                                    {"EduLevelName": "А", "ProgrammName": "p"},
                                ]
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "Id": "c2",
                        "Supplements": [
                            {
                                "EducationalPrograms": [
                                    {"EduLevelName": "А"},
                                    {"EduLevelName": "Б"},
                                ]
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "Id": "c3",
                        "Supplements": [{"EducationalPrograms": [{"EduLevelName": "Б"}]}],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "sample_one_certificate_per_edu_level_name.py"),
            str(src),
            "-o",
            str(outp),
            "--vocab",
            str(vocab),
            "--uniform-random",
            "--seed",
            "0",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    lines = outp.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    by = {json.loads(ln)["EduLevelName"]: json.loads(ln) for ln in lines}
    assert "certificate" not in by["А"]
    assert "certificate_id" not in by["А"]
    assert "certificate_fill_score" not in by["А"]
    assert by["А"]["programs"][0]["ProgrammName"] == "p"
    assert "EduLevelName" not in by["А"]["programs"][0]
    assert "program_index_in_supplement" not in by["А"]["programs"][0]
    assert "certificate_id" not in by["Б"]
    assert len(by["А"]["programs"]) == 1
    assert len(by["Б"]["programs"]) == 1


def test_sample_one_per_edu_level_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sample_one_certificate_per_edu_level_name.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "EduLevelName" in r.stdout
    assert "uniform-random" in r.stdout
