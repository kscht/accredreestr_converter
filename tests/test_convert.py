"""Тесты конвертации XML → JSONL."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import convert as c

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMA = ROOT / "data-20160908-structure-20160713.xml"


def _run_convert_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "convert.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_minimal(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    stats = c.convert_many(
        [FIXTURES / "minimal.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    rows = _read_jsonl(out)
    assert len(rows) == 1
    row = rows[0]
    assert row["Id"] == "min-1"
    assert row["IsFederal"] is True
    assert row["IssueDate"] == "2020-01-15"
    assert row["EndDate"] == "2025-01-15"
    assert row["_source_file"] == "minimal.xml"
    assert row["Supplements"] == []
    assert row["Decisions"] == []
    assert stats.per_file["minimal.xml"]["processed"] == 1


def test_multiple_supplements(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "multiple_supplements.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    row = _read_jsonl(out)[0]
    sups = row["Supplements"]
    assert isinstance(sups, list)
    assert len(sups) == 2
    assert {s["Id"] for s in sups} == {"s1", "s2"}
    assert sups[0]["EducationalPrograms"] == []


def test_single_supplement_wrapped_in_array(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "single_supplement.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    row = _read_jsonl(out)[0]
    sups = row["Supplements"]
    assert isinstance(sups, list) and len(sups) == 1
    assert sups[0]["IssueDate"] == "2021-06-01"


def test_missing_collection_is_empty_array(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "no_supplements.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    row = _read_jsonl(out)[0]
    assert row["Supplements"] == []
    assert row["Decisions"] == []


def test_bool_casting(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    stats = c.ConversionStats()
    assert c.cast_bool("1", "IsFederal", stats) is True
    assert c.cast_bool(" 0 ", "IsFederal", stats) is False
    assert c.cast_bool("Да", "IsFederal", stats) is True
    assert c.cast_bool("ДА", "IsFederal", stats) is True
    assert c.cast_bool("true", "IsFederal", stats) is True
    assert c.cast_bool("возможно", "IsFederal", stats) is None
    assert stats.bad_booleans == 1
    assert "Не удалось распознать булево" in caplog.text


def test_date_normalization(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    stats = c.ConversionStats()
    assert c.parse_date("2019-04-15T10:00:00+03:00", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("2010-06-18 00:00:00+04", "IssueDate", stats) == "2010-06-18"
    assert c.parse_date("2019-04-15T10:00:00+03", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("2019-04-15T10:00:00+0300", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("2019-04-15 10:00:00", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("2019-04-15", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("15.04.2019", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("15/04/2019", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("15-04-2019", "IssueDate", stats) == "2019-04-15"
    assert c.parse_date("вчера", "IssueDate", stats) == "вчера"
    assert stats.bad_dates == 1


def test_id_numbers_are_strings() -> None:
    stats = c.ConversionStats()
    assert c.cast_id_number("007200000000", "INN", stats) == "007200000000"
    assert c.cast_id_number("7 200 000 000", "INN", stats) == "7200000000"
    assert c.cast_id_number("7200-000-000", "INN", stats) == "7200000000"
    assert c.cast_id_number("12-3X4", "INN", stats) == "123X4"
    assert stats.non_digit_ids == 1


def test_empty_tag_becomes_null(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "empty_fields.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    row = _read_jsonl(out)[0]
    assert row["RegNumber"] is None
    assert row["StatusName"] is None
    assert row["TypeName"] is None
    assert row["RegionName"] is None
    assert row["IssueDate"] is None


def test_broken_record_skipped(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    calls = {"n": 0}
    real_dump = json.dumps

    def _dumps(obj: object, **kwargs: object) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated broken record")
        return real_dump(obj, **kwargs)

    with mock.patch.object(c.json, "dumps", _dumps):
        stats = c.convert_many(
            [FIXTURES / "broken_record.xml"],
            out,
            merged=True,
            out_dir=tmp_path,
            progress_every=0,
            limit=None,
            strict=False,
            schema_path=SCHEMA,
        )
    rows = _read_jsonl(out)
    assert len(rows) == 1
    assert rows[0]["Id"] == "br-1"
    assert stats.per_file["broken_record.xml"]["skipped"] == 1
    assert stats.broken_records == 1


def test_cyrillic_preserved(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "cyrillic.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    row = _read_jsonl(out)[0]
    assert "Организация" in row["EduOrgFullName"]


def test_limit_option(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "limit_batch.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=2,
        strict=False,
        schema_path=SCHEMA,
    )
    rows = _read_jsonl(out)
    assert len(rows) == 2
    assert {r["Id"] for r in rows} == {"l1", "l2"}


def test_dirty_whitespace(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "dirty_data.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    row = _read_jsonl(out)[0]
    assert row["RegNumber"] == "RN 1 2"
    assert "ул. Пушкина" in row["PostAddress"]


def test_control_chars_stripped() -> None:
    assert c.clean_text("A\x01B") == "AB"
    assert c.ensure_json_safe({"x": "A\x02B"})["x"] == "AB"


def test_invalid_utf8_recovered(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / "invalid_encoding.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    row = _read_jsonl(out)[0]
    assert row["Id"] == "ie-1"
    assert isinstance(row["RegNumber"], str)


def test_strict_mode_fails_on_broken(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    calls = {"n": 0}
    real_dump = json.dumps

    def _dumps(obj: object, **kwargs: object) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated broken record")
        return real_dump(obj, **kwargs)

    with mock.patch.object(c.json, "dumps", _dumps):
        with pytest.raises(RuntimeError):
            c.convert_many(
                [FIXTURES / "broken_record.xml"],
                out,
                merged=True,
                out_dir=tmp_path,
                progress_every=0,
                limit=None,
                strict=True,
                schema_path=SCHEMA,
            )


def test_report_file(tmp_path: Path) -> None:
    out = tmp_path / "o.jsonl"
    rep = tmp_path / "rep.json"
    proc = _run_convert_cli(
        [
            str(FIXTURES / "minimal.xml"),
            "-o",
            str(out),
            "--report",
            str(rep),
            "--schema",
            str(SCHEMA),
            "--progress-every",
            "0",
        ]
    )
    assert proc.returncode == 0
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert "inputs" in data and "per_file" in data and "total" in data
    assert data["total"]["processed"] >= 1


def test_multiple_inputs_merged(tmp_path: Path) -> None:
    a = tmp_path / "a.xml"
    b = tmp_path / "b.xml"
    cfile = tmp_path / "c.xml"
    a.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><OpenData><Certificates>'
        '<Certificate><Id>a1</Id><IsFederal>1</IsFederal></Certificate>'
        "</Certificates></OpenData>",
        encoding="utf-8",
    )
    b.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><OpenData><Certificates>'
        '<Certificate><Id>b1</Id><IsFederal>0</IsFederal></Certificate>'
        "</Certificates></OpenData>",
        encoding="utf-8",
    )
    cfile.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><OpenData><Certificates>'
        '<Certificate><Id>c1</Id><IsFederal>1</IsFederal></Certificate>'
        "</Certificates></OpenData>",
        encoding="utf-8",
    )
    out = tmp_path / "merged.jsonl"
    c.convert_many(
        [a, b, cfile],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    rows = _read_jsonl(out)
    assert {r["_source_file"] for r in rows} == {"a.xml", "b.xml", "c.xml"}
    assert {r["Id"] for r in rows} == {"a1", "b1", "c1"}


def test_default_multiple_separate_outputs(tmp_path: Path) -> None:
    a = tmp_path / "one.xml"
    b = tmp_path / "two.xml"
    a.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><OpenData><Certificates>'
        '<Certificate><Id>x</Id><IsFederal>1</IsFederal></Certificate>'
        "</Certificates></OpenData>",
        encoding="utf-8",
    )
    b.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><OpenData><Certificates>'
        '<Certificate><Id>y</Id><IsFederal>0</IsFederal></Certificate>'
        "</Certificates></OpenData>",
        encoding="utf-8",
    )
    c.convert_many(
        [a, b],
        None,
        merged=False,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    assert (tmp_path / "one.jsonl").is_file()
    assert (tmp_path / "two.jsonl").is_file()
    assert _read_jsonl(tmp_path / "one.jsonl")[0]["Id"] == "x"
    assert _read_jsonl(tmp_path / "two.jsonl")[0]["Id"] == "y"


def test_unknown_tag_warned_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    out = tmp_path / "o.jsonl"
    stats = c.convert_many(
        [FIXTURES / "unknown_tag.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    rows = _read_jsonl(out)
    assert all("TotallyUnknownField" in r for r in rows)
    assert stats.unknown_tags.count("TotallyUnknownField") == 1
    warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert sum(1 for m in warn_msgs if "Неизвестный тег" in m) == 1


@pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="Тяжёлый тест, задайте RUN_SLOW=1")
def test_streaming_memory(tmp_path: Path) -> None:
    big = tmp_path / "big.xml"
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?><OpenData><Certificates>',
    ]
    for i in range(5000):
        parts.append(
            f"<Certificate><Id>i{i}</Id><IsFederal>1</IsFederal></Certificate>"
        )
    parts.append("</Certificates></OpenData>")
    big.write_text("".join(parts), encoding="utf-8")
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [big],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    assert len(_read_jsonl(out)) == 5000


def test_cli_help() -> None:
    p = _run_convert_cli(["--help"])
    assert p.returncode == 0
    assert "--merged" in p.stdout

    p2 = subprocess.run(
        [sys.executable, str(ROOT / "download.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert p2.returncode == 0
