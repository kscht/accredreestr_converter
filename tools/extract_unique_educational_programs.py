#!/usr/bin/env python3
"""Уникальные объекты EducationalProgram из большого JSONL (один проход).

Вход обычно — JSONL из ``convert.py`` (по умолчанию без «Недействующее» на корне, без псевдорегиона «за пределами РФ», без ключей с ``null`` и пустых ``[]``/``{}``).

Уникальность по **содержимому без поля Id** (Id в реестре не глобально уникален).
Поля **TypeName**, **EduNormativePeriod**, **IsAccredited**, **IsCanceled**, **IsSuspended**
не входят в справочник: исключаются из отпечатка уникальности и из строк выхода. Программы **без непустого UGSName** в справочник не попадают. **Qualification** по умолчанию **может быть пустой** (как в выгрузке ИС ГА для части СПО, напр. 09.02.07); при **`--require-qualification`** в выборку только с непустым Qualification. Для **Qualification**-строк сначала канонизация хвоста («перед закрывающей кавычкой…»), затем **уникальность** по отпечатку. Строки выхода **сортируются по убыванию длины Qualification** (пустая/`null` — в конце по длине), затем по **ProgrammCode** (стандартный ``XX.XX.XX`` — по трём числам; нестандартные непустые — по строке; пустой/null — позже), затем **UGSCode** (так же), ProgrammName и отпечатку. В каждую строку JSONL — остальные поля программы и **Id**
первого вхождения данного набора (после исключений). После сборки выполняется проверка целостности для **ProgrammCode ``09.02.07``**: если такие программы прошли фильтры, в выходе обязана быть хотя бы одна строка с этим кодом (иначе скрипт завершится с кодом **1**).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "educational_programs_unique.jsonl"

# Если после фильтров во входе была хотя бы одна программа с таким ProgrammCode, в выходе
# обязана быть ровно одна уникальная строка с этим кодом (регресс: СПО 09.02.07 с пустым Qualification).
_PROGRAMM_CODES_OUTPUT_INVARIANT: Final[frozenset[str]] = frozenset({"09.02.07"})

# Не для номенклатурного справочника: не пишем и не участвуют в дедупликации.
_OMIT_FOR_NOMENCLATURE: frozenset[str] = frozenset(
    {
        "TypeName",
        "EduNormativePeriod",
        "IsAccredited",
        "IsCanceled",
        "IsSuspended",
    }
)

_TRIPLET_CODE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")


def _fingerprint(prog: dict[str, Any]) -> str:
    """Стабильная строка по полям, кроме Id и полей из _OMIT_FOR_NOMENCLATURE."""
    keys = [
        k
        for k in prog.keys()
        if k != "Id"
        and k not in _OMIT_FOR_NOMENCLATURE
        and not str(k).startswith("_")
    ]
    keys.sort()
    payload: dict[str, Any] = {k: prog[k] for k in keys}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _nominal_record(prog: dict[str, Any]) -> dict[str, Any]:
    """Копия программы без полей, выкинутых для справочника."""
    return {k: v for k, v in prog.items() if k not in _OMIT_FOR_NOMENCLATURE}


def _canonical_qualification_before_closing_quote(s: str) -> str:
    """Как перед закрывающей кавычкой в JSON: без пробелов в конце и без одной лишней точки сразу перед ней."""
    t = s.rstrip()
    if t.endswith("."):
        t = t[:-1].rstrip()
    return t


def _program_with_canonical_qualification(prog: dict[str, Any]) -> dict[str, Any]:
    """Поверхностная копия с каноническим Qualification (если это строка)."""
    out = dict(prog)
    q = out.get("Qualification")
    if isinstance(q, str):
        out["Qualification"] = _canonical_qualification_before_closing_quote(q)
    return out


def _ugs_name_present(prog: dict[str, Any]) -> bool:
    """Для справочника нужен непустой UGSName (после trim строки)."""
    v = prog.get("UGSName")
    if v is None:
        return False
    return bool(str(v).strip())


def _qualification_present(prog: dict[str, Any]) -> bool:
    """Для справочника нужен непустой Qualification (ожидается prog после _program_with_canonical_qualification)."""
    v = prog.get("Qualification")
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return bool(str(v).strip())


def _qualification_text_len(rec: dict[str, Any]) -> int:
    """Длина строки квалификации для сортировки (null / не строка → 0)."""
    v = rec.get("Qualification")
    if v is None:
        return 0
    if isinstance(v, str):
        return len(v)
    return len(str(v))


def _nomenclature_code_sort_key(raw: Any) -> tuple[Any, ...]:
    """Порядок: ``XX.XX.XX`` по трём числам; затем прочие непустые по строке; пустой/null — последними."""
    s = "" if raw is None else str(raw).strip()
    if not s:
        return (2, 0, 0, 0, "")
    m = _TRIPLET_CODE_RE.fullmatch(s)
    if m:
        return (0, int(m.group(1)), int(m.group(2)), int(m.group(3)), "")
    return (1, 0, 0, 0, s)


def _normalized_programm_code(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _verify_output_invariants(
    seen: dict[str, dict[str, Any]],
    invariant_input_hits: dict[str, int],
) -> str | None:
    """Проверка, что «якорные» коды не потеряны при дедупликации (ошибка логики / регресс)."""
    for code in _PROGRAMM_CODES_OUTPUT_INVARIANT:
        n = int(invariant_input_hits.get(code, 0))
        if n == 0:
            continue
        if not any(r.get("ProgrammCode") == code for r in seen.values()):
            return (
                f"Внутренняя ошибка сборки справочника: во входе после фильтров встречалась "
                f"программа с ProgrammCode {code!r} ({n} раз), но среди уникальных строк выхода "
                f"нет ни одной записи с этим кодом."
            )
    return None


def _nominal_sort_key(fp: str, rec: dict[str, Any]) -> tuple[Any, ...]:
    """Сортировка: длиннее Qualification выше; затем ProgrammCode, UGSCode и стабильный хвост."""
    qlen = _qualification_text_len(rec)
    pk = _nomenclature_code_sort_key(rec.get("ProgrammCode"))
    uk = _nomenclature_code_sort_key(rec.get("UGSCode"))
    pn = rec.get("ProgrammName")
    prog_n = "" if pn is None else str(pn)
    return (-qlen, pk, uk, prog_n, fp)


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Собрать уникальные EducationalProgram по содержимому (без Id); "
            "без TypeName, EduNormativePeriod, IsAccredited/IsCanceled/IsSuspended; "
            "только с непустым UGSName (Qualification по умолчанию может быть пустой); "
            "Id — первое вхождение; выход: по убыванию длины Qualification, затем ProgrammCode, UGSCode."
        ),
    )
    p.add_argument("jsonl", type=Path, help="Входной .jsonl (сертификаты)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Выходной JSONL (по умолчанию {_DEFAULT_OUT})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Обработать не более N непустых строк входа",
    )
    p.add_argument(
        "--require-qualification",
        action="store_true",
        help=(
            "Включать только программы с непустым Qualification после канонизации "
            "(режим совместимости со старым справочником)."
        ),
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    seen: dict[str, dict[str, Any]] = {}
    lines_in = 0
    programs_seen = 0
    skipped_no_ugs_name = 0
    skipped_no_qualification = 0
    invariant_hits: dict[str, int] = {c: 0 for c in _PROGRAMM_CODES_OUTPUT_INVARIANT}

    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            lines_in += 1
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            for sup in obj.get("Supplements") or []:
                if not isinstance(sup, dict):
                    continue
                for prog in sup.get("EducationalPrograms") or []:
                    if not isinstance(prog, dict):
                        continue
                    programs_seen += 1
                    prog = _program_with_canonical_qualification(prog)
                    if not _ugs_name_present(prog):
                        skipped_no_ugs_name += 1
                        continue
                    if args.require_qualification and not _qualification_present(prog):
                        skipped_no_qualification += 1
                        continue
                    pcn = _normalized_programm_code(prog.get("ProgrammCode"))
                    if pcn in invariant_hits:
                        invariant_hits[pcn] += 1
                    fp = _fingerprint(prog)
                    if fp not in seen:
                        seen[fp] = _nominal_record(dict(prog))

            if args.limit is not None and lines_in >= args.limit:
                break

    inv_err = _verify_output_invariants(seen, invariant_hits)
    if inv_err:
        print(inv_err, file=sys.stderr)
        return 1

    out: Path = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as w:
        for _fp, row in sorted(
            seen.items(),
            key=lambda kv: _nominal_sort_key(kv[0], kv[1]),
        ):
            w.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"Строк сертификатов: {lines_in}\n"
        f"Всего EducationalProgram: {programs_seen}\n"
        f"Пропущено (нет UGSName): {skipped_no_ugs_name}\n"
        f"Пропущено (нет Qualification, режим --require-qualification): {skipped_no_qualification}\n"
        f"Уникальных по полям (без Id): {len(seen)}\n"
        f"Записано: {out.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
