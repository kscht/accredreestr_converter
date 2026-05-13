"""Смоук-тест: specs/sql/mapping.json парсится и содержит ожидаемые таблицы."""

import json
from pathlib import Path

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
