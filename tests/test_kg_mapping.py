"""Смоук-тест: kg/mapping.json парсится и содержит ожидаемую структуру."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "kg" / "mapping.json"


def test_kg_mapping_json_loads() -> None:
    data = json.loads(MAPPING.read_text(encoding="utf-8"))
    assert data.get("format_version") == 1
    kinds = {n["kind"] for n in data["node_kinds"]}
    assert kinds == {
        "Certificate",
        "Supplement",
        "Decision",
        "EducationalProgram",
        "ActualEducationOrganization",
    }
    preds = {e["predicate"] for e in data["edge_kinds"]}
    assert "hasSupplement" in preds
    assert "hasDecision" in preds
    assert "hasEducationalProgram" in preds
