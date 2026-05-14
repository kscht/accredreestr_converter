#!/usr/bin/env python3
"""Аудит корневых StatusName и TypeName в JSONL сертификатов (одна строка = сертификат).

Значения null/отсутствие ключа учитываются как отдельная метка ``<null>`` в гистограммах.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "dataset_status_audit.json"
_NULL_LABEL = "<null>"


def _label(v: Any) -> str:
    if v is None:
        return _NULL_LABEL
    if isinstance(v, str):
        s = v.strip()
        return s if s else _NULL_LABEL
    return str(v)


def main() -> int:
    p = argparse.ArgumentParser(description="Аудит StatusName и TypeName в JSONL сертификатов.")
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
    st = Counter()
    tn = Counter()

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
            st[_label(row.get("StatusName"))] += 1
            tn[_label(row.get("TypeName"))] += 1

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    def _sorted_hist(c: Counter) -> dict[str, int]:
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    out = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Гистограммы корневых полей сертификата StatusName и TypeName. "
            f"Пусто/null/отсутствие ключа — «{_NULL_LABEL}»."
        ),
        "certificate_lines_total": total,
        "histograms": {
            "StatusName": _sorted_hist(st),
            "TypeName": _sorted_hist(tn),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Строк: {total}\n"
        f"Уникальных StatusName: {len(st)}\n"
        f"Уникальных TypeName: {len(tn)}\n"
        f"Отчёт: {args.output.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
