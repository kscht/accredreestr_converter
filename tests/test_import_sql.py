"""Импорт JSONL → SQLite, PostgreSQL, MySQL (опционально)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import convert as c
from sql_convert.import_sql import _parse_mysql_dsn, export_jsonl_to_sql, import_jsonl
from sql_convert.sql_ddl import build_create_statements, build_drop_statements, load_mapping

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


def test_import_sql_module_help() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "sql_convert.import_sql", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "--sqlite" in r.stdout
    assert "--postgres" in r.stdout
    assert "--sql-out" in r.stdout
    assert "--mysql" in r.stdout


def test_parse_mysql_dsn() -> None:
    k = _parse_mysql_dsn("mysql://u:p@db.example:3307/mydb")
    assert k == {
        "host": "db.example",
        "port": 3307,
        "user": "u",
        "password": "p",
        "database": "mydb",
    }
    k2 = _parse_mysql_dsn("user@localhost/testdb")
    assert k2["host"] == "localhost"
    assert k2["database"] == "testdb"
    assert k2["user"] == "user"


def test_ddl_mysql_innodb_and_backticks() -> None:
    mapping = load_mapping()
    creates = build_create_statements(mapping, "mysql")
    joined = "\n".join(creates)
    assert "ENGINE=InnoDB" in joined
    assert "DEFAULT CHARSET=utf8mb4" in joined
    assert "`certificates`" in joined
    assert "`is_federal`" in joined
    assert "TINYINT(1)" in joined


def test_export_sql_mysql_dump_shape(ms_jsonl: Path, tmp_path: Path) -> None:
    sql_path = tmp_path / "dump_mysql.sql"
    export_jsonl_to_sql(
        ms_jsonl,
        sql_path,
        dialect="mysql",
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    text = sql_path.read_text(encoding="utf-8")
    assert "SET NAMES utf8mb4" in text
    assert "INSERT INTO `certificates`" in text
    assert "ENGINE=InnoDB" in text


def test_ddl_sqlite_memory() -> None:
    mapping = load_mapping()
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    for stmt in build_drop_statements(mapping, "sqlite"):
        conn.execute(stmt)
    for stmt in build_create_statements(mapping, "sqlite"):
        conn.execute(stmt)
    conn.commit()
    n = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='certificates'"
    ).fetchone()[0]
    assert n == 1
    conn.close()


def test_export_sql_file_sqlite_roundtrip(ms_jsonl: Path, tmp_path: Path) -> None:
    sql_path = tmp_path / "dump.sql"
    export_jsonl_to_sql(
        ms_jsonl,
        sql_path,
        dialect="sqlite",
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    assert sql_path.is_file()
    db = tmp_path / "from_sql.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(sql_path.read_text(encoding="utf-8"))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM certificates").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM supplements").fetchone()[0] == 2
    conn.close()


def test_import_sqlite_multiple_supplements(ms_jsonl: Path, tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    import_jsonl(
        ms_jsonl,
        dialect="sqlite",
        sqlite_path=db,
        postgres_conninfo=None,
        mysql_dsn=None,
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM certificates").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM supplements").fetchone()[0] == 2
    conn.close()


def _have_psycopg() -> bool:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not os.environ.get("ACCRED_PG_TEST_DSN") or not _have_psycopg(),
    reason="Нужны ACCRED_PG_TEST_DSN и пакет psycopg",
)
def test_import_postgres_roundtrip(ms_jsonl: Path) -> None:
    dsn = os.environ["ACCRED_PG_TEST_DSN"]
    import_jsonl(
        ms_jsonl,
        dialect="postgres",
        sqlite_path=None,
        postgres_conninfo=dsn,
        mysql_dsn=None,
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM certificates")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM supplements")
            assert cur.fetchone()[0] == 2


def _have_pymysql() -> bool:
    try:
        import pymysql  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not os.environ.get("ACCRED_MYSQL_TEST_DSN") or not _have_pymysql(),
    reason="Нужны ACCRED_MYSQL_TEST_DSN и пакет pymysql",
)
def test_import_mysql_roundtrip(ms_jsonl: Path) -> None:
    dsn = os.environ["ACCRED_MYSQL_TEST_DSN"]
    import pymysql

    import_jsonl(
        ms_jsonl,
        dialect="mysql",
        sqlite_path=None,
        postgres_conninfo=None,
        mysql_dsn=dsn,
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    kw = _parse_mysql_dsn(dsn)
    conn = pymysql.connect(**kw, charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM `certificates`")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM `supplements`")
            assert cur.fetchone()[0] == 2
    finally:
        conn.close()
