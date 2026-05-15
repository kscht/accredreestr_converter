#!/usr/bin/env python3
"""Аудит JSONL: сертификаты и приложения с «пустым» StatusName.

«Пустой» статус (как в гистограммах ``audit_dataset_status`` / ``registry_status_vocab``):

- на корне ``Certificate``: ключа ``StatusName`` нет, значение ``null``, либо строка из одних пробелов;
- в элементе ``Supplements[]``: то же для ``StatusName`` у словаря-приложения.

По умолчанию пишет JSON-сводку с числами и короткими примерами (см. ``--limit``).
Опционально потоково пишет **полные** строки входного JSONL:

- ``--problem-jsonl`` / ``-p`` [PATH] — сертификат, у которого пуст **корневой** ``StatusName`` **или**
  пуст ``StatusName`` хотя бы у одного элемента ``Supplements[]`` (объединение). Без PATH после ``-p``
  выход: ``examples/certificate_lines_StatusName_nullish.jsonl``;
- ``-f`` / ``--full-jsonl`` — только пустой **корневой** ``StatusName`` (подмножество ``-p``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "dataset_null_statusname_audit.json"
_DEFAULT_PROBLEM_JSONL = _ROOT / "examples" / "certificate_lines_StatusName_nullish.jsonl"

NullishKind = Literal["missing", "json_null", "empty_string"]


def _root_status_nullish(row: dict[str, Any]) -> NullishKind | None:
    if "StatusName" not in row:
        return "missing"
    v = row["StatusName"]
    if v is None:
        return "json_null"
    if isinstance(v, str) and not v.strip():
        return "empty_string"
    return None


def _supplement_status_nullish(sup: dict[str, Any]) -> NullishKind | None:
    if "StatusName" not in sup:
        return "missing"
    v = sup["StatusName"]
    if v is None:
        return "json_null"
    if isinstance(v, str) and not v.strip():
        return "empty_string"
    return None


def main() -> int:
    p = argparse.ArgumentParser(
        description="Аудит JSONL: записи с пустым/null StatusName на корне и в Supplements[].",
    )
    p.add_argument("jsonl", type=Path, help="Входной .jsonl (одна строка = сертификат)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON-отчёт (по умолчанию {_DEFAULT_OUT})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=200,
        metavar="N",
        help="Не больше N примеров в каждом из блоков examples_* (0 = без примеров, только счётчики)",
    )
    p.add_argument(
        "-f",
        "--full-jsonl",
        type=Path,
        default=None,
        metavar="PATH",
        help="Дополнительно записать полные строки входа, где пуст только корневой StatusName",
    )
    p.add_argument(
        "-p",
        "--problem-jsonl",
        nargs="?",
        const=_DEFAULT_PROBLEM_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "Полные строки входа: пустой корневой StatusName и/или пустой StatusName в Supplements[]. "
            f"Флаг без PATH — запись в {_DEFAULT_PROBLEM_JSONL.relative_to(_ROOT)}"
        ),
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2
    if args.limit < 0:
        print("--limit не может быть отрицательным", file=sys.stderr)
        return 2

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    total = 0
    root_null_lines = 0
    root_by_kind: dict[str, int] = {"missing": 0, "json_null": 0, "empty_string": 0}
    sup_null_hits = 0
    lines_with_sup_null = 0

    examples_root: list[dict[str, Any]] = []
    examples_sup: list[dict[str, Any]] = []

    full_fh = args.full_jsonl.open("w", encoding="utf-8", newline="\n") if args.full_jsonl else None
    problem_fh = args.problem_jsonl.open("w", encoding="utf-8", newline="\n") if args.problem_jsonl else None
    union_lines = 0

    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            s = raw_line.strip()
            if not s:
                continue
            total += 1
            try:
                row = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue

            rk = _root_status_nullish(row)
            if rk is not None:
                root_null_lines += 1
                root_by_kind[rk] += 1
                if full_fh is not None:
                    full_fh.write(raw_line)
                if len(examples_root) < args.limit:
                    cid = row.get("Id")
                    examples_root.append(
                        {
                            "certificate_id": cid,
                            "input_line_number": total,
                            "StatusName_kind": rk,
                            "TypeName": row.get("TypeName"),
                            "RegionName": row.get("RegionName"),
                            "EduOrgShortName": row.get("EduOrgShortName"),
                        }
                    )

            sups = row.get("Supplements")
            line_has_sup_null = False
            if isinstance(sups, list):
                for idx, sup in enumerate(sups):
                    if not isinstance(sup, dict):
                        continue
                    sk = _supplement_status_nullish(sup)
                    if sk is None:
                        continue
                    sup_null_hits += 1
                    line_has_sup_null = True
                    if len(examples_sup) < args.limit:
                        examples_sup.append(
                            {
                                "certificate_id": row.get("Id"),
                                "input_line_number": total,
                                "supplement_index": idx,
                                "StatusName_kind": sk,
                                "Supplement_Number": sup.get("Number"),
                                "SerialNumber": sup.get("SerialNumber"),
                                "certificate_StatusName": row.get("StatusName"),
                            }
                        )
            if line_has_sup_null:
                lines_with_sup_null += 1

            if rk is not None or line_has_sup_null:
                union_lines += 1
                if problem_fh is not None:
                    problem_fh.write(raw_line)

    if full_fh is not None:
        full_fh.close()
    if problem_fh is not None:
        problem_fh.close()

    out: dict[str, Any] = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Сертификаты с пустым корневым StatusName (нет ключа / null / пустая строка); "
            "отдельно — вхождения пустого StatusName в элементах Supplements[]. "
            "Полные строки: -p/--problem-jsonl (корень или supplement), -f/--full-jsonl (только корень)."
        ),
        "certificate_lines_total": total,
        "root_StatusName_nullish_lines": root_null_lines,
        "root_StatusName_nullish_by_kind": dict(sorted(root_by_kind.items())),
        "supplement_StatusName_nullish_hits": sup_null_hits,
        "certificate_lines_with_any_supplement_StatusName_nullish": lines_with_sup_null,
        "certificate_lines_with_StatusName_nullish_root_or_supplement_union": union_lines,
        "problem_jsonl_output": str(args.problem_jsonl.resolve()) if args.problem_jsonl else None,
        "examples_root_StatusName_nullish": examples_root,
        "examples_supplement_StatusName_nullish": examples_sup,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Строк сертификатов: {total}\n"
        f"С пустым корневым StatusName: {root_null_lines}\n"
        f"  по видам: {root_by_kind}\n"
        f"Пустых StatusName в Supplements[] (всего вхождений): {sup_null_hits}\n"
        f"Сертификатов, где есть хотя бы одно такое приложение: {lines_with_sup_null}\n"
        f"Сертификатов (строк) с проблемой на корне и/или в supplement: {union_lines}\n"
        f"Отчёт: {args.output.resolve()}"
        + (f"\nПолные строки (корень): {args.full_jsonl.resolve()}" if args.full_jsonl else "")
        + (
            f"\nПолные строки (корень или supplement): {args.problem_jsonl.resolve()}"
            if args.problem_jsonl
            else ""
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
