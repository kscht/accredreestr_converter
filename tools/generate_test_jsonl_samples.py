#!/usr/bin/env python3
"""Случайные подвыборки JSONL фиксированных размеров для тестов (10, 50, 100, 500, 5000 строк).

Использует резервуарный алгоритм из sample_jsonl_lines.py. Для каждого размера — свой seed,
чтобы выборки были независимыми при одном и том же входном файле.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import sample_jsonl_lines as sjl  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SIZES = (10, 50, 100, 500, 5000)
_DEFAULT_SEED_BASE = 40440


def _default_input_path() -> Path | None:
    out = _ROOT / "out"
    if not out.is_dir():
        return None
    candidates = sorted(out.glob("data-*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)
    if candidates:
        return candidates[0]
    alt = out / "sample_live_5000.jsonl"
    return alt if alt.is_file() else None


def main() -> int:
    p = argparse.ArgumentParser(
        description="Сгенерировать набор случайных JSONL выборок (10, 50, 100, 500, 5000 строк) из большого файла.",
    )
    p.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=None,
        help="Входной .jsonl (по умолчанию: самый крупный out/data-*.jsonl или out/sample_live_5000.jsonl)",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=_ROOT / "examples" / "jsonl_samples",
        help="Каталог для sample_10.jsonl, sample_50.jsonl, … (по умолчанию examples/jsonl_samples)",
    )
    p.add_argument(
        "--sizes",
        type=str,
        default=",".join(map(str, _DEFAULT_SIZES)),
        help="Размеры через запятую (по умолчанию 10,50,100,500,5000)",
    )
    p.add_argument(
        "--seed-base",
        type=int,
        default=_DEFAULT_SEED_BASE,
        metavar="S",
        help=f"База для seed: для размера N используется seed S+N (по умолчанию {_DEFAULT_SEED_BASE})",
    )
    args = p.parse_args()

    inp = args.input
    if inp is None:
        inp = _default_input_path()
    if inp is None or not inp.is_file():
        print(
            "Не найден входной JSONL: укажите путь явно или положите out/data-*.jsonl",
            file=sys.stderr,
        )
        return 2

    try:
        sizes = [int(x.strip()) for x in args.sizes.split(",") if x.strip()]
    except ValueError:
        print("Некорректный --sizes", file=sys.stderr)
        return 2
    if any(n < 1 for n in sizes):
        print("Все размеры должны быть >= 1", file=sys.stderr)
        return 2

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for n in sizes:
        seed = args.seed_base + n
        try:
            lines = sjl.reservoir_sample_lines(inp.resolve(), n, seed)
        except (ValueError, FileNotFoundError) as exc:
            print(f"n={n}: {exc}", file=sys.stderr)
            return 2
        out_path = out_dir / f"sample_{n}.jsonl"
        with out_path.open("w", encoding="utf-8", newline="\n") as fh:
            for line in lines:
                fh.write(line + "\n")
        print(f"seed={seed}\t{n} строк → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
