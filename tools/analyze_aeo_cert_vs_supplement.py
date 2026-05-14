#!/usr/bin/env python3
"""Сравнение Id у ActualEducationOrganization на корне Certificate и в Supplements[].

Потоковый обход JSONL: считает расхождения; собирает **все** строки с расхождениями
в порядке следования во входном файле (не случайная выборка) и записывает срезы
``sample_10.jsonl`` … ``sample_5000.jsonl`` в каталог (как у generate_test_jsonl_samples,
но строки — первые N из пула «интересных» записей).

Вход — обычно JSONL из ``convert.py`` (типичный компактный вывод по умолчанию).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SIZES = (10, 50, 100, 500, 5000)


def _aeo_id(obj: dict[str, Any] | None) -> str | None:
    if not isinstance(obj, dict):
        return None
    i = obj.get("Id")
    if i is None:
        return None
    s = str(i).strip()
    return s or None


def _interesting_line(
    obj: dict[str, Any],
    root_id: str | None,
    sup_ids: list[tuple[str, str]],
) -> bool:
    """Строка JSONL попадает в тестовый датасет: корень ≠ приложение или разные AEO между приложениями."""
    if root_id is not None and sup_ids:
        if not all(aid == root_id for _, aid in sup_ids):
            return True
    if root_id is None and sup_ids:
        unique = {aid for _, aid in sup_ids}
        if len(unique) > 1:
            return True
    return False


def _mismatch_note(
    total: int,
    obj: dict[str, Any],
    root_id: str | None,
    sup_ids: list[tuple[str, str]],
) -> str:
    if root_id is not None and sup_ids and not all(aid == root_id for _, aid in sup_ids):
        bad = [(x, y) for x, y in sup_ids if y != root_id]
        return (
            f"строка~{total} cert.Id={obj.get('Id')} root_AEO={root_id} "
            f"не совпали приложения={bad[:8]}"
        )
    return (
        f"строка~{total} cert.Id={obj.get('Id')} "
        f"AEO по приложениям (разные Id)={sup_ids[:12]}"
    )


def _write_sample_files(
    out_dir: Path,
    lines: list[str],
    sizes: list[int],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for n in sizes:
        out_path = out_dir / f"sample_{n}.jsonl"
        chunk = lines[:n]
        with out_path.open("w", encoding="utf-8", newline="\n") as fh:
            for line in chunk:
                fh.write(line + "\n")


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Сравнить Id AEO на сертификате и в приложениях; "
            "опционально записать детерминированные sample_*.jsonl из расхождений."
        ),
    )
    p.add_argument("jsonl", type=Path, help="Путь к .jsonl")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Обработать не более N непустых строк",
    )
    p.add_argument(
        "--no-samples",
        action="store_true",
        help="Не записывать sample_*.jsonl (только сводка в stdout)",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=_ROOT / "examples" / "jsonl_samples_aeo_mismatch",
        help="Каталог для sample_10.jsonl, … (по умолчанию examples/jsonl_samples_aeo_mismatch)",
    )
    p.add_argument(
        "--sizes",
        type=str,
        default=",".join(map(str, _DEFAULT_SIZES)),
        help="Размеры файлов через запятую (по умолчанию 10,50,100,500,5000)",
    )
    p.add_argument(
        "--print-examples",
        type=int,
        default=0,
        metavar="K",
        help="Дополнительно вывести в stdout первые K текстовых описаний расхождений (0 = не выводить)",
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    try:
        sizes = [int(x.strip()) for x in args.sizes.split(",") if x.strip()]
    except ValueError:
        print("Некорректный --sizes", file=sys.stderr)
        return 2
    if any(n < 1 for n in sizes):
        print("Все размеры в --sizes должны быть >= 1", file=sys.stderr)
        return 2

    kprint = max(0, args.print_examples)

    total = 0
    root_aeo_present = 0
    any_sup_aeo_present = 0
    both_present = 0
    all_sup_match_root_when_root = 0
    mismatch_vs_root = 0

    no_root_but_sup_aeo = 0
    no_root_all_sup_same_aeo = 0
    cross_sup_mismatch = 0

    interesting_lines: list[str] = []
    print_notes: list[str] = []

    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            total += 1
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            root_id = _aeo_id(obj.get("ActualEducationOrganization"))
            if root_id is not None:
                root_aeo_present += 1

            sup_ids: list[tuple[str, str]] = []
            for sup in obj.get("Supplements") or []:
                if not isinstance(sup, dict):
                    continue
                sid = sup.get("Id")
                aid = _aeo_id(sup.get("ActualEducationOrganization"))
                if aid is not None:
                    sup_ids.append((str(sid) if sid is not None else "?", aid))

            if sup_ids:
                any_sup_aeo_present += 1

            if root_id is not None and sup_ids:
                both_present += 1
                if all(aid == root_id for _, aid in sup_ids):
                    all_sup_match_root_when_root += 1
                else:
                    mismatch_vs_root += 1

            if root_id is None and sup_ids:
                no_root_but_sup_aeo += 1
                unique = {aid for _, aid in sup_ids}
                if len(unique) == 1:
                    no_root_all_sup_same_aeo += 1
                else:
                    cross_sup_mismatch += 1

            if _interesting_line(obj, root_id, sup_ids):
                interesting_lines.append(s)
                if len(print_notes) < kprint:
                    print_notes.append(_mismatch_note(total, obj, root_id, sup_ids))

            if args.limit is not None and total >= args.limit:
                break

    print("=== ActualEducationOrganization: корень vs Supplements[] ===")
    print(f"Обработано непустых строк JSONL:     {total}")
    print(f"Строк с AEO на корне:                {root_aeo_present}")
    print(f"Строк с AEO хотя бы в одном прилож.: {any_sup_aeo_present}")
    print()
    print("Корень + приложения (оба присутствуют):")
    print(f"  таких строк:                       {both_present}")
    print(f"  все Id прилож. = корневому AEO:    {all_sup_match_root_when_root}")
    print(f"  есть приложение с Id ≠ корня:     {mismatch_vs_root}")
    print()
    print("Без корневого AEO, но AEO в приложениях:")
    print(f"  таких строк:                       {no_root_but_sup_aeo}")
    print(f"  все прилож. с одним Id AEO:        {no_root_all_sup_same_aeo}")
    print(f"  разные Id между приложениями:     {cross_sup_mismatch}")
    print()
    print(f"Собрано строк для датасета (расхождения, порядок файла): {len(interesting_lines)}")

    if not args.no_samples:
        out_dir = args.output_dir
        _write_sample_files(out_dir, interesting_lines, sizes)
        for n in sizes:
            n_written = min(n, len(interesting_lines))
            print(f"  → {out_dir / f'sample_{n}.jsonl'}\t({n_written} строк)", file=sys.stderr)
    else:
        print("(запись sample_*.jsonl отключена: --no-samples)", file=sys.stderr)

    if print_notes:
        print("\nПримеры (первые --print-examples):")
        for ex in print_notes:
            print(" ", ex)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
