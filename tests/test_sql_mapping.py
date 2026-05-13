"""Смоук-тест: specs/sql/mapping.json парсится и содержит ожидаемые таблицы."""

import json
from pathlib import Path

from sql_convert.sql_ddl import build_create_statements, load_mapping

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "specs" / "sql" / "mapping.json"


def test_sql_mapping_json_loads() -> None:
    data = json.loads(MAPPING.read_text(encoding="utf-8"))
    assert data.get("format_version") == 1
    names = {t["name"] for t in data["tables"]}
    assert names == {
        "certificates",
        "supplements",
        "decisions",
        "educational_programs",
        "actual_education_organizations",
    }
    cert = next(t for t in data["tables"] if t["name"] == "certificates")
    assert cert["primary_key"] == ["source_file", "certificate_id"]
    prog = next(t for t in data["tables"] if t["name"] == "educational_programs")
    assert prog["primary_key"] == [
        "source_file",
        "certificate_id",
        "supplement_id",
        "program_slot",
    ]
    pcols = {c["name"] for c in prog["columns"]}
    assert "program_slot" in pcols and "program_id" in pcols


def test_duckdb_ddl_contains_program_slot_integer() -> None:
    mapping = load_mapping()
    creates = build_create_statements(mapping, "duckdb")
    joined = "\n".join(creates)
    assert '"program_slot"' in joined
    assert "INTEGER" in joined


def test_duckdb_ddl_fk_uses_no_action_not_cascade() -> None:
    mapping = load_mapping()
    creates = build_create_statements(mapping, "duckdb")
    joined = "\n".join(creates)
    assert "ON DELETE CASCADE" not in joined
    assert "ON DELETE NO ACTION" in joined
    assert '"certificates"' in joined
