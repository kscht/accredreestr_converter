"""Diff словарей имён (без сети)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _ROOT / "tools" / "diff_org_name_dictionaries.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("diff_org_name_dictionaries", _MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pairwise_legacy_two_files(tmp_path: Path) -> None:
    mod = _load_mod()

    def dump(entries: list[dict], path: Path) -> None:
        path.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    dump(
        [
            {"raw": "X", "suggested_display": "1"},
            {"raw": "onlyA", "suggested_display": "a"},
        ],
        a,
    )
    dump(
        [
            {"raw": "X", "suggested_display": "2"},
            {"raw": "onlyB", "suggested_display": "b"},
        ],
        b,
    )
    ma, _ = mod._dictionary_meta_and_entries_map(a)
    mb, _ = mod._dictionary_meta_and_entries_map(b)
    r = mod._pairwise_legacy(ma, mb, sample_diff=10, model_key_a=None, model_key_b=None)
    assert r["counts"]["common_raw"] == 1
    assert r["counts"]["common_diff_suggested_display"] == 1
    assert r["counts"]["only_in_a"] == 1


def test_triple_summary(tmp_path: Path) -> None:
    mod = _load_mod()
    ma = {"x": {"raw": "X", "suggested_display": "1"}}
    mb = {"x": {"raw": "X", "suggested_display": "1"}}
    mc = {"x": {"raw": "X", "suggested_display": "2"}}
    t = mod._triple_summary(ma, mb, mc, sample_diff=10, model_key_a=None, model_key_b=None, model_key_c=None)
    assert t["keys_in_all_three"] == 1
    assert t["a_equals_b_not_c"] == 1


def test_pairwise_by_model_two_keys_in_one_blob(tmp_path: Path) -> None:
    mod = _load_mod()
    path = tmp_path / "merged.json"
    path.write_text(
        json.dumps(
            {
                "model": "m1",
                "entries": [
                    {
                        "raw": "X",
                        "by_model": {
                            "m1": {"suggested_display": "1"},
                            "m2": {"suggested_display": "2"},
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mm, _ = mod._dictionary_meta_and_entries_map(path)
    r = mod._pairwise_legacy(mm, mm, sample_diff=10, model_key_a="m1", model_key_b="m2")
    assert r["counts"]["common_raw"] == 1
    assert r["counts"]["common_diff_suggested_display"] == 1
    assert r["counts"]["common_same_suggested_display"] == 0
