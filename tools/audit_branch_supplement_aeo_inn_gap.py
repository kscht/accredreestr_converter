#!/usr/bin/env python3
"""Аудит JSONL, сгенерированного ``tools/extract_branch_supplement_aeo_inn_gap_jsonl.py``.

Сводка: число записей, ``IsForBranch`` у родительского ``Supplement``, пустой **OGRN** у supplement AEO при наличии донора «сверху`` (как ``convert._donor_ogrn_for_supplement`` по сохранённым полям), непустой ``HeadEduOrgId`` у supplement AEO, согласованность ``donor_inn_digits`` с полями в ``root_ActualEducationOrganization`` / ``EduOrgINN``.

Вход — **не** полные сертификаты, а строки с ``record_kind``: ``branch_supplement_aeo_inn_gap_v1``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from convert import (  # noqa: E402
    _aeo_field_missing_for_fill,
    _scalar_digits_only_string,
)

_EXPECTED_KIND = "branch_supplement_aeo_inn_gap_v1"
_DEFAULT_OUT = _ROOT / "examples" / "dataset_branch_supplement_aeo_inn_gap_audit.json"

_WS_HYPHEN = re.compile(r"[\s\-]")


def _label(v: Any) -> str:
    if v is None:
        return "<null>"
    if isinstance(v, str):
        s = v.strip()
        return s if s else "<empty>"
    return str(v)


def _meta_scalar_label(v: Any) -> str:
    """Метка для полей supplement (IsForBranch и т.д.): bool → 0/1 для читаемости в JSON."""
    if v is None:
        return "<null>"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v == int(v):
            return str(int(v))
        return str(v)
    if isinstance(v, str):
        s = v.strip()
        return s if s else "<empty>"
    return str(v)


def _reconstruct_donor_inn_from_record(rec: dict[str, Any]) -> str | None:
    ra = rec.get("root_ActualEducationOrganization")
    if isinstance(ra, dict):
        d = _scalar_digits_only_string(ra.get("INN"))
        if d:
            return d
    return _scalar_digits_only_string(rec.get("EduOrgINN"))


def _reconstruct_donor_ogrn_from_record(rec: dict[str, Any]) -> str | None:
    ra = rec.get("root_ActualEducationOrganization")
    if isinstance(ra, dict):
        d = _scalar_digits_only_string(ra.get("OGRN"))
        if d:
            return d
    return _scalar_digits_only_string(rec.get("EduOrgOGRN"))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Аудит JSONL branch_supplement_aeo_inn_gap (из extract_branch_supplement_aeo_inn_gap_jsonl).",
    )
    p.add_argument("jsonl", type=Path, help="Входной .jsonl (объекты record_kind branch_supplement_aeo_inn_gap_v1)")
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

    total = 0
    bad_kind = 0
    donor_inn_mismatch = 0
    sup_ogrn_missing_with_donor = 0
    sup_ogrn_missing_no_donor = 0
    sup_head_nonempty = 0
    is_for_branch = Counter()
    inn_root_vs_eduorg_only = {"from_root_aeo_inn": 0, "from_eduorg_inn_only": 0}

    for line in args.jsonl.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        total += 1
        if rec.get("record_kind") != _EXPECTED_KIND:
            bad_kind += 1
            continue

        d_inn_file = rec.get("donor_inn_digits")
        d_inn_re = _reconstruct_donor_inn_from_record(rec)
        if (
            isinstance(d_inn_file, str)
            and d_inn_re
            and _WS_HYPHEN.sub("", d_inn_file.strip()) != d_inn_re
        ):
            donor_inn_mismatch += 1

        ra = rec.get("root_ActualEducationOrganization")
        sa = rec.get("supplement_ActualEducationOrganization")
        if isinstance(sa, dict):
            if _aeo_field_missing_for_fill(sa, "OGRN"):
                dog = _reconstruct_donor_ogrn_from_record(rec)
                if dog:
                    sup_ogrn_missing_with_donor += 1
                else:
                    sup_ogrn_missing_no_donor += 1
            hv = sa.get("HeadEduOrgId")
            if hv is not None and isinstance(hv, str) and hv.strip():
                sup_head_nonempty += 1

        if isinstance(ra, dict):
            r_inn = _scalar_digits_only_string(ra.get("INN"))
            e_inn = _scalar_digits_only_string(rec.get("EduOrgINN"))
            if r_inn:
                inn_root_vs_eduorg_only["from_root_aeo_inn"] += 1
            elif e_inn:
                inn_root_vs_eduorg_only["from_eduorg_inn_only"] += 1

        meta = rec.get("supplement_meta")
        if isinstance(meta, dict) and "IsForBranch" in meta:
            is_for_branch[_meta_scalar_label(meta.get("IsForBranch"))] += 1
        else:
            is_for_branch["<key absent>"] += 1

    try:
        src_rel = str(args.jsonl.resolve().relative_to(_ROOT))
    except ValueError:
        src_rel = str(args.jsonl.resolve())

    out = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Аудит выборки ``branch_supplement_aeo_inn_gap_v1``: supplement ``ActualEducationOrganization`` "
            "с **другим** ``Id``, чем у корневой AEO, при пустом **INN** в supplement и непустом доноре INN "
            "на корне сертификата (см. ``tools/extract_branch_supplement_aeo_inn_gap_jsonl.py``). "
            "Поля ``donor_inn_digits`` / ``donor_ogrn_digits`` в записи — снимок на момент извлечения."
        ),
        "lines_total": total,
        "lines_wrong_or_missing_record_kind": bad_kind,
        "donor_inn_digits_mismatch_vs_reconstructed": donor_inn_mismatch,
        "supplement_aeo_OGRN_missing_with_upper_donor": sup_ogrn_missing_with_donor,
        "supplement_aeo_OGRN_missing_without_upper_donor": sup_ogrn_missing_no_donor,
        "supplement_aeo_HeadEduOrgId_nonempty": sup_head_nonempty,
        "donor_INN_source_hint": {
            "root_aeo_had_digit_INN": inn_root_vs_eduorg_only["from_root_aeo_inn"],
            "only_EduOrgINN_had_digits": inn_root_vs_eduorg_only["from_eduorg_inn_only"],
            "description_ru": "Подсказка по сохранённым полям: у скольких записей в slim-корне был цифровой INN vs только EduOrgINN (на момент извлечения).",
        },
        "supplement_IsForBranch_histogram": dict(sorted(is_for_branch.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Строк: {total}\n"
        f"Неверный record_kind: {bad_kind}\n"
        f"OGRN у supplement пуст, донор OGRN «сверху» есть: {sup_ogrn_missing_with_donor}\n"
        f"Отчёт: {args.output.resolve()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
