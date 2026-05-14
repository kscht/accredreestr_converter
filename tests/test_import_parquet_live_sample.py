"""Опциональный экспорт Parquet с живой подвыборкой JSONL (не в CI по умолчанию)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parquet_convert.import_duckdb import import_jsonl_to_duckdb
from sql_convert.sql_ddl import load_mapping

ROOT = Path(__file__).resolve().parents[1]
LIVE_JSONL = ROOT / "out" / "sample_live_5000.jsonl"
# Полный экспорт большого JSONL в Parquet в pytest долго; проверяем срез живых данных.
LIVE_PARQUET_LIMIT = 100


@pytest.mark.skipif(
    os.environ.get("ACCRED_PARQUET_LIVE_SAMPLE") != "1",
    reason="Задайте ACCRED_PARQUET_LIVE_SAMPLE=1 для Parquet из out/sample_live_5000.jsonl",
)
@pytest.mark.skipif(
    not LIVE_JSONL.is_file(),
    reason=f"Нет файла {LIVE_JSONL} (сгенерируйте: python tools/sample_jsonl_lines.py …)",
)
def test_parquet_export_live_sample_slice(tmp_path: Path) -> None:
    """In-memory DuckDB → COPY в Parquet по первым N непустым строкам живого JSONL (см. LIVE_PARQUET_LIMIT)."""
    pytest.importorskip("duckdb")
    import duckdb

    pq = tmp_path / "parquet_out"
    import_jsonl_to_duckdb(
        LIVE_JSONL,
        duckdb_path=None,
        parquet_dir=pq,
        mapping_path=None,
        recreate=True,
        limit=LIVE_PARQUET_LIMIT,
    )
    mapping = load_mapping()
    for t in mapping["tables"]:
        path = pq / f"{t['name']}.parquet"
        assert path.is_file(), f"ожидался файл {path}"

    con = duckdb.connect(":memory:")
    try:
        cert_pq = pq / "certificates.parquet"
        n = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [str(cert_pq.resolve())],
        ).fetchone()[0]
        assert n == LIVE_PARQUET_LIMIT
    finally:
        con.close()
