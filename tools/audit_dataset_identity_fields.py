#!/usr/bin/env python3
"""Сводная статистика по полям, пригодным как кандидаты на первичный ключ (ИНН/ОГРН).

Считается по **одной строке JSONL = один сертификат** для плоских полей на корне
(``EduOrgINN``, ``EduOrgOGRN``) и для полей ``INN`` / ``OGRN`` в объекте
``ActualEducationOrganization`` на **корне** сертификата.

**IndividualEntrepreneurINN** в отчёт не входит.

Отдельно — **по каждой** карточке ``ActualEducationOrganization`` внутри
``Supplements[]`` (только если значение — ``dict``): те же разрезы для ``INN`` и
``OGRN`` (в JSON ключ именно ``OGRN``). Дополнительно: для карточек с пустым
``INN``/``OGRN`` — сколько из них имеют **те же UID-поля**, что и корневая
``ActualEducationOrganization``: непустой ``Id`` (реестровый UID ОО, без учёта регистра
шестнадцатеричных символов) и согласованный ``HeadEduOrgId`` (если непустой с обеих сторон —
должен совпадать). Не используются ``Id`` сертификата и ``Id`` элемента ``Supplements[]``.

Очистка для критерия «только цифры»: удаление пробелов и дефисов, **как у**
``convert.cast_id_number`` и в логике подсчёта этого отчёта.

Аудит **не** читает XML: он отражает только то, что уже записано в JSONL.
Счётчики ``nonempty_not_digits_only_after_clean`` и ``sample_nonempty_not_digit_only_ids``
относятся к строкам, где в файле по-прежнему есть **непустая** строка, не проходящая
``str.isdigit()`` после той же очистки.

Дополнительно — счётчики **``*borrowable*``**: для **текущего** JSONL сколько раз при совпадении
UID карточек AEO (как у ``*same_aeo_Id_as_root``) пустое **INN**/**OGRN** в приложении **ещё** можно
было бы заполнить из корневой AEO **и/или** из **EduOrgINN** / **EduOrgOGRN** на корне сертификата
(те же критерии «только цифры» после очистки); и сколько **сертификатов**, где пустое **INN**/**OGRN**
у корневой AEO **ещё** можно было бы заполнить из supplement с тем же UID **или** из **EduOrgINN** /
**EduOrgOGRN**. Правила доноров совпадают с ``fill_aeo_coherent_inn_ogrn`` в ``convert.py`` (по умолчанию
включён); на выходе конвертера с умолчанием эти счётчики часто **нулевые**.

На уровне **сертификата** поля ``would_drop_if_require_*`` показывают, сколько строк JSONL
**не** удастся оставить в датасете, если PK обязан быть **непустым** в этом поле или
**непустой строкой только из цифр после очистки** соответственно.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _ROOT / "examples" / "dataset_identity_fields_audit.json"
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
    """Скаляр UID после strip; для сравнения используется lower() (UUID в разном регистре)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s.lower()


def _aeo_supplement_uid_matches_root(root_aeo: Any, sup_aeo: Any) -> bool:
    """True, если карточка AEO в приложении ссылается на ту же ОО по UID-полям, что и корневая AEO.

    Сравниваются только поля ``ActualEducationOrganization``:
    ``Id`` (оба непустые и равны с учётом регистра) и ``HeadEduOrgId``: если на корне
    и в приложении значение непустое с обеих сторон — должны совпадать; если хотя бы
    с одной стороны пусто — условие по этому полю не мешает (в выгрузке часто ключ
    отсутствует с обеих сторон).
    """
    if not isinstance(root_aeo, dict) or not isinstance(sup_aeo, dict):
        return False
    rid = _aeo_uid_token(root_aeo.get("Id"))
    sid = _aeo_uid_token(sup_aeo.get("Id"))
    if rid is None or sid is None or rid != sid:
        return False
    rh = _aeo_uid_token(root_aeo.get("HeadEduOrgId"))
    sh = _aeo_uid_token(sup_aeo.get("HeadEduOrgId"))
    if rh and sh:
        return rh == sh
    return True


def _aeo_field_missing_or_empty(aeo: Any, field_name: str) -> bool:
    """То же условие «missing_or_empty», что в _consume_aeo_field до nonempty."""
    return (
        not isinstance(aeo, dict)
        or field_name not in aeo
        or not _nonempty_scalar(aeo.get(field_name))
    )


def _aeo_field_nonempty_digits_only_after_clean(aeo: Any, field_name: str) -> bool:
    """True, если поле есть, непустое и после очистки только цифры (пригодный донор для «заимствования»)."""
    if not isinstance(aeo, dict) or field_name not in aeo or not _nonempty_scalar(aeo.get(field_name)):
        return False
    cleaned = _clean_digits_candidate(str(aeo.get(field_name)))
    return bool(cleaned and cleaned.isdigit())


