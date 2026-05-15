#!/usr/bin/env python3
"""Уникальные непустые ``EduLevelName`` из ``Supplements[].EducationalPrograms[]`` в JSONL реестра.

Один проход, без загрузки всего файла в память. Выход — JSON для репозитория (словарь значений
и метаданные; гистограмма по строкам уровня — для контроля и последующего сопоставления).

Пример::

    python tools/extract_unique_edu_level_names.py out/data.jsonl \\
        -o specs/edu_level_names_vocab.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "specs" / "edu_level_names_vocab.json"


def _nonempty_edu_level_name(pr: dict[str, Any]) -> str | None:
    """Непустой EduLevelName после strip или None, если ключа нет / пусто."""
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Уникальные EduLevelName в EducationalPrograms (JSONL сертификатов).",
    )
    ap.add_argument("jsonl", type=Path, help="Входной .jsonl (одна строка = сертификат)")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON (по умолчанию {_DEFAULT_OUT.relative_to(_ROOT)})",
    )
    args = ap.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    hist: Counter[str] = Counter()
    cert_lines = 0
    programs_total = 0
    programs_nonempty = 0
    programs_empty = 0

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
            cert_lines += 1
            for sup in row.get("Supplements") or []:
                if not isinstance(sup, dict):
                    continue
                for pr in sup.get("EducationalPrograms") or []:
                    if not isinstance(pr, dict):
                        continue
                    programs_total += 1
                    name = _nonempty_edu_level_name(pr)
                    if name is None:
                        programs_empty += 1
                    else:
                        programs_nonempty += 1
                        hist[name] += 1

    unique_sorted = sorted(hist.keys())
    out: dict[str, Any] = {
        "format_version": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "description_ru": (
            "Уникальные непустые строки EduLevelName среди объектов EducationalPrograms "
            "в Supplements[]; гистограмма по числу таких программ в снимке. "
            "Пустой или отсутствующий EduLevelName в unique_edu_level_names не входит."
        ),
        "source_jsonl": src_rel,
        "certificate_lines_total": cert_lines,
        "educational_program_objects_total": programs_total,
        "educational_programs_nonempty_edu_level_name": programs_nonempty,
        "educational_programs_empty_or_missing_edu_level_name": programs_empty,
        "unique_edu_level_names": unique_sorted,
        "unique_edu_level_names_count": len(unique_sorted),
        "histogram_EduLevelName": dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Сертификатов: {cert_lines}\n"
        f"Объектов EducationalPrograms: {programs_total}\n"
        f"  с непустым EduLevelName: {programs_nonempty}\n"
        f"  пусто/нет ключа: {programs_empty}\n"
        f"Уникальных непустых EduLevelName: {len(unique_sorted)}\n"
        f"Файл: {args.output.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
