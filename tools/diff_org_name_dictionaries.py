#!/usr/bin/env python3
"""Сравнить JSON черновики словаря (формат ``draft_org_name_dictionary_openrouter``).

Сопоставление по ``raw`` (``casefold``). Два файла — отчёт как раньше. С ``--path-c`` —
третий словарь (например ``deepseek/deepseek-v4-flash`` на OpenRouter): блоки ``pairwise``
(A↔B, A↔C, B↔C) и ``triple_on_common_raw``.

Пример (два файла или один merged с ``by_model``; для одного файла укажите ``--model-a`` и ``--model-b``)::

    python tools/diff_org_name_dictionaries.py \\
        out/org_name_dictionary_draft_openrouter.json \\
        out/org_name_dictionary_draft_openrouter.prev.json \\
        -o out/org_name_dictionary_diff_report.json

    python tools/diff_org_name_dictionaries.py \\
        out/org_name_dictionary_draft_openrouter.json \\
        out/org_name_dictionary_draft_openrouter.json \\
        --model-a openai/gpt-4o-mini \\
        --model-b deepseek/deepseek-v4-flash \\
        -o out/org_name_dictionary_diff_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def suggested_display_for_diff(entry: dict[str, Any], model_key: str | None) -> Any:
    """У плоского формата — верхний ``suggested_display``; у v2 — из ``by_model[model_key]``."""
    bm = entry.get("by_model")
    if isinstance(bm, dict) and bm:
        if model_key and model_key in bm:
            inner = bm[model_key]
            return inner.get("suggested_display") if isinstance(inner, dict) else None
        if not model_key and len(bm) == 1:
            inner = next(iter(bm.values()))
            return inner.get("suggested_display") if isinstance(inner, dict) else None
        return None
    return entry.get("suggested_display")


def _dictionary_meta_and_entries_map(path: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    blob = json.loads(path.read_text(encoding="utf-8"))
    entries = blob.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: нет entries[]")
    hint: str | None = None
    for k in ("model_last_run", "model"):
        v = blob.get(k)
        if isinstance(v, str) and v.strip():
            hint = v.strip()
            break
    out: dict[str, dict[str, Any]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        raw = e.get("raw")
        if not isinstance(raw, str) or not raw.strip():
            continue
        out[raw.casefold()] = e
    return out, hint


def _pairwise_legacy(
    ma: dict[str, dict[str, Any]],
    mb: dict[str, dict[str, Any]],
    *,
    sample_diff: int,
    model_key_a: str | None,
    model_key_b: str | None,
) -> dict[str, Any]:
    """Формат отчёта A vs B как в оригинале (path_a/path_b оборачивают снаружи)."""
    keys_a = set(ma)
    keys_b = set(mb)
    only_a = keys_a - keys_b
    only_b = keys_b - keys_a
    common = keys_a & keys_b
    same_sd = 0
    diff_sd = 0
    diff_examples: list[dict[str, Any]] = []
    for k in common:
        sa = suggested_display_for_diff(ma[k], model_key_a)
        sb = suggested_display_for_diff(mb[k], model_key_b)
        if isinstance(sa, str) and isinstance(sb, str) and sa == sb:
            same_sd += 1
        else:
            diff_sd += 1
            if len(diff_examples) < max(0, int(sample_diff)):
                diff_examples.append(
                    {
                        "raw": ma[k].get("raw"),
                        "suggested_display_a": sa,
                        "suggested_display_b": sb,
                    }
                )

    return {
        "counts": {
            "entries_a": len(ma),
            "entries_b": len(mb),
            "only_in_a": len(only_a),
            "only_in_b": len(only_b),
            "common_raw": len(common),
            "common_same_suggested_display": same_sd,
            "common_diff_suggested_display": diff_sd,
        },
        "sample_only_in_a_raw": [ma[k].get("raw") for k in sorted(only_a)[:40]],
        "sample_only_in_b_raw": [mb[k].get("raw") for k in sorted(only_b)[:40]],
        "sample_suggested_display_diffs": diff_examples,
    }


def _pairwise_named(
    ma: dict[str, dict[str, Any]],
    mb: dict[str, dict[str, Any]],
    *,
    label_left: str,
    label_right: str,
    sample_diff: int,
    model_key_a: str | None,
    model_key_b: str | None,
) -> dict[str, Any]:
    keys_a = set(ma)
    keys_b = set(mb)
    only_a = keys_a - keys_b
    only_b = keys_b - keys_a
    common = keys_a & keys_b
    same_sd = 0
    diff_sd = 0
    diff_examples: list[dict[str, Any]] = []
    for k in common:
        sa = suggested_display_for_diff(ma[k], model_key_a)
        sb = suggested_display_for_diff(mb[k], model_key_b)
        if isinstance(sa, str) and isinstance(sb, str) and sa == sb:
            same_sd += 1
        else:
            diff_sd += 1
            if len(diff_examples) < max(0, int(sample_diff)):
                diff_examples.append(
                    {
                        "raw": ma[k].get("raw"),
                        f"suggested_display_{label_left}": sa,
                        f"suggested_display_{label_right}": sb,
                    }
                )

    return {
        "counts": {
            f"entries_{label_left}": len(ma),
            f"entries_{label_right}": len(mb),
            f"only_in_{label_left}": len(only_a),
            f"only_in_{label_right}": len(only_b),
            "common_raw": len(common),
            "common_same_suggested_display": same_sd,
            "common_diff_suggested_display": diff_sd,
        },
        f"sample_only_in_{label_left}_raw": [ma[k].get("raw") for k in sorted(only_a)[:40]],
        f"sample_only_in_{label_right}_raw": [mb[k].get("raw") for k in sorted(only_b)[:40]],
        "sample_suggested_display_diffs": diff_examples,
    }


def _triple_summary(
    ma: dict[str, dict[str, Any]],
    mb: dict[str, dict[str, Any]],
    mc: dict[str, dict[str, Any]],
    *,
    sample_diff: int,
    model_key_a: str | None,
    model_key_b: str | None,
    model_key_c: str | None,
) -> dict[str, Any]:
    ka, kb, kc = set(ma), set(mb), set(mc)
    all_three = ka & kb & kc
    n = len(all_three)
    all_same = ab_same_not_c = ac_same_not_b = bc_same_not_a = all_diff = 0
    examples_all_diff: list[dict[str, Any]] = []
    examples_ab_agree: list[dict[str, Any]] = []
    for k in all_three:
        sa = suggested_display_for_diff(ma[k], model_key_a)
        sb = suggested_display_for_diff(mb[k], model_key_b)
        sc = suggested_display_for_diff(mc[k], model_key_c)
        if not all(isinstance(x, str) for x in (sa, sb, sc)):
            continue
        if sa == sb == sc:
            all_same += 1
        elif sa == sb != sc:
            ab_same_not_c += 1
            if len(examples_ab_agree) < min(20, sample_diff):
                examples_ab_agree.append({"raw": ma[k].get("raw"), "a_and_b": sa, "c_only": sc})
        elif sa == sc != sb:
            ac_same_not_b += 1
        elif sb == sc != sa:
            bc_same_not_a += 1
        else:
            all_diff += 1
            if len(examples_all_diff) < min(40, sample_diff):
                examples_all_diff.append(
                    {"raw": ma[k].get("raw"), "suggested_display_a": sa, "suggested_display_b": sb, "suggested_display_c": sc}
                )

    return {
        "keys_in_all_three": n,
        "all_three_same_suggested_display": all_same,
        "a_equals_b_not_c": ab_same_not_c,
        "a_equals_c_not_b": ac_same_not_b,
        "b_equals_c_not_a": bc_same_not_a,
        "all_three_pairwise_different_suggested_display": all_diff,
        "sample_all_three_differ": examples_all_diff,
        "sample_a_and_b_agree_c_differs": examples_ab_agree,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Diff двух или трёх org_name_dictionary JSON.")
    p.add_argument("path_a", type=Path, help="База (напр. openai/gpt-4o-mini)")
    p.add_argument("path_b", type=Path, help="Второй словарь")
    p.add_argument(
        "--path-c",
        type=Path,
        default=None,
        help="Третий словарь (напр. deepseek/deepseek-v4-flash)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="JSON-отчёт; без флага — только stdout (кратко)",
    )
    p.add_argument(
        "--sample-diff",
        type=int,
        default=80,
        metavar="N",
        help="Сколько примеров отличий suggested_display на пару",
    )
    p.add_argument(
        "--model-a",
        type=str,
        default=None,
        help="Ключ модели в by_model для path_a (иначе из JSON: model_last_run/model, иначе один ключ в by_model)",
    )
    p.add_argument(
        "--model-b",
        type=str,
        default=None,
        help="То же для path_b",
    )
    p.add_argument(
        "--model-c",
        type=str,
        default=None,
        help="То же для path_c",
    )
    args = p.parse_args()
    paths = [args.path_a, args.path_b]
    if args.path_c is not None:
        paths.append(args.path_c)
    for path in paths:
        if not path.is_file():
            print(f"Нет файла: {path}", file=sys.stderr)
            return 2

    ma, hint_a = _dictionary_meta_and_entries_map(args.path_a)
    mb, hint_b = _dictionary_meta_and_entries_map(args.path_b)
    mk_a = (args.model_a if args.model_a is not None else hint_a) or None
    mk_b = (args.model_b if args.model_b is not None else hint_b) or None
    if isinstance(mk_a, str):
        mk_a = mk_a.strip() or None
    if isinstance(mk_b, str):
        mk_b = mk_b.strip() or None

    if args.path_c is None:
        report = {
            "path_a": str(args.path_a),
            "path_b": str(args.path_b),
            "model_key_a": mk_a,
            "model_key_b": mk_b,
            **_pairwise_legacy(ma, mb, sample_diff=args.sample_diff, model_key_a=mk_a, model_key_b=mk_b),
        }
    else:
        mc, hint_c = _dictionary_meta_and_entries_map(args.path_c)
        mk_c = (args.model_c if args.model_c is not None else hint_c) or None
        if isinstance(mk_c, str):
            mk_c = mk_c.strip() or None
        report = {
            "path_a": str(args.path_a),
            "path_b": str(args.path_b),
            "path_c": str(args.path_c),
            "model_key_a": mk_a,
            "model_key_b": mk_b,
            "model_key_c": mk_c,
            "pairwise": {
                "a_vs_b": _pairwise_legacy(
                    ma, mb, sample_diff=args.sample_diff, model_key_a=mk_a, model_key_b=mk_b
                ),
                "a_vs_c": _pairwise_named(
                    ma,
                    mc,
                    label_left="a",
                    label_right="c",
                    sample_diff=args.sample_diff,
                    model_key_a=mk_a,
                    model_key_b=mk_c,
                ),
                "b_vs_c": _pairwise_named(
                    mb,
                    mc,
                    label_left="b",
                    label_right="c",
                    sample_diff=args.sample_diff,
                    model_key_a=mk_b,
                    model_key_b=mk_c,
                ),
            },
            "triple_on_common_raw": _triple_summary(
                ma,
                mb,
                mc,
                sample_diff=args.sample_diff,
                model_key_a=mk_a,
                model_key_b=mk_b,
                model_key_c=mk_c,
            ),
        }

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Отчёт: {args.output}", file=sys.stderr)
    else:
        if args.path_c is None:
            print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
        else:
            print(json.dumps(report["triple_on_common_raw"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
