#!/usr/bin/env python3
"""Аудит корневого RegionName в JSONL сертификатов (одна строка = сертификат).

Счётчик ``outside_rf_pseudo_region`` — сколько строк с ``RegionName``, совпадающим с
константой псевдорегиона «за пределами РФ» (как в ``convert.CERTIFICATE_REGION_NAME_OUTSIDE_RF``).

При конвертации по умолчанию (``omit_outside_rf_region``) такие сертификаты **не попадают**
в JSONL, поэтому в аудите «свежего» файла этот счётчик часто **0**; ненулевой отчёт
``omitted_outside_rf_region`` смотрите в JSON ``--report`` у ``convert.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "dataset_region_audit.json"
_NULL_LABEL = "<null>"

# Синхронно с convert.CERTIFICATE_REGION_NAME_OUTSIDE_RF
_OUTSIDE_RF: str = (
    "образовательные учреждения, находящиеся за пределами Российской Федерации"
)


def _label(v: Any) -> str:
    if v is None:
        return _NULL_LABEL
    if isinstance(v, str):
        s = v.strip()
        return s if s else _NULL_LABEL
    return str(v)


def main() -> int:
    p = argparse.ArgumentParser(description="Аудит RegionName в JSONL сертификатов.")
    p.add_argument("jsonl", type=Path, help="Входной .jsonl")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON-отчёт (по умолчанию {_DEFAULT_OUT})",
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    total = 0
    reg = Counter()
    outside_rf = 0

    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            try:
                row = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            total += 1
            rn = row.get("RegionName")
            lab = _label(rn)
            reg[lab] += 1
            if isinstance(rn, str) and rn.strip() == _OUTSIDE_RF:
                outside_rf += 1

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    def _sorted_hist(c: Counter) -> dict[str, int]:
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    out = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Гистограмма корневого RegionName сертификата; "
            f"пусто/null — «{_NULL_LABEL}». Поле ``outside_rf_pseudo_region`` — число строк "
            "с псевдорегионом «за пределами РФ» в **данном** JSONL (при конвертации "
            "``convert.py`` по умолчанию такие сертификаты не пишутся; для полного снимка — "
            "``--include-outside-rf-region``)."
        ),
        "certificate_lines_total": total,
        "outside_rf_pseudo_region": outside_rf,
        "histograms": {
            "RegionName": _sorted_hist(reg),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Строк: {total}\n"
        f"Уникальных RegionName: {len(reg)}\n"
        f"Псевдорегион «за пределами РФ»: {outside_rf}\n"
        f"Отчёт: {args.output.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
