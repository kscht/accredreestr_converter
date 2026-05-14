"""tools/extract_unique_educational_programs.py"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_extract_spec = importlib.util.spec_from_file_location(
    "extract_unique_educational_programs",
    ROOT / "tools" / "extract_unique_educational_programs.py",
)
assert _extract_spec and _extract_spec.loader
extract_uep = importlib.util.module_from_spec(_extract_spec)
_extract_spec.loader.exec_module(extract_uep)


def test_extract_unique_programs_dedupes_by_content_not_id(tmp_path: Path) -> None:
    p1 = {
        "Id": "aaa",
        "EduLevelName": "ВО",
        "ProgrammName": "Пед",
        "ProgrammCode": None,
        "UGSName": "Педагогика",
        "Qualification": "Бакалавр",
    }
    p2 = {**p1, "Id": "bbb"}
    p3 = {**p1, "Id": "ccc", "ProgrammName": "Другое"}
    cert = {
        "Id": "cert-1",
        "Supplements": [
            {"Id": "s1", "EducationalPrograms": [p1, p2]},
            {"Id": "s2", "EducationalPrograms": [p3]},
        ],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
            str(inp),
            "-o",
            str(outp),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 2
    by_name = {r.get("ProgrammName"): r for r in rows}
    assert by_name["Пед"]["Id"] == "aaa"
    assert by_name["Другое"]["Id"] == "ccc"


def test_extract_skips_programs_without_ugs_name(tmp_path: Path) -> None:
    with_ugs = {
        "Id": "a",
        "UGSName": "Физика",
        "EduLevelName": "ВО",
        "ProgrammName": "X",
        "Qualification": "Специалист",
    }
    no_ugs = {**with_ugs, "Id": "b", "UGSName": None}
    blank = {**with_ugs, "Id": "c", "UGSName": "   "}
    cert = {
        "Id": "c1",
        "Supplements": [{"Id": "s", "EducationalPrograms": [no_ugs, blank, with_ugs]}],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["Id"] == "a"
    assert "Пропущено (нет UGSName): 2" in r.stderr


def test_extract_unique_programs_help() -> None:
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
            "--help",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "без Id" in r.stdout or "Id" in r.stdout
    assert "UGSName" in r.stdout or "EduNormativePeriod" in r.stdout


def test_extract_drops_typename_and_period_for_nomenclature(tmp_path: Path) -> None:
    a = {
        "Id": "i1",
        "TypeName": None,
        "EduLevelName": "X",
        "EduNormativePeriod": "2 года",
        "ProgrammName": "P",
        "UGSName": "Группа наук",
        "Qualification": "Магистр",
    }
    b = {**a, "Id": "i2", "EduNormativePeriod": "4 года"}
    cert = {"Id": "c", "Supplements": [{"Id": "s", "EducationalPrograms": [a, b]}]}
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert "TypeName" not in row
    assert "EduNormativePeriod" not in row
    for k in ("IsAccredited", "IsCanceled", "IsSuspended"):
        assert k not in row
    assert row["Id"] == "i1"
    assert row["ProgrammName"] == "P"


def test_extract_omits_accreditation_flags_even_when_set(tmp_path: Path) -> None:
    a = {
        "Id": "x1",
        "UGSName": "Науки",
        "EduLevelName": "L",
        "ProgrammName": "P",
        "Qualification": "Бакалавр",
        "IsAccredited": True,
        "IsCanceled": None,
        "IsSuspended": False,
    }
    b = {
        **a,
        "Id": "x2",
        "IsAccredited": False,
        "IsCanceled": True,
        "IsSuspended": None,
    }
    cert = {"Id": "c", "Supplements": [{"Id": "s", "EducationalPrograms": [a, b]}]}
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["Id"] == "x1"
    assert "IsAccredited" not in row and "IsCanceled" not in row and "IsSuspended" not in row


def test_extract_skips_null_qualification_with_require_flag(tmp_path: Path) -> None:
    ok = {
        "Id": "q1",
        "UGSName": "Укрупнённая группа",
        "EduLevelName": "ВО",
        "ProgrammName": "Прикладная математика",
        "Qualification": "Бакалавр",
    }
    null_q = {**ok, "Id": "q2", "Qualification": None}
    blank_q = {**ok, "Id": "q3", "Qualification": "  "}
    cert = {"Id": "c", "Supplements": [{"Id": "s", "EducationalPrograms": [null_q, blank_q, ok]}]}
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
            str(inp),
            "-o",
            str(outp),
            "--require-qualification",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["Id"] == "q1"
    assert "Пропущено (нет Qualification, режим --require-qualification): 2" in r.stderr


def test_extract_normalizes_qualification_trailing_dot_and_space(tmp_path: Path) -> None:
    """Канон: без хвостовых пробелов и без точки перед закрывающей кавычкой; затем дедупликация."""
    base = {
        "EduLevelName": "ВО",
        "ProgrammName": "Пед",
        "ProgrammCode": None,
        "UGSName": "Педагогика",
    }
    p_dot = {"Id": "i1", "Qualification": "Бакалавр.", **base}
    p_space = {"Id": "i2", "Qualification": "Бакалавр   ", **base}
    p_clean = {"Id": "i3", "Qualification": "Бакалавр", **base}
    cert = {"Id": "c", "Supplements": [{"Id": "s", "EducationalPrograms": [p_dot, p_space, p_clean]}]}
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["Qualification"] == "Бакалавр"
    assert rows[0]["Id"] == "i1"


def test_extract_skips_qualification_empty_after_normalization_when_required(tmp_path: Path) -> None:
    ok = {
        "Id": "k1",
        "UGSName": "Группа",
        "EduLevelName": "ВО",
        "ProgrammName": "P",
        "Qualification": "Магистр",
    }
    only_dots_spaces = {**ok, "Id": "k2", "Qualification": "  .  "}
    cert = {"Id": "c", "Supplements": [{"Id": "s", "EducationalPrograms": [only_dots_spaces, ok]}]}
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
            str(inp),
            "-o",
            str(outp),
            "--require-qualification",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["Id"] == "k1"
    assert "Пропущено (нет Qualification, режим --require-qualification): 1" in r.stderr


def test_verify_output_invariants_catches_missing_anchor_code() -> None:
    seen = {"x": {"ProgrammCode": "09.02.01", "UGSName": "Информатика и вычислительная техника"}}
    hits = {"09.02.07": 3}
    err = extract_uep._verify_output_invariants(seen, hits)
    assert err is not None
    assert "09.02.07" in err


def test_verify_output_invariants_ok_when_anchor_present() -> None:
    row = {
        "ProgrammCode": "09.02.07",
        "UGSName": "Информатика и вычислительная техника",
        "Qualification": None,
    }
    assert extract_uep._verify_output_invariants({"a": row}, {"09.02.07": 5}) is None


def test_extract_includes_program_with_null_qualification_by_default(tmp_path: Path) -> None:
    """Как в ИС ГА для части СПО: UGSName есть, Qualification null — строка попадает в справочник."""
    spo = {
        "Id": "s1",
        "UGSName": "Информатика и вычислительная техника",
        "UGSCode": "09.00.00",
        "EduLevelName": "Среднее профессиональное образование",
        "ProgrammName": "Информационные системы и программирование",
        "ProgrammCode": "09.02.07",
        "Qualification": None,
    }
    cert = {"Id": "c", "Supplements": [{"Id": "sup", "EducationalPrograms": [spo]}]}
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["ProgrammCode"] == "09.02.07"
    assert rows[0].get("Qualification") is None
    assert "Пропущено (нет Qualification, режим --require-qualification): 0" in r.stderr


def test_extract_output_sorted_by_qualification_length_then_programm_code(
    tmp_path: Path,
) -> None:
    """При равной длине Qualification — сначала ProgrammCode, затем UGSCode (пустой UGS — в конец)."""
    base = {"EduLevelName": "ВО", "ProgrammCode": None, "Qualification": "Бакалавр"}
    p02 = {
        "Id": "i02",
        "UGSName": "Укрупнённая 02",
        "UGSCode": "02.00.00",
        "ProgrammName": "Программа 2",
        **base,
    }
    p01 = {
        "Id": "i01",
        "UGSName": "Укрупнённая 01",
        "UGSCode": "01.00.00",
        "ProgrammName": "Программа 1",
        **base,
    }
    p_no_code = {
        "Id": "i0",
        "UGSName": "Без кода УГС",
        "ProgrammName": "Программа 0",
        **base,
    }
    cert = {
        "Id": "c",
        "Supplements": [{"Id": "s", "EducationalPrograms": [p02, p01, p_no_code]}],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 3
    assert [x["Id"] for x in rows] == ["i01", "i02", "i0"]
    assert [x.get("UGSCode") for x in rows] == ["01.00.00", "02.00.00", None]


def test_extract_sort_programm_code_before_ugs_when_same_qualification_length(
    tmp_path: Path,
) -> None:
    """Прежний номенклатурный порядок: при равной длине квалификации сначала ProgrammCode, потом UGSCode."""
    ql = "Бакалавр"
    base = {"EduLevelName": "ВО", "UGSName": "Укрупнённая", "Qualification": ql}
    # При сортировке сначала по UGS шло бы b (01...) затем a (02...); по ProgrammCode — a затем b.
    a = {
        "Id": "pc_first",
        **base,
        "UGSCode": "02.00.00",
        "ProgrammCode": "01.01.01",
        "ProgrammName": "P1",
    }
    b = {
        "Id": "ugs_would_be_first",
        **base,
        "UGSCode": "01.00.00",
        "ProgrammCode": "09.09.09",
        "ProgrammName": "P2",
    }
    cert = {"Id": "c", "Supplements": [{"Id": "s", "EducationalPrograms": [b, a]}]}
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 2
    assert [x["Id"] for x in rows] == ["pc_first", "ugs_would_be_first"]
    """Сначала по убыванию длины Qualification; пустое поле — в конец по длине."""
    base = {
        "EduLevelName": "ВО",
        "UGSName": "Науки",
        "UGSCode": "01.00.00",
        "ProgrammName": "Программа",
    }
    short = {"Id": "i_short", **base, "Qualification": "Бак"}
    long_q = {
        "Id": "i_long",
        **base,
        "Qualification": "Очень длинная квалификация для сортировки",
    }
    null_q = {"Id": "i_null", **base}
    cert = {
        "Id": "c",
        "Supplements": [{"Id": "s", "EducationalPrograms": [short, null_q, long_q]}],
    }
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps(cert, ensure_ascii=False) + "\n", encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "extract_unique_educational_programs.py"),
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
    rows = [json.loads(x) for x in outp.read_text(encoding="utf-8").strip().splitlines()]
    assert len(rows) == 3
    assert [x["Id"] for x in rows] == ["i_long", "i_short", "i_null"]