def _root_scalar_nonempty_digits_only_after_clean(row: dict[str, Any], key: str) -> bool:
    """То же для скаляра на корне сертификата (EduOrgINN, EduOrgOGRN)."""
    if key not in row or not _nonempty_scalar(row.get(key)):
        return False
    cleaned = _clean_digits_candidate(str(row.get(key)))
    return bool(cleaned and cleaned.isdigit())


@dataclass
class FieldCounter:
    """Счётчики по одному полю на фиксированном числе строк (сертификатов или карточек)."""

    total_lines: int = 0
    missing_or_empty: int = 0
    nonempty: int = 0
    nonempty_digits_only_after_clean: int = 0
    nonempty_not_digits_only_after_clean: int = 0
    sample_not_digit_certificate_ids: list[str] = field(default_factory=list)

    def finalize(self, max_samples: int) -> dict[str, Any]:
        drop_nonempty = self.missing_or_empty
        drop_digits = self.total_lines - self.nonempty_digits_only_after_clean
        return {
            "total_lines": self.total_lines,
            "missing_or_empty": self.missing_or_empty,
            "nonempty": self.nonempty,
            "nonempty_digits_only_after_clean": self.nonempty_digits_only_after_clean,
            "nonempty_not_digits_only_after_clean": self.nonempty_not_digits_only_after_clean,
            "would_drop_if_require_nonempty": drop_nonempty,
            "would_drop_if_require_digits_only_after_clean": drop_digits,
            "sample_nonempty_not_digit_only_ids": self.sample_not_digit_certificate_ids[
                :max_samples
            ],
        }


def _consume_scalar(counter: FieldCounter, row: dict[str, Any], key: str, cid: str, max_s: int) -> None:
    counter.total_lines += 1
    if key not in row or not _nonempty_scalar(row.get(key)):
        counter.missing_or_empty += 1
        return
    counter.nonempty += 1
    cleaned = _clean_digits_candidate(str(row.get(key)))
    if cleaned and cleaned.isdigit():
        counter.nonempty_digits_only_after_clean += 1
    else:
        counter.nonempty_not_digits_only_after_clean += 1
        if len(counter.sample_not_digit_certificate_ids) < max_s:
            counter.sample_not_digit_certificate_ids.append(cid)


