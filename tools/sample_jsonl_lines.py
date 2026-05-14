#!/usr/bin/env python3
"""Случайная подвыборка строк из большого JSONL (резервуарный алгоритм, один проход по файлу)."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path


def reservoir_sample_lines(input_path: Path, n: int, seed: int) -> list[str]:
    """Вернуть n случайных непустых строк из JSONL (резервуар, один проход, O(n) память)."""
    if n < 1:
        raise ValueError("n должно быть >= 1")
    if not input_path.is_file():
        raise FileNotFoundError(f"Нет файла: {input_path}")

    random.seed(seed)
    k = n
    reservoir: list[str] = []

    with input_path.open(encoding="utf-8", errors="replace") as fh:
        i = 0
        for line in fh:
            s = line.strip()
            if not s:
                continue
            if i < k:
                reservoir.append(s)
            else:
                j = random.randint(0, i)
                if j < k:
                    reservoir[j] = s
            i += 1

    if len(reservoir) < k:
        raise ValueError(
            f"В файле только {len(reservoir)} непустых строк, запрошено {k}"
        )
    return reservoir


def main() -> int:
    p = argparse.ArgumentParser(
        description="Записать N случайных непустых строк из JSONL в отдельный файл (без загрузки всего файла в память).",
    )
    p.add_argument("input", type=Path, help="Входной .jsonl")
    p.add_argument("-o", "--output", type=Path, required=True, help="Выходной .jsonl")
    p.add_argument("-n", "--lines", type=int, required=True, metavar="N", help="Сколько строк выбрать")
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed RNG для воспроизводимости (по умолчанию 42)",
    )
    args = p.parse_args()
    if args.lines < 1:
        print("N должно быть >= 1", file=sys.stderr)
        return 2
    if not args.input.is_file():
        print(f"Нет файла: {args.input}", file=sys.stderr)
        return 2

    try:
        lines = reservoir_sample_lines(args.input, args.lines, args.seed)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for s in lines:
            out.write(s + "\n")
    print(f"Записано {args.lines} строк → {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
