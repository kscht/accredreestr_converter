"""Совместимость констант и кода с эталонным XML-описанием структуры."""

from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

import convert as c

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "specs" / "xml" / "data-20160908-structure-20160713.xml"


def test_schema_file_exists() -> None:
    assert SCHEMA.is_file()


def test_schema_parses() -> None:
    tree = etree.parse(str(SCHEMA))
    assert tree.getroot().tag.endswith("OpenData")
    assert tree.find(".//Certificate") is not None


def test_constants_subset_of_schema() -> None:
    tags = c.load_schema_tag_names(SCHEMA)
    for name in c.BOOL_FIELDS | c.DATE_FIELDS | c.ID_NUMBER_FIELDS:
        assert name in tags, f"Поле {name!r} не найдено в эталонном XML"
    for wrapper in c.COLLECTION_WRAPPERS:
        assert wrapper in tags, f"Обёртка {wrapper!r} не найдена в эталонном XML"
        child = c.COLLECTION_WRAPPERS[wrapper]
        assert child in tags, f"Элемент коллекции {child!r} не найден в эталонном XML"


def test_schema_can_be_converted(tmp_path: Path) -> None:
    out = tmp_path / "schema.jsonl"
    stats = c.convert_many(
        [SCHEMA],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1
    row = json.loads(lines[0])
    assert row.get("_source_file") == SCHEMA.name
    assert stats.per_file[SCHEMA.name]["processed"] >= 1
