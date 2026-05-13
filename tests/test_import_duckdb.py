"""Импорт JSONL → DuckDB и экспорт Parquet."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import convert as c
from parquet_convert.import_duckdb import import_jsonl_to_duckdb

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMA = ROOT / "specs" / "xml" / "data-20160908-structure-20160713.xml"


@pytest.fixture()
def ms_jsonl(tmp_path: Path) -> Path:
    out = tmp_path / "ms.jsonl"
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
    return out


def test_import_duckdb_module_help() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "parquet_convert.import_duckdb", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "--duckdb" in r.stdout
    assert "--parquet-dir" in r.stdout


def test_import_duckdb_file_roundtrip(ms_jsonl: Path, tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    import duckdb

    db = tmp_path / "w.duckdb"
    import_jsonl_to_duckdb(
        ms_jsonl,
        duckdb_path=db,
        parquet_dir=None,
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    con = duckdb.connect(str(db))
    try:
        assert con.execute("SELECT COUNT(*) FROM certificates").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM supplements").fetchone()[0] == 2
    finally:
        con.close()


def test_import_duckdb_parquet_export(ms_jsonl: Path, tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    import duckdb

    pq = tmp_path / "pq"
    import_jsonl_to_duckdb(
        ms_jsonl,
        duckdb_path=None,
        parquet_dir=pq,
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    assert (pq / "certificates.parquet").is_file()
    assert (pq / "supplements.parquet").is_file()
    con = duckdb.connect(":memory:")
    try:
        p = pq / "certificates.parquet"
        n = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [str(p.resolve())],
        ).fetchone()[0]
        assert n == 1
    finally:
        con.close()


def test_import_duckdb_limit_counts_input_lines_including_failed(ms_jsonl: Path, tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    import duckdb

    line = ms_jsonl.read_text(encoding="utf-8").strip()
    dup = tmp_path / "dup.jsonl"
    dup.write_text(line + "\n" + line + "\n", encoding="utf-8")
    db1 = tmp_path / "d1.duckdb"
    import_jsonl_to_duckdb(
        dup,
        duckdb_path=db1,
        parquet_dir=None,
        mapping_path=None,
        recreate=True,
        limit=1,
    )
    con = duckdb.connect(str(db1))
    try:
        assert con.execute('SELECT COUNT(*) FROM "certificates"').fetchone()[0] == 1
    finally:
        con.close()

    db2 = tmp_path / "d2.duckdb"
    import_jsonl_to_duckdb(
        dup,
        duckdb_path=db2,
        parquet_dir=None,
        mapping_path=None,
        recreate=True,
        limit=2,
    )
    con = duckdb.connect(str(db2))
    try:
        assert con.execute('SELECT COUNT(*) FROM "certificates"').fetchone()[0] == 1
    finally:
        con.close()
