#!/usr/bin/env python3
"""Аудит: при проблемах с полями идентичности — как соотносится Id AEO в приложении с Id корневой AEO.

Критерии «проблема с полем», как в ``tools/audit_dataset_identity_fields.py``:
``EduOrgINN``, ``EduOrgOGRN`` на корне сертификата; ``INN`` и ``OGRN`` в корневой
``ActualEducationOrganization``; ``INN`` и ``OGRN`` в каждой карточке
``ActualEducationOrganization`` внутри ``Supplements[]`` (только ``dict``-карточки).
Проблема: ключ отсутствует / null / пустая строка после ``strip``, **или** после
удаления пробелов и дефисов остаток непустой и **не** ``str.isdigit()``.

**Строка сертификата попадает в фильтр**, если есть **хотя бы одна** такая проблема
где-либо на этой строке.

Сравнение **Id** только по полю ``ActualEducationOrganization.Id`` (после
``strip`` и без учёта регистра), без ``HeadEduOrgId`` — отдельно от полного
совпадения UID в ``audit_dataset_identity_fields.py``.

Аудит **не** читает XML.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "dataset_aeo_supplement_root_id_identity_issues.json"
_WS_HYPHEN = re.compile(r"[\s\-]")


def _nonempty_scalar(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return True


def _clean_digits_candidate(raw: str) -> str:
    return _WS_HYPHEN.sub("", str(raw).strip())


def _aeo_uid_token(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s.lower()


def _scalar_field_has_identity_issue(row: dict[str, Any], key: str) -> bool:
    if key not in row or not _nonempty_scalar(row.get(key)):
        return True
    cleaned = _clean_digits_candidate(str(row.get(key)))
    return not (cleaned and cleaned.isdigit())


def _aeo_field_has_identity_issue(aeo: Any, field_name: str) -> bool:
    if not isinstance(aeo, dict) or field_name not in aeo or not _nonempty_scalar(
        aeo.get(field_name)
    ):
        return True
    cleaned = _clean_digits_candidate(str(aeo.get(field_name)))
    return not (cleaned and cleaned.isdigit())


def _row_has_any_identity_issue(row: dict[str, Any]) -> bool:
    if _scalar_field_has_identity_issue(row, "EduOrgINN"):
        return True
    if _scalar_field_has_identity_issue(row, "EduOrgOGRN"):
        return True
    root = row.get("ActualEducationOrganization")
    if _aeo_field_has_identity_issue(root, "INN"):
        return True
    if _aeo_field_has_identity_issue(root, "OGRN"):
        return True
    for sup in row.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        saeo = sup.get("ActualEducationOrganization")
        if not isinstance(saeo, dict):
            continue
        if _aeo_field_has_identity_issue(saeo, "INN"):
            return True
        if _aeo_field_has_identity_issue(saeo, "OGRN"):
            return True
    return False


def _supplement_aeo_has_inn_or_ogrn_issue(saeo: dict[str, Any]) -> bool:
    return _aeo_field_has_identity_issue(saeo, "INN") or _aeo_field_has_identity_issue(
        saeo, "OGRN"
    )


def _classify_aeo_id_vs_root(
    root_aeo: Any, sup_aeo: dict[str, Any]
) -> str:
    rid = _aeo_uid_token(root_aeo.get("Id")) if isinstance(root_aeo, dict) else None
    sid = _aeo_uid_token(sup_aeo.get("Id"))
    if rid is not None and sid is not None:
        return "same_Id" if rid == sid else "different_Id"
    return "incomparable_Id"


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "При проблемах с ИНН/ОГРН (как в audit_dataset_identity_fields): "
            "сравнить Id корневой AEO и AEO в каждом Supplement."
        ),
    )
    p.add_argument("jsonl", type=Path, help="Входной .jsonl")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON-отчёт (по умолчанию {_DEFAULT_OUT})",
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    total_certs = 0
    certs_with_issue = 0
    certs_with_issue_nonempty_supplements = 0

    # Среди строк с проблемой: все supplement AEO-dict
    issue_sup_cards_total = 0
    issue_sup_same_id = 0
    issue_sup_diff_id = 0
    issue_sup_inc_id = 0

    # Среди строк с проблемой: только карточки supplement AEO с проблемой INN или OGRN
    issue_sup_cards_inn_ogrn_problem = 0
    sub_same_id = 0
    sub_diff_id = 0
    sub_inc_id = 0

    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            try:
                row = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            total_certs += 1
            if not _row_has_any_identity_issue(row):
                continue
            certs_with_issue += 1

            sups = row.get("Supplements") or []
            if isinstance(sups, list) and any(isinstance(x, dict) for x in sups):
                certs_with_issue_nonempty_supplements += 1

            aeo_root = row.get("ActualEducationOrganization")
            for sup in sups:
                if not isinstance(sup, dict):
                    continue
                saeo = sup.get("ActualEducationOrganization")
                if not isinstance(saeo, dict):
                    continue
                bucket = _classify_aeo_id_vs_root(aeo_root, saeo)
                issue_sup_cards_total += 1
                if bucket == "same_Id":
                    issue_sup_same_id += 1
                elif bucket == "different_Id":
                    issue_sup_diff_id += 1
                else:
                    issue_sup_inc_id += 1

                if _supplement_aeo_has_inn_or_ogrn_issue(saeo):
                    issue_sup_cards_inn_ogrn_problem += 1
                    if bucket == "same_Id":
                        sub_same_id += 1
                    elif bucket == "different_Id":
                        sub_diff_id += 1
                    else:
                        sub_inc_id += 1

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    out: dict[str, Any] = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Строки JSONL, где есть хотя бы одна «проблема» с полями идентичности в смысле "
            "`tools/audit_dataset_identity_fields.py` (EduOrgINN, EduOrgOGRN, INN/OGRN у корневой "
            "ActualEducationOrganization и INN/OGRN у каждой dict-карточки AEO в Supplements[]). "
            "Для таких строк считается, как соотносится `ActualEducationOrganization.Id` в приложении "
            "с `Id` корневой AEO (strip, сравнение без учёта регистра). "
            "Не путать с `Id` сертификата или `Supplements[].Id`."
        ),
        "identity_issue_definition_ru": (
            "Проблема: поле отсутствует, null или пустая строка после strip; либо после удаления "
            "пробелов и дефисов остаток непустой и не состоит только из цифр (как nonempty_not_digits_only_after_clean)."
        ),
        "certificate_lines_total": total_certs,
        "certificates_with_any_identity_issue": certs_with_issue,
        "certificates_with_issue_and_at_least_one_supplement_dict": certs_with_issue_nonempty_supplements,
        "when_certificate_has_identity_issue_supplement_aeo_dict_cards": {
            "total_cards": issue_sup_cards_total,
            "same_ActualEducationOrganization_Id_as_root": issue_sup_same_id,
            "different_ActualEducationOrganization_Id_from_root": issue_sup_diff_id,
            "incomparable_Id_missing_on_root_or_supplement_aeo": issue_sup_inc_id,
        },
        "when_certificate_has_identity_issue_and_supplement_aeo_has_inn_or_ogrn_issue": {
            "total_cards": issue_sup_cards_inn_ogrn_problem,
            "same_ActualEducationOrganization_Id_as_root": sub_same_id,
            "different_ActualEducationOrganization_Id_from_root": sub_diff_id,
            "incomparable_Id_missing_on_root_or_supplement_aeo": sub_inc_id,
        },
        "glossary_ru": {
            "same_ActualEducationOrganization_Id_as_root": (
                "у корневой и supplement-карточки AEO непустой Id и совпадает после strip и lower()"
            ),
            "different_ActualEducationOrganization_Id_from_root": (
                "оба Id непустые, но токены различаются"
            ),
            "incomparable_Id_missing_on_root_or_supplement_aeo": (
                "у корневой AEO или у карточки в приложении Id отсутствует / пустой после strip"
            ),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Сертификатов: {total_certs}, с проблемой идентичности: {certs_with_issue}\n"
        f"Отчёт: {args.output.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