def _consume_aeo_field(
    counter: FieldCounter,
    aeo: Any,
    field: str,
    cid: str,
    max_s: int,
) -> None:
    counter.total_lines += 1
    if not isinstance(aeo, dict) or field not in aeo or not _nonempty_scalar(aeo.get(field)):
        counter.missing_or_empty += 1
        return
    counter.nonempty += 1
    cleaned = _clean_digits_candidate(str(aeo.get(field)))
    if cleaned and cleaned.isdigit():
        counter.nonempty_digits_only_after_clean += 1
    else:
        counter.nonempty_not_digits_only_after_clean += 1
        if len(counter.sample_not_digit_certificate_ids) < max_s:
            counter.sample_not_digit_certificate_ids.append(cid)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Сводный аудит EduOrgINN, EduOrgOGRN и INN/OGRN в ActualEducationOrganization.",
    )
    p.add_argument("jsonl", type=Path, help="Входной .jsonl")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON-отчёт (по умолчанию {_DEFAULT_OUT})",
    )
    p.add_argument(
        "--max-samples",
        type=int,
        default=80,
        metavar="N",
        help="Максимум Id в sample_nonempty_not_digit_only_ids на каждое поле (сертификат)",
    )
    args = p.parse_args()
    if not args.jsonl.is_file():
        print(f"Нет файла: {args.jsonl}", file=sys.stderr)
        return 2

    c_edu_inn = FieldCounter()
    c_edu_ogrn = FieldCounter()
    c_root_aeo_inn = FieldCounter()
    c_root_aeo_ogrn = FieldCounter()

    c_sup_inn = FieldCounter()
    c_sup_ogrn = FieldCounter()

    total_certs = 0
    sup_inn_missing_same_aeo_id_as_root = 0
    sup_ogrn_missing_same_aeo_id_as_root = 0
    sup_inn_missing_same_uid_root_has_borrowable_inn = 0
    sup_ogrn_missing_same_uid_root_has_borrowable_ogrn = 0
    cert_root_inn_missing_any_sup_same_uid_has_borrowable_inn = 0
    cert_root_ogrn_missing_any_sup_same_uid_has_borrowable_ogrn = 0

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
            cid = str(row.get("Id", "")).strip()

            _consume_scalar(c_edu_inn, row, "EduOrgINN", cid, args.max_samples)
            _consume_scalar(c_edu_ogrn, row, "EduOrgOGRN", cid, args.max_samples)

            aeo_root = row.get("ActualEducationOrganization")
            _consume_aeo_field(c_root_aeo_inn, aeo_root, "INN", cid, args.max_samples)
            _consume_aeo_field(c_root_aeo_ogrn, aeo_root, "OGRN", cid, args.max_samples)

            edu_inn_donor = _root_scalar_nonempty_digits_only_after_clean(row, "EduOrgINN")
            edu_ogrn_donor = _root_scalar_nonempty_digits_only_after_clean(row, "EduOrgOGRN")
            root_inn_donor = _aeo_field_nonempty_digits_only_after_clean(aeo_root, "INN") or edu_inn_donor
            root_ogrn_donor = _aeo_field_nonempty_digits_only_after_clean(aeo_root, "OGRN") or edu_ogrn_donor

            any_sup_inn_donor = False
            any_sup_ogrn_donor = False
            for sup in row.get("Supplements") or []:
                if not isinstance(sup, dict):
                    continue
                saeo = sup.get("ActualEducationOrganization")
                if not isinstance(saeo, dict):
                    continue
                same_uid = _aeo_supplement_uid_matches_root(aeo_root, saeo)
                if same_uid and _aeo_field_missing_or_empty(saeo, "INN"):
                    sup_inn_missing_same_aeo_id_as_root += 1
                if same_uid and _aeo_field_missing_or_empty(saeo, "OGRN"):
                    sup_ogrn_missing_same_aeo_id_as_root += 1
                if same_uid and _aeo_field_missing_or_empty(saeo, "INN") and root_inn_donor:
                    sup_inn_missing_same_uid_root_has_borrowable_inn += 1
                if same_uid and _aeo_field_missing_or_empty(saeo, "OGRN") and root_ogrn_donor:
                    sup_ogrn_missing_same_uid_root_has_borrowable_ogrn += 1
                if same_uid and _aeo_field_nonempty_digits_only_after_clean(saeo, "INN"):
                    any_sup_inn_donor = True
                if same_uid and _aeo_field_nonempty_digits_only_after_clean(saeo, "OGRN"):
                    any_sup_ogrn_donor = True
                _consume_aeo_field(c_sup_inn, saeo, "INN", cid, args.max_samples)
                _consume_aeo_field(c_sup_ogrn, saeo, "OGRN", cid, args.max_samples)

            if _aeo_field_missing_or_empty(aeo_root, "INN") and (any_sup_inn_donor or edu_inn_donor):
                cert_root_inn_missing_any_sup_same_uid_has_borrowable_inn += 1
            if _aeo_field_missing_or_empty(aeo_root, "OGRN") and (any_sup_ogrn_donor or edu_ogrn_donor):
                cert_root_ogrn_missing_any_sup_same_uid_has_borrowable_ogrn += 1

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    out: dict[str, Any] = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Сводка по кандидатам на PK: EduOrgINN, EduOrgOGRN, INN и OGRN в корневом "
            "ActualEducationOrganization, а также INN/OGRN в карточках AEO внутри Supplements[]. "
            "Для supplement-секции total_lines = число карточек AEO-dict, не число сертификатов. "
            "Поле IndividualEntrepreneurINN в отчёт не входит. "
            "Счётчики *same_aeo_Id_as_root* — карточки в приложении с missing_or_empty INN/OGRN, если по полям "
            "ActualEducationOrganization.Id и (при двусторонней заполненности) HeadEduOrgId карточка приложения "
            "совпадает с корневой AEO; не путать с Id сертификата или Id элемента Supplements[]. "
            "Счётчики *borrowable* — остаточные случаи в данном JSONL: при совпадении UID пустое INN/OGRN, "
            "для которого по тем же правилам, что fill_aeo_coherent_inn_ogrn в convert.py (по умолчанию), "
            "ещё есть донор (nonempty_digits_only_after_clean; для AEO — также **EduOrgINN** / **EduOrgOGRN** "
            "на корне сертификата; см. glossary). После конвертации с умолчанию часто нули."
        ),
        "aeo_uid_fields_compared_ru": [
            "ActualEducationOrganization.Id — реестровый UID образовательной организации",
            "ActualEducationOrganization.HeadEduOrgId — UID головной организации; участвует в сравнении только если непустой и на корне, и в приложении",
        ],
        "certificate_lines_total": total_certs,
        "per_certificate": {
            "EduOrgINN": c_edu_inn.finalize(args.max_samples),
            "EduOrgOGRN": c_edu_ogrn.finalize(args.max_samples),
            "root_ActualEducationOrganization_INN": c_root_aeo_inn.finalize(args.max_samples),
            "root_ActualEducationOrganization_OGRN": c_root_aeo_ogrn.finalize(args.max_samples),
            "root_INN_missing_or_empty_borrowable_from_supplement_aeo_same_uid": cert_root_inn_missing_any_sup_same_uid_has_borrowable_inn,
            "root_OGRN_missing_or_empty_borrowable_from_supplement_aeo_same_uid": cert_root_ogrn_missing_any_sup_same_uid_has_borrowable_ogrn,
        },
        "per_supplement_aeo_card": {
            "supplement_aeo_cards_total": c_sup_inn.total_lines,
            "INN": c_sup_inn.finalize(args.max_samples),
            "OGRN": c_sup_ogrn.finalize(args.max_samples),
            "INN_missing_or_empty_with_same_aeo_Id_as_root": sup_inn_missing_same_aeo_id_as_root,
            "OGRN_missing_or_empty_with_same_aeo_Id_as_root": sup_ogrn_missing_same_aeo_id_as_root,
            "INN_missing_same_uid_supplement_could_borrow_from_root_aeo": sup_inn_missing_same_uid_root_has_borrowable_inn,
            "OGRN_missing_same_uid_supplement_could_borrow_from_root_aeo": sup_ogrn_missing_same_uid_root_has_borrowable_ogrn,
        },
        "glossary_ru": {
            "missing_or_empty": "нет ключа в JSON, null или пустая строка после strip",
            "digits_only_after_clean": "после удаления пробелов и дефисов строка непустая и str.isdigit()",
            "would_drop_if_require_nonempty": "сколько строк (сертификатов) или карточек AEO не пройдут отбор «PK непустой»",
            "would_drop_if_require_digits_only_after_clean": "сколько строк/карточек не пройдут отбор «PK = только цифры после очистки»",
            "INN_missing_or_empty_with_same_aeo_Id_as_root": (
                "число карточек AEO в Supplements[], где INN missing_or_empty, при этом UID-поля карточки "
                "совпадают с корневой ActualEducationOrganization (см. aeo_uid_fields_compared_ru; часто дубликат без ИНН)"
            ),
            "OGRN_missing_or_empty_with_same_aeo_Id_as_root": (
                "то же для OGRN в карточке приложения при том же совпадении UID-полей с корневой AEO"
            ),
            "INN_missing_same_uid_supplement_could_borrow_from_root_aeo": (
                "карточка AEO в Supplements[]: INN missing_or_empty, UID как у корневой AEO, "
                "и есть пригодный донор INN: корневая AEO **или** **EduOrgINN** на сертификате "
                "(nonempty_digits_only_after_clean; то же, что может заполнить convert.py с fill_aeo_coherent_inn_ogrn)"
            ),
            "OGRN_missing_same_uid_supplement_could_borrow_from_root_aeo": (
                "то же для OGRN: донор — корневая AEO **или** **EduOrgOGRN** на сертификате"
            ),
            "root_INN_missing_or_empty_borrowable_from_supplement_aeo_same_uid": (
                "число строк JSONL (сертификатов), где у корневой AEO INN missing_or_empty, "
                "и есть донор: хотя бы одна supplement-карточка AEO с тем же UID и INN "
                "nonempty_digits_only_after_clean **или** **EduOrgINN** на корне сертификата "
                "(остаток после convert.py с умолчанию — часто 0)"
            ),
            "root_OGRN_missing_or_empty_borrowable_from_supplement_aeo_same_uid": (
                "то же для OGRN корневой AEO: донор supplement с тем же UID **или** **EduOrgOGRN** "
                "(остаток после convert.py с умолчанию — часто 0)"
            ),
            "borrowable_donor_value_ru": (
                "донор: ключ есть, значение непустое после strip, после удаления пробелов и дефисов — непустая строка из цифр "
                "(как nonempty_digits_only_after_clean в этом отчёте); для полей AEO дополнительно учитываются "
                "**EduOrgINN** / **EduOrgOGRN** на корне Certificate как источник INN/OGRN для той же организации; "
                "конфликты доноров в convert.py не разрешаются, только учёт"
            ),
            "note_convert_identity_ru": (
                "В свежем JSONL от convert.py по умолчанию нецифровые ИНН/КПП/ОГРН из XML не хранятся как строка: "
                "ключ отсутствует (omit_null_keys) или null (--include-null-keys); см. non_digit_ids в --report convert.py."
            ),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Сертификатов (строк JSONL): {total_certs}\n"
        f"Карточек AEO в приложениях: {c_sup_inn.total_lines}\n"
        f"Отчёт: {args.output.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
