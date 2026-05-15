#!/usr/bin/env python3
"""Словарь уникальных ``StatusName`` в JSONL реестра: на корне ``Certificate`` и в ``Supplements[]``.

В выгрузке не только «Действующее» / «Недействующее» — скрипт собирает **полный** набор строк,
гистограммы и **по одному примеру** на каждое уникальное значение (первое вхождение при обходе файла).

Пример::

    python tools/registry_status_vocab.py out/data.jsonl \\
        -o examples/registry_status_names_vocab.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "registry_status_names_vocab.json"
_NULL = "<null>"


def _label(v: Any) -> str:
    if v is None:
        return _NULL
    if isinstance(v, str):
        s = v.strip()
        return s if s else _NULL
    return str(v)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Уникальные StatusName на корне Certificate и в Supplements[] + примеры.",
    )
    p.add_argument("jsonl", type=Path, help="Входной JSONL (одна строка = сертификат)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON (по умолчанию {_DEFAULT_OUT})",
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    root_hist: Counter[str] = Counter()
    sup_hist: Counter[str] = Counter()
    root_example: dict[str, dict[str, Any]] = {}
    sup_example: dict[str, dict[str, Any]] = {}

    lines = 0
    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            lines += 1
            cid = row.get("Id")
            rs = _label(row.get("StatusName"))
            root_hist[rs] += 1
            if rs not in root_example and cid is not None:
                root_example[rs] = {
                    "certificate_id": cid,
                    "RegionName": row.get("RegionName"),
                    "EduOrgShortName": row.get("EduOrgShortName"),
                }

            for idx, sup in enumerate(row.get("Supplements") or []):
                if not isinstance(sup, dict):
                    continue
                ss = _label(sup.get("StatusName"))
                sup_hist[ss] += 1
                if ss not in sup_example and cid is not None:
                    sup_example[ss] = {
                        "certificate_id": cid,
                        "supplement_index": idx,
                        "certificate_StatusName": _label(row.get("StatusName")),
                        "Supplement_Number": sup.get("Number"),
                        "SerialNumber": sup.get("SerialNumber"),
                    }

    def _sorted_hist(c: Counter[str]) -> dict[str, int]:
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    root_keys = sorted(root_hist.keys(), key=lambda k: (-root_hist[k], k))
    sup_keys = sorted(sup_hist.keys(), key=lambda k: (-sup_hist[k], k))
    union = sorted(set(root_hist) | set(sup_hist), key=lambda k: (k == _NULL, k))

    out = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Уникальные строковые значения ``StatusName``: на корне ``Certificate`` и в элементах "
            "``Supplements[]``. Пустая строка / null / отсутствие ключа — метка «<null>». "
            "Для каждого уникального значения — одно первое вхождение в файле (``example_*``). "
            "В реестре не только «Действующее» и «Недействующее»; см. ``histograms``."
        ),
        "certificate_lines_total": lines,
        "histograms": {
            "certificate_StatusName": _sorted_hist(root_hist),
            "supplement_StatusName": _sorted_hist(sup_hist),
        },
        "unique_sorted": {
            "certificate_StatusName": root_keys,
            "supplement_StatusName": sup_keys,
            "union_sorted": union,
        },
        "examples_first_occurrence": {
            "certificate_StatusName": {k: root_example[k] for k in root_keys if k in root_example},
            "supplement_StatusName": {k: sup_example[k] for k in sup_keys if k in sup_example},
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Строк сертификатов: {lines}\n"
        f"Уникальных StatusName на корне: {len(root_hist)}\n"
        f"Уникальных StatusName в Supplements: {len(sup_hist)}\n"
        f"Файл: {args.output.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
