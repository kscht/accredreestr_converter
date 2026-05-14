#!/usr/bin/env python3
"""Поиск скалярных «плейсхолдеров» в JSONL (как Qualification: \"0\" → null в convert.py).

Потоковый обход: для каждого пути к строковому значению считает вхождения значений,
попадающих под заданные классы (ровно строка из нулей, одно тире, маркеры «нет данных»).

Пример:
  python tools/scan_jsonl_placeholder_scalars.py out/data-20260403-structure-20160713.jsonl
  python tools/scan_jsonl_placeholder_scalars.py examples/educational_programs_unique.jsonl --limit 5000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_RE_ONLY_ZEROS = re.compile(r"^0+$")
_RE_DASH = re.compile(r"^[\-—–]$")
_RE_EMPTY_MARKER = re.compile(r"^(н/д|нд|нет данных|null|none)$", re.I)


def classify_placeholder(s: str) -> str | None:
    if _RE_ONLY_ZEROS.match(s):
        return "only_zeros"
    if _RE_DASH.match(s):
        return "dash_only"
    if _RE_EMPTY_MARKER.match(s):
        return "empty_marker"
    return None


def _path_key(parts: tuple[str, ...]) -> str:
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def _walk(obj: Any, parts: tuple[str, ...], hit_counter: Counter[tuple[str, str, str]]) -> None:
    """hit_counter: (class_id, path, literal_value) -> count."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).startswith("_"):
                continue
            _walk(v, parts + (str(k),), hit_counter)
        return
    if isinstance(obj, list):
        for item in obj:
            _walk(item, parts + ("*",), hit_counter)
        return
    if isinstance(obj, str):
        cls = classify_placeholder(obj)
        if cls is not None:
            hit_counter[(cls, _path_key(parts), obj)] += 1
        return


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("jsonl", type=Path, help="Входной .jsonl")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Не более N непустых строк JSONL",
    )
    p.add_argument(
        "--min-count",
        type=int,
        default=1,
        help="Печатать только пары (путь, значение) с числом вхождений >= N",
    )
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    hit_counter: Counter[tuple[str, str, str]] = Counter()
    lines = 0
    bad_json = 0

    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            lines += 1
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                bad_json += 1
                continue
            if isinstance(obj, dict):
                _walk(obj, (), hit_counter)

            if args.limit is not None and lines >= args.limit:
                break

    by_class: dict[str, dict[str, Counter[str]]] = {}
    for (cls, path, val), c in hit_counter.items():
        if c < args.min_count:
            continue
        by_class.setdefault(cls, {}).setdefault(path, Counter())[val] += c

    print(f"Строк JSONL: {lines}\tошибок JSON: {bad_json}", file=sys.stderr)
    print("класс\tвсего_вхождений\tуникальных_литералов\tпример_значения\tпуть")
    grand = 0
    for cls in sorted(by_class.keys()):
        paths = by_class[cls]
        for path in sorted(paths.keys()):
            vc = paths[path]
            total = sum(vc.values())
            grand += total
            example = sorted(vc.keys(), key=lambda k: (-vc[k], k))[0]
            print(f"{cls}\t{total}\t{len(vc)}\t{example!r}\t{path}")
    print(f"---\nВсего отмеченных строковых вхождений: {grand}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
