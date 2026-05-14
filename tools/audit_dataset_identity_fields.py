#!/usr/bin/env python3
"""Сводная статистика по полям, пригодным как кандидаты на первичный ключ (ИНН/ОГРН).

Считается по **одной строке JSONL = один сертификат** для плоских полей на корне
(``EduOrgINN``, ``EduOrgOGRN``) и для полей ``INN`` / ``OGRN`` в объекте
``ActualEducationOrganization`` на **корне** сертификата.

**IndividualEntrepreneurINN** в отчёт не входит.

Отдельно — **по каждой** карточке ``ActualEducationOrganization`` внутри
``Supplements[]`` (только если значение — ``dict``): те же разрезы для ``INN`` и
``OGRN`` (в JSON ключ именно ``OGRN``).

Очистка для критерия «только цифры»: удаление пробелов и дефисов, **как у**
``convert.cast_id_number`` и в логике подсчёта этого отчёта.

Аудит **не** читает XML: он отражает только то, что уже записано в JSONL.
Счётчики ``nonempty_not_digits_only_after_clean`` и ``sample_nonempty_not_digit_only_ids``
относятся к строкам, где в файле по-прежнему есть **непустая** строка, не проходящая
``str.isdigit()`` после той же очистки.

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

            for sup in row.get("Supplements") or []:
                if not isinstance(sup, dict):
                    continue
                saeo = sup.get("ActualEducationOrganization")
                if not isinstance(saeo, dict):
                    continue
                _consume_aeo_field(c_sup_inn, saeo, "INN", cid, args.max_samples)
                _consume_aeo_field(c_sup_ogrn, saeo, "OGRN", cid, args.max_samples)

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
            "Поле IndividualEntrepreneurINN в отчёт не входит."
        ),
        "certificate_lines_total": total_certs,
        "per_certificate": {
            "EduOrgINN": c_edu_inn.finalize(args.max_samples),
            "EduOrgOGRN": c_edu_ogrn.finalize(args.max_samples),
            "root_ActualEducationOrganization_INN": c_root_aeo_inn.finalize(args.max_samples),
            "root_ActualEducationOrganization_OGRN": c_root_aeo_ogrn.finalize(args.max_samples),
        },
        "per_supplement_aeo_card": {
            "supplement_aeo_cards_total": c_sup_inn.total_lines,
            "INN": c_sup_inn.finalize(args.max_samples),
            "OGRN": c_sup_ogrn.finalize(args.max_samples),
        },
        "glossary_ru": {
            "missing_or_empty": "нет ключа в JSON, null или пустая строка после strip",
            "digits_only_after_clean": "после удаления пробелов и дефисов строка непустая и str.isdigit()",
            "would_drop_if_require_nonempty": "сколько строк (сертификатов) или карточек AEO не пройдут отбор «PK непустой»",
            "would_drop_if_require_digits_only_after_clean": "сколько строк/карточек не пройдут отбор «PK = только цифры после очистки»",
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
