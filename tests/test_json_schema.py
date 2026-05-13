"""JSON Schema: валидность примеров из конвертера."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import convert as c

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "json-schema" / "certificate-line.schema.json"
FIXTURES = ROOT / "tests" / "fixtures"
XML_SCHEMA = ROOT / "data-20160908-structure-20160713.xml"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schema)


def _one_row(tmp_path: Path, xml_name: str) -> dict:
    out = tmp_path / "o.jsonl"
    c.convert_many(
        [FIXTURES / xml_name],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=XML_SCHEMA,
    )
    line = out.read_text(encoding="utf-8").strip().splitlines()[0]
    return json.loads(line)


def test_schema_validates_minimal(validator: jsonschema.Draft202012Validator, tmp_path: Path) -> None:
    row = _one_row(tmp_path, "minimal.xml")
    validator.validate(row)


def test_schema_validates_multiple_supplements(
    validator: jsonschema.Draft202012Validator, tmp_path: Path
) -> None:
    row = _one_row(tmp_path, "multiple_supplements.xml")
    validator.validate(row)


def test_schema_rejects_missing_source_file(
    validator: jsonschema.Draft202012Validator,
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"Id": "x"})
