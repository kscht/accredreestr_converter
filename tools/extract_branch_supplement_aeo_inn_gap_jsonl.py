#!/usr/bin/env python3
"""Извлечение в JSONL карточек supplement ``ActualEducationOrganization`` с разным ``Id`` от корня (филиал в смысле проекта), где **INN** пуст, а донор есть «сверху».

Критерии совпадают со статистикой «5482»: ``ActualEducationOrganization.Id`` на корне и в supplement оба непусты, токены **различаются**, у supplement **нет** валидного **INN** (как ``convert._aeo_field_missing_for_fill``), при этом
``convert._donor_inn_for_supplement`` возвращает непустую строку только из цифр.

Одна строка выходного JSONL — **не** полный сертификат, а объект ``branch_supplement_aeo_inn_gap_v1`` (удобно для отдельного аудита и просмотра). В запись входят имена с корня сертификата (**``certificate_EduOrgFullName``** / **``certificate_EduOrgShortName``**) и дубли имён корневой AEO (**``root_AEO_FullName``** / **``root_AEO_ShortName``**) рядом со сжатой карточкой **``root_ActualEducationOrganization``**. Для быстрого просмотра карточек: ``--limit N`` или готовая выборка ``examples/branch_supplement_aeo_inn_gap_sample.jsonl`` (первые 40 записей с полного снимка, если он был собран локально; после дозаполнения INN с корня при разном ``Id`` у AEO выборка может стать **пустой**).

Пример::

    python tools/extract_branch_supplement_aeo_inn_gap_jsonl.py out/data.jsonl \\
        -o examples/branch_supplement_aeo_inn_gap.jsonl

    Подмножество без слова «филиал» в ``supplement ActualEducationOrganization.FullName``::

        python tools/extract_branch_supplement_aeo_inn_gap_jsonl.py out/data.jsonl \\
            -o examples/branch_supplement_aeo_inn_gap_no_filial_supplement_aeo_fullname.jsonl \\
            --without-filial-in-supplement-aeo-fullname
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from convert import (  # noqa: E402
    _aeo_field_missing_for_fill,
    _aeo_uid_token,
    _donor_inn_for_supplement,
    _donor_ogrn_for_supplement,
)


RECORD_KIND = "branch_supplement_aeo_inn_gap_v1"
_FILIAL_IN_NAME = re.compile("филиал", re.IGNORECASE)


def _supplement_aeo_fullname_has_filial(sa: dict[str, Any]) -> bool:
    fn = sa.get("FullName")
    return isinstance(fn, str) and bool(_FILIAL_IN_NAME.search(fn))


def _pick_supplement_meta(sup: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("IsForBranch", "StatusName", "Number", "SerialNumber", "FormNumber"):
        if k in sup:
            out[k] = sup[k]
    return out


def _slim_aeo(aeo: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "Id",
        "FullName",
        "ShortName",
        "INN",
        "OGRN",
        "KPP",
        "HeadEduOrgId",
        "IsBranch",
        "RegionName",
    )
    return {k: aeo[k] for k in keys if k in aeo}


def iter_gap_records(
    row: dict[str, Any],
    *,
    without_filial_in_supplement_aeo_fullname: bool = False,
) -> Any:
    ra = row.get("ActualEducationOrganization")
    if not isinstance(ra, dict):
        return
    rid = _aeo_uid_token(ra.get("Id"))
    if not rid:
        return
    cert_id = row.get("Id")
    for idx, sup in enumerate(row.get("Supplements") or []):
        if not isinstance(sup, dict):
            continue
        sa = sup.get("ActualEducationOrganization")
        if not isinstance(sa, dict):
            continue
        sid = _aeo_uid_token(sa.get("Id"))
        if not sid or sid == rid:
            continue
        if not _aeo_field_missing_for_fill(sa, "INN"):
            continue
        donor_inn = _donor_inn_for_supplement(ra, row)
        if not donor_inn:
            continue
        if without_filial_in_supplement_aeo_fullname and _supplement_aeo_fullname_has_filial(sa):
            continue
        donor_ogrn = _donor_ogrn_for_supplement(ra, row)
        yield {
            "record_kind": RECORD_KIND,
            "certificate_id": cert_id,
            "supplement_index": idx,
            "root_aeo_id": ra.get("Id"),
            "supplement_aeo_id": sa.get("Id"),
            "donor_inn_digits": donor_inn,
            "donor_ogrn_digits": donor_ogrn,
            "EduOrgINN": row.get("EduOrgINN"),
            "EduOrgOGRN": row.get("EduOrgOGRN"),
            # Имя организации на корне Certificate (в XML «выше» Supplements), для сверки с корневой AEO.
            "certificate_EduOrgFullName": row.get("EduOrgFullName"),
            "certificate_EduOrgShortName": row.get("EduOrgShortName"),
            # Дубли имён корневой AEO на верхнем уровне (полная карточка по-прежнему в root_ActualEducationOrganization).
            "root_AEO_FullName": ra.get("FullName"),
            "root_AEO_ShortName": ra.get("ShortName"),
            "root_ActualEducationOrganization": _slim_aeo(ra),
            "supplement_ActualEducationOrganization": _slim_aeo(sa),
            "supplement_meta": _pick_supplement_meta(sup),
        }


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "JSONL карточек supplement AEO: Id ≠ корня, INN пуст, донор INN есть на корне сертификата."
        ),
    )
    p.add_argument("jsonl", type=Path, help="Входной JSONL сертификатов (одна строка = Certificate)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_ROOT / "examples" / "branch_supplement_aeo_inn_gap.jsonl",
        help=f"Выходной JSONL (по умолчанию {_ROOT / 'examples' / 'branch_supplement_aeo_inn_gap.jsonl'})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Максимум записей в выходной файл (для просмотра карточек без полного прохода)",
    )
    p.add_argument(
        "--without-filial-in-supplement-aeo-fullname",
        action="store_true",
        help=(
            "Оставить только карточки, где в supplement ActualEducationOrganization.FullName "
            "нет подстроки «филиал» (без учёта регистра); пустое имя тоже проходит фильтр."
        ),
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    n = 0
    lim = args.limit
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.jsonl.open(encoding="utf-8", errors="replace") as inp, args.output.open(
        "w", encoding="utf-8"
    ) as out:
        for line in inp:
            if lim is not None and n >= lim:
                break
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            for rec in iter_gap_records(
                row,
                without_filial_in_supplement_aeo_fullname=args.without_filial_in_supplement_aeo_fullname,
            ):
                if lim is not None and n >= lim:
                    break
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            if lim is not None and n >= lim:
                break

    print(f"Записано строк: {n}\nФайл: {args.output.resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
