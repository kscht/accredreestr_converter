#!/usr/bin/env python3
"""По одной выборке на каждый ``EduLevelName`` из словаря (компактный JSONL для маппинга).

Читает список уровней из ``specs/edu_level_names_vocab.json`` (ключ ``unique_edu_level_names``),
одним проходом по JSONL. По умолчанию для каждого уровня выбирается сертификат с **максимальной
заполненностью** (рекурсивный счёт непустых листьев JSON); при **равном** счёте — равномерный
резервуар среди равных. Флаг ``--uniform-random`` отключает приоритет заполненности: тогда только
резервуар 1/k по всем подходящим сертификатам.

Каждая строка выходного JSONL — короткий объект: ``EduLevelName`` на корне и ``programs`` —
массив из **одной** программы с этим уровнем (первая по порядку в сертификате), поля для
сопоставления без повторения ``EduLevelName`` внутри объекта программы.

Пример::

    python tools/sample_one_certificate_per_edu_level_name.py out/data.jsonl \\
        -o examples/certificate_sample_one_random_per_edu_level_name.jsonl --seed 42
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_VOCAB = _ROOT / "specs" / "edu_level_names_vocab.json"
_DEFAULT_OUT = _ROOT / "examples" / "certificate_sample_one_random_per_edu_level_name.jsonl"


def _nonempty_edu_level_name(pr: dict[str, Any]) -> str | None:
    if "EduLevelName" not in pr:
        return None
    v = pr["EduLevelName"]
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    s = str(v).strip()
    return s if s else None


def _levels_in_certificate_matching_vocab(row: dict[str, Any], vocab: frozenset[str]) -> set[str]:
    found: set[str] = set()
    for sup in row.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        for pr in sup.get("EducationalPrograms") or []:
            if not isinstance(pr, dict):
                continue
            n = _nonempty_edu_level_name(pr)
            if n and n in vocab:
                found.add(n)
    return found


_PROGRAM_FIELDS_FOR_MAPPING: tuple[str, ...] = (
    "EduLevelName",
    "ProgrammName",
    "ProgrammCode",
    "UGSName",
    "UGSCode",
    "TypeName",
    "IsAccredited",
)


def _slim_program_dict(pr: dict[str, Any]) -> dict[str, Any]:
    """Только поля, полезные для сопоставления уровня с профилем программы (без пустых значений)."""
    slim: dict[str, Any] = {}
    for k in _PROGRAM_FIELDS_FOR_MAPPING:
        if k not in pr:
            continue
        v = pr[k]
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        slim[k] = v
    return slim


def _first_program_matching_edu_level(cert: dict[str, Any], level: str) -> list[dict[str, Any]]:
    """Первая программа в сертификате с непустым EduLevelName == level (после strip)."""
    for sup in cert.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        for pr in sup.get("EducationalPrograms") or []:
            if not isinstance(pr, dict):
                continue
            if _nonempty_edu_level_name(pr) != level:
                continue
            slim = _slim_program_dict(pr)
            if len(slim) != 1 or "EduLevelName" not in slim:
                slim.pop("EduLevelName", None)
            return [slim]
    return []


def _certificate_fill_score(obj: Any) -> int:
    """Грубый счёт «заполненности»: рекурсивно непустые листья (строка после strip, число, bool, вложенность)."""
    if obj is None:
        return 0
    if isinstance(obj, bool):
        return 1
    if isinstance(obj, (int, float)):
        return 1
    if isinstance(obj, str):
        return 1 if obj.strip() else 0
    if isinstance(obj, dict):
        return sum(_certificate_fill_score(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_certificate_fill_score(v) for v in obj)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Компактная выборка на каждый EduLevelName из edu_level_names_vocab (маппинг программ).",
    )
    ap.add_argument("jsonl", type=Path, help="Входной .jsonl (одна строка = сертификат)")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Выходной .jsonl (по умолчанию {_DEFAULT_OUT.relative_to(_ROOT)})",
    )
    ap.add_argument(
        "--vocab",
        type=Path,
        default=_DEFAULT_VOCAB,
        help=f"JSON со списком unique_edu_level_names (по умолчанию {_DEFAULT_VOCAB.relative_to(_ROOT)})",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Seed ГПСЧ для воспроизводимости (по умолчанию — недетерминировано)",
    )
    ap.add_argument(
        "--uniform-random",
        action="store_true",
        help="Не максимизировать заполненность: равномерный случайный выбор среди всех подходящих сертификатов",
    )
    args = ap.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2
    if not args.vocab.is_file():
        print(f"Нет словаря: {args.vocab}", file=sys.stderr)
        return 2

    raw_vocab = json.loads(args.vocab.read_text(encoding="utf-8"))
    names = raw_vocab.get("unique_edu_level_names")
    if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
        print("В vocab ожидается ключ unique_edu_level_names: список строк", file=sys.stderr)
        return 2

    vocab_set = frozenset(names)
    rng = random.Random(args.seed)

    counts: dict[str, int] = {n: 0 for n in names}
    chosen: dict[str, dict[str, Any] | None] = {n: None for n in names}
    chosen_score: dict[str, int] = {n: -1 for n in names}
    tie_counts: dict[str, int] = {n: 0 for n in names}

    total_lines = 0
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
            total_lines += 1
            hit = _levels_in_certificate_matching_vocab(row, vocab_set)
            if not hit:
                continue
            score = _certificate_fill_score(row)
            for L in sorted(hit):
                if args.uniform_random:
                    counts[L] += 1
                    if rng.random() * counts[L] < 1.0:
                        chosen[L] = copy.deepcopy(row)
                else:
                    prev = chosen_score[L]
                    if score > prev:
                        chosen_score[L] = score
                        tie_counts[L] = 1
                        chosen[L] = copy.deepcopy(row)
                    elif score == prev:
                        tie_counts[L] += 1
                        if rng.random() * tie_counts[L] < 1.0:
                            chosen[L] = copy.deepcopy(row)

    missing = [n for n in names if chosen.get(n) is None]
    if missing:
        print(f"Не найдено ни одного сертификата для уровней: {missing}", file=sys.stderr)
        return 1

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())
    try:
        voc_rel = str(args.vocab.resolve().relative_to(_ROOT))
    except ValueError:
        voc_rel = str(args.vocab.resolve())

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for L in names:
            cert = chosen[L]
            assert cert is not None
            payload: dict[str, Any] = {
                "EduLevelName": L,
                "programs": _first_program_matching_edu_level(cert, L),
            }
            out.write(json.dumps(payload, ensure_ascii=False) + "\n")

    print(
        f"Прочитано строк сертификатов: {total_lines}\n"
        f"Уровней в словаре: {len(names)}\n"
        f"Записано строк выборки: {len(names)}\n"
        f"Режим: {'uniform_random' if args.uniform_random else 'max_fill_score_then_random_tie'}\n"
        f"Выход: {args.output.resolve()}\n"
        f"источник JSONL: {src_rel}\n"
        f"словарь: {voc_rel}"
        + (f"\nseed: {args.seed}" if args.seed is not None else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
