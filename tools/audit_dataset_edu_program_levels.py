#!/usr/bin/env python3
"""Аудит JSONL: уровни образования в ``Supplements[].EducationalPrograms[]``.

В типичной выгрузке **корневой** ``TypeName`` у сертификата и ``TypeName`` у программы
часто **отсутствуют**; различать ООО/школу/вуз по снимку удобнее по строке ``EduLevelName``
у каждого элемента ``EducationalPrograms[]``.

**«Школьные» ступени** (точное совпадение строки после ``strip``) — множество
``SCHOOL_LEVEL_NAMES`` в коде: НОО, ООО, СОО, дошкольное, «общее» и варианты из реестра.

Классификация **одной строки JSONL** (сертификата):

- ``no_educational_programs`` — ни в одном ``Supplements[]`` нет непустого списка программ;
- ``all_program_levels_empty`` — программы есть, но у **всех** нет непустого ``EduLevelName``;
- ``school_levels_only`` — есть хотя бы одна программа с непустым уровнем и **все** такие
  уровни входят в ``SCHOOL_LEVEL_NAMES``;
- ``non_school_levels_only`` — есть непустые уровни и **ни один** не из ``SCHOOL_LEVEL_NAMES``
  (типично СПО, высшее, профобучение);
- ``mixed_school_and_other`` — встречаются и школьные, и нешкольные непустые уровни.

Потоковый обход входного JSONL. JSON-отчёт по умолчанию:
``examples/dataset_edu_program_levels_audit.json``.

Опционально полные строки входа:

- **``-p``** / ``--problem-jsonl`` [PATH] — только ``non_school_levels_only`` (в реестре
  аккредитации по программам нет «школьной» ступени — удобно для ручного разбора).
  Без PATH: ``examples/certificate_lines_edu_programs_non_school_only.jsonl``;
  файлы такого рода в **``.gitignore``** (как крупные выборки из полного JSONL);
- **``--school-jsonl``** [PATH] — только ``school_levels_only``. Без PATH:
  ``examples/certificate_lines_edu_programs_school_only.jsonl`` (**``.gitignore``**);
- **``--mixed-jsonl``** [PATH] — только ``mixed_school_and_other``. Без PATH:
  ``examples/certificate_lines_edu_programs_school_mixed.jsonl`` (**``.gitignore``**);
- **``--empty-level-jsonl``** [PATH] — сертификаты, где **хотя бы у одной** программы пустой
  или отсутствующий ``EduLevelName`` (данные реестра / компактный JSON). Без PATH:
  ``examples/certificate_lines_edu_programs_empty_EduLevelName.jsonl`` (**``.gitignore``**);
- **``--empty-program-jsonl``** [PATH] — **каждая** программа с пустым ``EduLevelName`` отдельной
  строкой JSON (обёртка: ``certificate_id``, индексы supplement/программы, ``program``). Без PATH:
  ``examples/edu_programs_empty_EduLevelName.jsonl``.

Пустые ``EduLevelName`` **не участвуют** в классификации school / mixed / non_school (смотрятся
только непустые строки); отдельные поля отчёта и ``--empty-level-jsonl`` как раз для учёта этой дыры.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "dataset_edu_program_levels_audit.json"
_DEFAULT_PROBLEM_JSONL = _ROOT / "examples" / "certificate_lines_edu_programs_non_school_only.jsonl"
_DEFAULT_SCHOOL_JSONL = _ROOT / "examples" / "certificate_lines_edu_programs_school_only.jsonl"
_DEFAULT_MIXED_JSONL = _ROOT / "examples" / "certificate_lines_edu_programs_school_mixed.jsonl"
_DEFAULT_EMPTY_LEVEL_JSONL = _ROOT / "examples" / "certificate_lines_edu_programs_empty_EduLevelName.jsonl"
_DEFAULT_EMPTY_PROGRAM_JSONL = _ROOT / "examples" / "edu_programs_empty_EduLevelName.jsonl"

# Точные строки EduLevelName из выгрузки ИС ГА (после strip), общие образовательные ступени школы.
SCHOOL_LEVEL_NAMES: frozenset[str] = frozenset(
    {
        "Начальное общее образование",
        "Основное общее образование",
        "Среднее общее образование",
        "Дошкольное образование",
        "Общее образование",
        "Среднее (полное) общее образование",
        "Не определен",
    }
)

CertKind = Literal[
    "no_educational_programs",
    "all_program_levels_empty",
    "school_levels_only",
    "non_school_levels_only",
    "mixed_school_and_other",
]


def _iter_program_level_strings(row: dict[str, Any]) -> tuple[int, list[str | None]]:
    """Возвращает (число объектов-программ, список EduLevelName сырьём по порядку обхода)."""
    programs: list[str | None] = []
    for sup in row.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        for pr in sup.get("EducationalPrograms") or []:
            if not isinstance(pr, dict):
                continue
            if "EduLevelName" not in pr:
                programs.append(None)
            else:
                v = pr["EduLevelName"]
                if v is None:
                    programs.append(None)
                elif isinstance(v, str):
                    programs.append(v.strip() or None)
                else:
                    programs.append(str(v).strip() or None)
    return len(programs), programs


def _classify_certificate(programs_count: int, levels: list[str | None]) -> CertKind:
    if programs_count == 0:
        return "no_educational_programs"
    nonempty = [x for x in levels if x]
    if not nonempty:
        return "all_program_levels_empty"
    in_s = [x for x in nonempty if x in SCHOOL_LEVEL_NAMES]
    out_s = [x for x in nonempty if x not in SCHOOL_LEVEL_NAMES]
    if in_s and out_s:
        return "mixed_school_and_other"
    if in_s:
        return "school_levels_only"
    return "non_school_levels_only"


def _educational_program_edulevel_empty(pr: dict[str, Any]) -> bool:
    """True, если у объекта программы нет непустого EduLevelName (как в гистограмме «<пустой>»)."""
    if "EduLevelName" not in pr:
        return True
    v = pr["EduLevelName"]
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    return not str(v).strip()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Аудит EduLevelName в Supplements[].EducationalPrograms[] и классификация сертификатов.",
    )
    ap.add_argument("jsonl", type=Path, help="Входной .jsonl (одна строка = сертификат)")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON-отчёт (по умолчанию {_DEFAULT_OUT})",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=200,
        metavar="N",
        help="Не больше N примеров certificate_id на каждый класс (0 = без примеров)",
    )
    ap.add_argument(
        "-p",
        "--problem-jsonl",
        nargs="?",
        const=_DEFAULT_PROBLEM_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "Полные строки: класс non_school_levels_only. Без PATH — "
            f"{_DEFAULT_PROBLEM_JSONL.relative_to(_ROOT)}"
        ),
    )
    ap.add_argument(
        "--school-jsonl",
        nargs="?",
        const=_DEFAULT_SCHOOL_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "Полные строки: класс school_levels_only. Без PATH — "
            f"{_DEFAULT_SCHOOL_JSONL.relative_to(_ROOT)}"
        ),
    )
    ap.add_argument(
        "--mixed-jsonl",
        nargs="?",
        const=_DEFAULT_MIXED_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "Полные строки: класс mixed_school_and_other. Без PATH — "
            f"{_DEFAULT_MIXED_JSONL.relative_to(_ROOT)}"
        ),
    )
    ap.add_argument(
        "--empty-level-jsonl",
        nargs="?",
        const=_DEFAULT_EMPTY_LEVEL_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "Полные строки: есть ≥1 программа с пустым/без EduLevelName. Без PATH — "
            f"{_DEFAULT_EMPTY_LEVEL_JSONL.relative_to(_ROOT)}"
        ),
    )
    ap.add_argument(
        "--empty-program-jsonl",
        nargs="?",
        const=_DEFAULT_EMPTY_PROGRAM_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "По одной JSON-строке на каждую программу с пустым EduLevelName (обёртка + program). "
            f"Без PATH — {_DEFAULT_EMPTY_PROGRAM_JSONL.relative_to(_ROOT)}"
        ),
    )
    args = ap.parse_args()
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

    fh_non = args.problem_jsonl.open("w", encoding="utf-8", newline="\n") if args.problem_jsonl else None
    fh_sch = args.school_jsonl.open("w", encoding="utf-8", newline="\n") if args.school_jsonl else None
    fh_mix = args.mixed_jsonl.open("w", encoding="utf-8", newline="\n") if args.mixed_jsonl else None
    fh_empty = (
        args.empty_level_jsonl.open("w", encoding="utf-8", newline="\n") if args.empty_level_jsonl else None
    )
    fh_empty_prog = (
        args.empty_program_jsonl.open("w", encoding="utf-8", newline="\n")
        if args.empty_program_jsonl
        else None
    )

    total_lines = 0
    level_hist: Counter[str] = Counter()
    empty_level_programs = 0
    programs_total = 0

    by_kind: Counter[str] = Counter()
    _kinds = (
        "no_educational_programs",
        "all_program_levels_empty",
        "school_levels_only",
        "non_school_levels_only",
        "mixed_school_and_other",
    )
    examples: dict[str, list[dict[str, Any]]] = {k: [] for k in _kinds}
    examples_empty_edulevel: list[dict[str, Any]] = []
    certificates_with_any_empty_edulevel_program = 0
    by_kind_if_has_empty_edulevel: Counter[str] = Counter()

    for raw_line in args.jsonl.open(encoding="utf-8", errors="replace"):
        s = raw_line.strip()
        if not s:
            continue
        total_lines += 1
        try:
            row = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        n_prog, levels = _iter_program_level_strings(row)
        programs_total += n_prog
        for lv in levels:
            if lv is None:
                empty_level_programs += 1
                level_hist["<пустой EduLevelName>"] += 1
            else:
                level_hist[lv] += 1

        kind = _classify_certificate(n_prog, levels)
        by_kind[kind] += 1

        n_empty_lv = sum(1 for x in levels if x is None)
        has_empty_edulevel = n_empty_lv > 0
        if has_empty_edulevel:
            certificates_with_any_empty_edulevel_program += 1
            by_kind_if_has_empty_edulevel[kind] += 1
            if len(examples_empty_edulevel) < args.limit:
                uniq = sorted(set(x for x in levels if x))
                examples_empty_edulevel.append(
                    {
                        "certificate_id": row.get("Id"),
                        "input_line_number": total_lines,
                        "program_level_kind": kind,
                        "empty_EduLevelName_program_count": n_empty_lv,
                        "nonempty_EduLevelName_distinct": uniq[:20],
                        "EduOrgShortName": row.get("EduOrgShortName"),
                    }
                )
            if fh_empty is not None:
                fh_empty.write(raw_line if raw_line.endswith("\n") else raw_line + "\n")

        if fh_empty_prog is not None:
            for si, sup in enumerate(row.get("Supplements") or []):
                if not isinstance(sup, dict):
                    continue
                for pi, pr in enumerate(sup.get("EducationalPrograms") or []):
                    if not isinstance(pr, dict):
                        continue
                    if not _educational_program_edulevel_empty(pr):
                        continue
                    fh_empty_prog.write(
                        json.dumps(
                            {
                                "certificate_id": row.get("Id"),
                                "input_line_number": total_lines,
                                "supplement_index": si,
                                "program_index_in_supplement": pi,
                                "program": pr,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

        if len(examples[kind]) < args.limit:
            cid = row.get("Id")
            uniq = sorted(set(x for x in levels if x))
            examples[kind].append(
                {
                    "certificate_id": cid,
                    "input_line_number": total_lines,
                    "EduLevelName_nonempty_distinct": uniq[:24],
                    "EduOrgShortName": row.get("EduOrgShortName"),
                }
            )

        if kind == "non_school_levels_only" and fh_non is not None:
            fh_non.write(raw_line if raw_line.endswith("\n") else raw_line + "\n")
        elif kind == "school_levels_only" and fh_sch is not None:
            fh_sch.write(raw_line if raw_line.endswith("\n") else raw_line + "\n")
        elif kind == "mixed_school_and_other" and fh_mix is not None:
            fh_mix.write(raw_line if raw_line.endswith("\n") else raw_line + "\n")

    for fh in (fh_non, fh_sch, fh_mix, fh_empty, fh_empty_prog):
        if fh is not None:
            fh.close()

    def _sorted_hist(c: Counter[str]) -> dict[str, int]:
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    school_sector_hist = {name: int(level_hist[name]) for name in sorted(SCHOOL_LEVEL_NAMES) if level_hist[name]}
    school_sector_subtotal = sum(school_sector_hist.values())

    out: dict[str, Any] = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Гистограмма EduLevelName по всем объектам EducationalPrograms в Supplements[]. "
            "В смысле «школы / общеобразовательный контур» здесь считаются ступени из "
            "`school_level_names_used`: НОО, ООО, СОО, дошкольное, «Общее образование», "
            "«Среднее (полное) общее», «Не определен» — см. блок `school_sector_histogram` и "
            "`school_sector_program_objects_subtotal`. "
            "Классификация сертификата по множеству **непустых** EduLevelName и этому списку; программы с пустым "
            "уровнем в классификацию не входят — см. "
            "`certificates_with_any_empty_EduLevelName_program` и `by_kind_if_has_empty_edulevel`. "
            "Корневой TypeName сертификата в компактном JSONL обычно отсутствует — см. audit_dataset_status."
        ),
        "school_level_names_used": sorted(SCHOOL_LEVEL_NAMES),
        "school_sector_histogram": school_sector_hist,
        "school_sector_program_objects_subtotal": school_sector_subtotal,
        "certificate_lines_total": total_lines,
        "educational_program_objects_total": programs_total,
        "educational_programs_with_empty_or_missing_EduLevelName": empty_level_programs,
        "certificates_with_any_empty_EduLevelName_program": certificates_with_any_empty_edulevel_program,
        "by_kind_if_has_empty_edulevel": dict(sorted(by_kind_if_has_empty_edulevel.items())),
        "certificates_by_program_level_kind": dict(sorted(by_kind.items())),
        "histogram_EduLevelName": _sorted_hist(level_hist),
        "examples_by_kind": examples,
        "examples_certificates_with_empty_EduLevelName_program": examples_empty_edulevel,
        "exports": {
            "non_school_only_jsonl": str(args.problem_jsonl.resolve()) if args.problem_jsonl else None,
            "school_only_jsonl": str(args.school_jsonl.resolve()) if args.school_jsonl else None,
            "mixed_jsonl": str(args.mixed_jsonl.resolve()) if args.mixed_jsonl else None,
            "empty_EduLevelName_jsonl": str(args.empty_level_jsonl.resolve()) if args.empty_level_jsonl else None,
            "empty_EduLevelName_program_objects_jsonl": (
                str(args.empty_program_jsonl.resolve()) if args.empty_program_jsonl else None
            ),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Строк сертификатов: {total_lines}\n"
        f"Объектов EducationalPrograms: {programs_total}\n"
        f"  с пустым/без EduLevelName: {empty_level_programs}\n"
        f"Сертификатов с ≥1 такой программой: {certificates_with_any_empty_edulevel_program}\n"
        f"  из них по классу (только по непустым уровням): {dict(by_kind_if_has_empty_edulevel)}\n"
        f"По классификации сертификатов: {dict(by_kind)}\n"
        f"Программ в «школьном контуре» (сумма по {len(SCHOOL_LEVEL_NAMES)} ступеням из отчёта): {school_sector_subtotal}\n"
        f"Отчёт: {args.output.resolve()}"
        + (f"\nnon_school_only → {args.problem_jsonl.resolve()}" if args.problem_jsonl else "")
        + (f"\nschool_only → {args.school_jsonl.resolve()}" if args.school_jsonl else "")
        + (f"\nmixed → {args.mixed_jsonl.resolve()}" if args.mixed_jsonl else "")
        + (f"\nempty EduLevelName → {args.empty_level_jsonl.resolve()}" if args.empty_level_jsonl else "")
        + (
            f"\nempty EduLevelName programs → {args.empty_program_jsonl.resolve()}"
            if args.empty_program_jsonl
            else ""
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
