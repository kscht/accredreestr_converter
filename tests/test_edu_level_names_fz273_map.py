"""specs/edu_level_names_fz273_map.json — структура и согласованность с edu_level_names_vocab.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "specs" / "edu_level_names_fz273_map.json"
VOCAB_PATH = ROOT / "specs" / "edu_level_names_vocab.json"

_ALLOWED_MAPPING_KINDS = frozenset(
    {
        "identity",
        "abbreviation_to_full",
        "obsolete_name_redirect",
        "abolished_level_reclassified",
        "abolished_subkind_folded",
        "ambiguous_umbrella_term",
        "umbrella_term_mapped",
        "manual_review_basis_ugs",
        "manual_review_basis_region",
        "technical_placeholder",
    }
)
_ALLOWED_NORM_STATUS = frozenset({"OK", "REQUIRES_MANUAL_REVIEW", "NO_CANONICAL_TARGET"})


def _load_map() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def test_fz273_map_loads_and_covers_vocab() -> None:
    m = _load_map()
    assert m.get("format_version") == 1
    assert m.get("schema_id") == "edu_level_names_fz273_map"
    canon = m["canonical_edu_level_names_fz273"]
    assert len(canon) == len(set(canon)), "canonical_edu_level_names_fz273: дубликаты"

    entries = m["entries"]
    by_source: dict[str, dict] = {}
    for e in entries:
        src = e["source_registry_level_name"]
        assert src not in by_source, f"дубликат source: {src!r}"
        by_source[src] = e
        assert e["mapping_kind"] in _ALLOWED_MAPPING_KINDS, e
        assert e["norm_status"] in _ALLOWED_NORM_STATUS, e
        tgt = e.get("target_edu_level_name")
        if tgt is not None:
            assert tgt in set(canon), f"цель вне канона: {src!r} -> {tgt!r}"

    vocab = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    names = vocab["unique_edu_level_names"]
    assert isinstance(names, list)
    missing = [n for n in names if n not in by_source]
    assert not missing, f"нет записи маппинга для: {missing}"
    extra = [s for s in by_source if s not in names]
    assert not extra, f"лишние source не из vocab: {extra}"


def test_fz273_map_expected_null_and_obschee_resolved() -> None:
    m = _load_map()
    by_source = {e["source_registry_level_name"]: e for e in m["entries"]}
    ob = by_source["Общее образование"]
    assert ob["target_edu_level_name"] == "Основное общее образование"
    assert ob["norm_status"] == "OK"
    assert ob["mapping_kind"] == "umbrella_term_mapped"

    e_nd = by_source["Не определен"]
    assert e_nd["target_edu_level_name"] is None
    assert e_nd["norm_status"] == "NO_CANONICAL_TARGET"

    prof_or = by_source["Профессиональное образование"]
    assert prof_or["target_edu_level_name"] == "Среднее профессиональное образование"
    assert prof_or["norm_status"] == "OK"
    assert prof_or["mapping_kind"] == "manual_review_basis_region"

    prof_ob = by_source["Профессиональное обучение"]
    assert prof_ob["target_edu_level_name"] == "Среднее профессиональное образование"
    assert prof_ob["norm_status"] == "OK"
    assert prof_ob["mapping_kind"] == "manual_review_basis_ugs"
