"""Тесты surreal_convert.import_surreal."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import convert as c
import pytest

from surreal_convert.import_surreal import (
    _level_key,
    _rec_id,
    _region_key,
    _relate,
    _surql_val,
    _upsert,
    import_surreal,
    iter_surql_for_certificate,
    load_kg_mapping,
)

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


@pytest.fixture()
def single_jsonl(tmp_path: Path) -> Path:
    out = tmp_path / "single.jsonl"
    c.convert_many(
        [FIXTURES / "single_supplement.xml"],
        out,
        merged=True,
        out_dir=tmp_path,
        progress_every=0,
        limit=None,
        strict=False,
        schema_path=SCHEMA,
    )
    return out


# --- unit helpers ---

def test_rec_id_basic() -> None:
    rid = _rec_id("certificate", "abc-123")
    assert rid == "certificate:`abc-123`"


def test_rec_id_escapes_backtick() -> None:
    rid = _rec_id("t", "a`b")
    assert rid == "t:`a\\`b`"


def test_surql_val_types() -> None:
    assert _surql_val(None) is None
    assert _surql_val(True) == "true"
    assert _surql_val(False) == "false"
    assert _surql_val(42) == "42"
    assert _surql_val(3.14) == "3.14"
    assert _surql_val("hello") == '"hello"'
    assert _surql_val('say "hi"') == '"say \\"hi\\""'


def test_surql_val_nan_inf() -> None:
    assert _surql_val(float("nan")) is None
    assert _surql_val(float("inf")) is None


def test_upsert_stmt() -> None:
    stmt = _upsert("certificate:`uuid`", {"StatusName": "Действующее", "IsFederal": True})
    assert stmt.startswith("UPSERT certificate:`uuid` SET")
    assert "IsFederal = true" in stmt
    assert 'StatusName = "Действующее"' in stmt
    assert stmt.endswith(";")


def test_relate_stmt() -> None:
    stmt = _relate("certificate:`c1`", "has_supplement", "supplement:`c1_s1`", "c1_s1")
    assert "UPSERT has_supplement:`c1_s1`" in stmt
    assert "in = certificate:`c1`" in stmt
    assert "out = supplement:`c1_s1`" in stmt


def test_level_key_stable() -> None:
    k1 = _level_key("Среднее общее образование")
    k2 = _level_key("Среднее общее образование")
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex


def test_region_key_stable() -> None:
    k1 = _region_key("г. Москва")
    k2 = _region_key("г. Москва")
    assert k1 == k2
    assert len(k1) == 64


# --- iter_surql_for_certificate ---

def test_iter_surql_minimal() -> None:
    mapping = load_kg_mapping()
    obj = {"Id": "test-uuid", "StatusName": "Действующее", "Supplements": [], "Decisions": []}
    stmts = list(iter_surql_for_certificate(mapping, obj))
    joined = "\n".join(stmts)
    assert "UPSERT certificate:`test-uuid`" in joined
    assert "uri" in joined


def test_iter_surql_no_id_skipped() -> None:
    mapping = load_kg_mapping()
    stmts = list(iter_surql_for_certificate(mapping, {"StatusName": "Действующее"}))
    assert stmts == []


def test_iter_surql_region() -> None:
    mapping = load_kg_mapping()
    obj = {
        "Id": "c1",
        "RegionName": "Свердловская область",
        "Supplements": [],
        "Decisions": [],
    }
    joined = "\n".join(iter_surql_for_certificate(mapping, obj))
    assert "UPSERT region:" in joined
    assert "in_region" in joined
    assert "Свердловская область" in joined


def test_iter_surql_supplement_and_programs() -> None:
    mapping = load_kg_mapping()
    obj = {
        "Id": "c1",
        "Supplements": [
            {
                "Id": "s1",
                "StatusName": "Действующее",
                "EducationalPrograms": [
                    {"Id": "p1", "EduLevelName": "СПО", "ProgrammName": "Программа А"},
                    {"Id": "p2", "EduLevelName": "НПО", "ProgrammName": "Программа Б"},
                ],
            }
        ],
        "Decisions": [],
    }
    stmts = list(iter_surql_for_certificate(mapping, obj))
    joined = "\n".join(stmts)
    assert "UPSERT supplement:" in joined
    assert "has_supplement" in joined
    assert "educational_program:" in joined
    assert "has_educational_program" in joined
    assert "educational_level:" in joined
    assert "has_education_level" in joined
    # Two programs → two has_education_level edges
    assert joined.count("has_education_level") == 2


def test_iter_surql_aeo_and_offers() -> None:
    mapping = load_kg_mapping()
    obj = {
        "Id": "c1",
        "Supplements": [
            {
                "Id": "s1",
                "EducationalPrograms": [
                    {"Id": "p1", "EduLevelName": "ВО — бакалавриат"},
                ],
                "ActualEducationOrganization": {
                    "Id": "a1",
                    "FullName": "Университет",
                    "RegionName": "г. Москва",
                },
            }
        ],
        "ActualEducationOrganization": {
            "Id": "root-a",
            "FullName": "Корневая ОО",
        },
        "Decisions": [],
    }
    joined = "\n".join(iter_surql_for_certificate(mapping, obj))
    assert "actual_education_organization:" in joined
    assert "has_actual_education_organization" in joined
    assert "offers_education_level" in joined
    assert "in_region" in joined
    # RegionName не должна попасть в SET полей AEO
    assert "RegionName" not in joined


def test_iter_surql_decision_skips_null_id() -> None:
    mapping = load_kg_mapping()
    obj = {
        "Id": "c1",
        "Supplements": [],
        "Decisions": [
            {"DecisionTypeName": "Выдача", "OrderDocumentNumber": "123"},  # no Id
            {"Id": "d1", "DecisionTypeName": "Аннулирование"},
        ],
    }
    stmts = list(iter_surql_for_certificate(mapping, obj))
    joined = "\n".join(stmts)
    # Only one decision node (d1), not the one without Id
    assert joined.count("UPSERT decision:") == 1
    assert "has_decision" in joined


def test_iter_surql_multiple_supplements(ms_jsonl: Path) -> None:
    mapping = load_kg_mapping()
    obj = json.loads(ms_jsonl.read_text(encoding="utf-8").strip())
    stmts = list(iter_surql_for_certificate(mapping, obj))
    joined = "\n".join(stmts)
    assert joined.count("UPSERT supplement:") >= 2
    assert "has_supplement" in joined


def test_iter_surql_idempotent_relations() -> None:
    """Рёбра используют UPSERT с детерминированным ключом — повторный вызов даёт те же операторы."""
    mapping = load_kg_mapping()
    obj = {"Id": "c1", "Supplements": [{"Id": "s1", "EducationalPrograms": []}], "Decisions": []}
    stmts1 = list(iter_surql_for_certificate(mapping, obj))
    stmts2 = list(iter_surql_for_certificate(mapping, obj))
    assert stmts1 == stmts2


# --- module help ---

def test_import_surreal_module_help() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "surreal_convert.import_surreal", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "--url" in r.stdout
    assert "--recreate" in r.stdout
    assert "--batch" in r.stdout


# --- live integration test (opt-in) ---

@pytest.mark.skipif(
    os.environ.get("ACCRED_SURREAL_LIVE") != "1",
    reason="Пропущен: задайте ACCRED_SURREAL_LIVE=1 и запустите SurrealDB на ws://localhost:8000",
)
def test_import_surreal_live(single_jsonl: Path) -> None:
    url = os.environ.get("ACCRED_SURREAL_URL", "ws://localhost:8000")
    count = import_surreal(
        single_jsonl,
        url=url,
        ns="test_accred",
        db="test_accred",
        recreate=True,
        limit=5,
    )
    assert count > 0
