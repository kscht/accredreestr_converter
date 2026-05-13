"""Опциональный импорт JSONL в SQLite на живой подвыборке (не в CI по умолчанию)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from sql_convert.import_sql import import_jsonl

ROOT = Path(__file__).resolve().parents[1]
LIVE_JSONL = ROOT / "out" / "sample_live_5000.jsonl"


@pytest.mark.skipif(
    os.environ.get("ACCRED_SQL_LIVE_SAMPLE") != "1",
    reason="Задайте ACCRED_SQL_LIVE_SAMPLE=1 для импорта out/sample_live_5000.jsonl",
)
@pytest.mark.skipif(
    not LIVE_JSONL.is_file(),
    reason=f"Нет файла {LIVE_JSONL} (сгенерируйте: python tools/sample_jsonl_lines.py …)",
)
def test_import_sqlite_live_sample_5000_all_rows(tmp_path: Path) -> None:
    """Импорт всей живой подвыборки: все строки JSONL должны пройти без отката."""
    db = tmp_path / "live.sqlite"
    import_jsonl(
        LIVE_JSONL,
        dialect="sqlite",
        sqlite_path=db,
        postgres_conninfo=None,
        mysql_dsn=None,
        mapping_path=None,
        recreate=True,
        limit=None,
    )
    conn = sqlite3.connect(str(db))
    n_cert = conn.execute("SELECT COUNT(*) FROM certificates").fetchone()[0]
    conn.close()
    assert n_cert == 5000
