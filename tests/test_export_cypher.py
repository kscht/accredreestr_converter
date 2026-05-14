"""Экспорт JSONL → Cypher по specs/kg/mapping.json."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import convert as c
import pytest

from cypher_convert.export_cypher import export_jsonl_to_cypher, iter_cypher_for_certificate, load_kg_mapping

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


def test_export_cypher_module_help() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "cypher_convert.export_cypher", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "--output" in r.stdout
    assert "--semicolon" in r.stdout
    assert "--clear-graph" in r.stdout


def test_iter_cypher_multiple_supplements(ms_jsonl: Path) -> None:
    mapping = load_kg_mapping()
    line = ms_jsonl.read_text(encoding="utf-8").strip()
    import json

    obj = json.loads(line)
    lines = list(iter_cypher_for_certificate(mapping, obj))
    joined = "\n".join(lines)
    assert "MERGE (c:Certificate" in joined
    assert "MERGE (s0:Supplement" in joined
    assert "MERGE (s1:Supplement" in joined
    assert "HAS_SUPPLEMENT" in joined


def test_iter_cypher_educational_levels_and_org_offers() -> None:
    mapping = load_kg_mapping()
    obj = {
        "Id": "c1",
        "IsFederal": False,
        "Supplements": [
            {
                "Id": "s1",
                "EducationalPrograms": [
                    {"Id": "p1", "EduLevelName": "СПО", "ProgrammName": "Прог А"},
                    {"Id": "p2", "EduLevelName": "НПО", "ProgrammName": "Прог Б"},
                ],
                "ActualEducationOrganization": {
                    "Id": "a1",
                    "FullName": "Школа приложения",
                },
            }
        ],
        "ActualEducationOrganization": {
            "Id": "root-a",
            "FullName": "Корневая ОО",
        },
    }
    joined = "\n".join(iter_cypher_for_certificate(mapping, obj))
    assert "EducationalLevel" in joined
    assert joined.count("HAS_EDUCATION_LEVEL") == 2
    assert joined.count("OFFERS_EDUCATION_LEVEL") == 4
    assert "p_si0_0.EduLevelName" not in joined
    assert "p_si0_1.EduLevelName" not in joined


def test_iter_cypher_region_and_aeo_ogrn() -> None:
    mapping = load_kg_mapping()
    obj = {
        "Id": "c1",
        "RegionName": "Свердловская область",
        "IsFederal": False,
        "Supplements": [],
        "ActualEducationOrganization": {
            "Id": "org1",
            "RegionName": "Свердловская область",
            "OGRN": "1026600786783",
            "FullName": "Школа",
        },
    }
    joined = "\n".join(iter_cypher_for_certificate(mapping, obj))
    assert "MERGE (rg0:Region" in joined
    assert joined.count("IN_REGION") == 2
    assert "SET c.RegionName" not in joined
    assert "SET a0.RegionName" not in joined
    assert "SET a0.OGRN" in joined


def test_export_jsonl_to_cypher_file(ms_jsonl: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.cypher"
    export_jsonl_to_cypher(ms_jsonl, out, mapping_path=None, limit=None)
    text = out.read_text(encoding="utf-8")
    assert "Certificate" in text
    assert "HAS_SUPPLEMENT" in text


def test_export_jsonl_to_cypher_semicolon(ms_jsonl: Path, tmp_path: Path) -> None:
    out = tmp_path / "semi.cypher"
    export_jsonl_to_cypher(
        ms_jsonl,
        out,
        mapping_path=None,
        limit=None,
        semicolon_after_certificate=True,
    )
    text = out.read_text(encoding="utf-8")
    assert "multi-statement" in text
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("//")]
    assert lines[-1].endswith(";")


def test_export_jsonl_prepends_clear_graph(ms_jsonl: Path, tmp_path: Path) -> None:
    out = tmp_path / "clear.cypher"
    export_jsonl_to_cypher(
        ms_jsonl,
        out,
        mapping_path=None,
        limit=1,
        clear_database_first=True,
    )
    text = out.read_text(encoding="utf-8")
    assert "DETACH DELETE" in text
    assert text.index("DETACH DELETE") < text.index("certificate line")
