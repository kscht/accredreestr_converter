"""Парсинг ответа OpenRouter и слияние записей (без сети)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _ROOT / "tools" / "draft_org_name_dictionary_openrouter.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("draft_org_name_dictionary_openrouter", _MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_json_plain_array() -> None:
    mod = _load_mod()
    text = '[{"raw": "А", "suggested_display": "Б"}]'
    v = mod._extract_json_value(text)
    assert v == [{"raw": "А", "suggested_display": "Б"}]


def test_extract_json_from_markdown_fence() -> None:
    mod = _load_mod()
    text = 'Вот результат:\n```json\n[{"raw": "X", "suggested_display": "Y"}]\n```\n'
    v = mod._extract_json_value(text)
    assert v == [{"raw": "X", "suggested_display": "Y"}]


def test_merge_entries_casefold_dedup() -> None:
    mod = _load_mod()
    a = [
        mod.normalize_dictionary_entry(
            {"raw": "МГУ", "by_model": {"m1": {"suggested_display": "Мгу"}}},
            legacy_flat_model=None,
        )
    ]
    b = [{"raw": "мгу", "suggested_display": "МГУ"}]
    m = mod.merge_entries(
        a,
        b,
        key_raw_casefold=True,
        legacy_flat_model_for_existing=None,
        new_batch_model="m1",
    )
    assert len(m) == 1
    assert m[0]["by_model"]["m1"]["suggested_display"] == "МГУ"


def test_normalize_migrates_legacy_flat() -> None:
    mod = _load_mod()
    e = mod.normalize_dictionary_entry(
        {"raw": "X", "suggested_display": "Y", "reason_short": "z"},
        legacy_flat_model="openai/x",
    )
    assert e["by_model"]["openai/x"]["suggested_display"] == "Y"
    assert e["by_model"]["openai/x"]["reason_short"] == "z"


def test_raws_missing_model_slot() -> None:
    mod = _load_mod()
    entries = [
        mod.normalize_dictionary_entry(
            {"raw": "A", "by_model": {"m1": {"suggested_display": "a"}}},
            legacy_flat_model=None,
        ),
        {"raw": "B", "by_model": {"m2": {"suggested_display": "b"}}},
    ]
    miss = mod.raws_missing_model_slot(entries, "m2", legacy_flat_model=None)
    assert miss == ["A"]
    miss_m1 = mod.raws_missing_model_slot(entries, "m1", legacy_flat_model=None)
    assert miss_m1 == ["B"]


def test_merge_accumulates_two_models() -> None:
    mod = _load_mod()
    a = [
        mod.normalize_dictionary_entry(
            {"raw": "A", "by_model": {"m1": {"suggested_display": "one"}}},
            legacy_flat_model=None,
        )
    ]
    b = [{"raw": "A", "suggested_display": "two"}]
    m = mod.merge_entries(
        a,
        b,
        key_raw_casefold=True,
        legacy_flat_model_for_existing=None,
        new_batch_model="m2",
    )
    assert m[0]["by_model"]["m1"]["suggested_display"] == "one"
    assert m[0]["by_model"]["m2"]["suggested_display"] == "two"


def test_collect_all_unique_from_jsonl_and_uniform_sample(tmp_path: Path) -> None:
    mod = _load_mod()
    p = tmp_path / "t.jsonl"
    row1 = {"EduOrgFullName": "AAA", "EduOrgShortName": "BBB"}
    row2 = {"EduOrgFullName": "AAA", "ActualEducationOrganization": {"FullName": "CCC"}}
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (row1, row2)) + "\n", encoding="utf-8")
    all_u = mod.collect_all_unique_from_jsonl(p, name_kind="all")
    assert all_u == ["AAA", "BBB", "CCC"]
    assert mod.collect_all_unique_from_jsonl(p, name_kind="full") == ["AAA", "CCC"]
    assert mod.collect_all_unique_from_jsonl(p, name_kind="short") == ["BBB"]
    s = mod.uniform_sample_strings(all_u, 2, random_seed=7)
    assert len(s) == 2
    assert set(s) <= set(all_u)
    assert mod.uniform_sample_strings(all_u, 10, random_seed=0) == all_u


def test_system_prompt_for_name_kind_distinct() -> None:
    mod = _load_mod()
    a = mod.system_prompt_for_name_kind("all")
    b = mod.system_prompt_for_name_kind("full")
    c = mod.system_prompt_for_name_kind("short")
    assert a != b and b != c and "кратк" in c and "полн" in b
