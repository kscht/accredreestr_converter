#!/usr/bin/env python3
"""Аудит JSONL: филиалы по правилу 1 — ``ActualEducationOrganization.Id`` в supplement ≠ Id корневой AEO.

Логика совпадает с веткой «филиал по Id» в ``convert.py`` (``_aeo_supplement_uid_differs_from_root``);
позже те же функции можно вызывать при записи ``derived`` в конвертере.

По умолчанию — JSON-сводка с числами и примерами (``--limit``). Опционально:

- ``--branch-jsonl`` / ``-b`` [PATH] — по одной компактной строке на каждое срабатывание правила 1
  (``branch_supplement_diff_aeo_id_v1``); без PATH — ``examples/branch_supplements_diff_aeo_id.jsonl``
  (крупный файл — в ``.gitignore`` на полном снимке);
- ``-p`` / ``--problem-jsonl`` [PATH] — полные строки сертификатов, где есть хотя бы один такой supplement
  (по умолчанию ``examples/certificate_lines_with_branch_supplements.jsonl``, тоже в ``.gitignore`` при большом объёме).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from convert import (  # noqa: E402
    _aeo_supplement_uid_differs_from_root,
    _aeo_supplement_uid_matches_root,
    _aeo_uid_token,
)

_DEFAULT_OUT = _ROOT / "examples" / "dataset_branches_audit.json"
_DEFAULT_BRANCH_JSONL = _ROOT / "examples" / "branch_supplements_diff_aeo_id.jsonl"
_DEFAULT_PROBLEM_JSONL = _ROOT / "examples" / "certificate_lines_with_branch_supplements.jsonl"

RECORD_KIND = "branch_supplement_diff_aeo_id_v1"
RULE_ID = "diff_aeo_id"


def is_branch_supplement_by_diff_aeo_id(root_aeo: Any, sup_aeo: Any) -> bool:
    """Правило 1: оба ``Id`` непусты и различаются (без учёта регистра UUID)."""
    return _aeo_supplement_uid_differs_from_root(root_aeo, sup_aeo)


def is_same_entity_supplement_by_aeo_id(root_aeo: Any, sup_aeo: Any) -> bool:
    """Тот же субъект AEO, что на корне (``_aeo_supplement_uid_matches_root``)."""
    return _aeo_supplement_uid_matches_root(root_aeo, sup_aeo)


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


def build_branch_hit_record(
    row: dict[str, Any],
    *,
    supplement_index: int,
    sup: dict[str, Any],
    root_aeo: dict[str, Any],
    sup_aeo: dict[str, Any],
) -> dict[str, Any]:
    """Компактная запись одного supplement, попавшего под правило 1 (для JSONL и будущего ``derived``)."""
    return {
        "record_kind": RECORD_KIND,
        "rule_id": RULE_ID,
        "certificate_id": row.get("Id"),
        "supplement_index": supplement_index,
        "root_aeo_id": root_aeo.get("Id"),
        "supplement_aeo_id": sup_aeo.get("Id"),
        "EduOrgINN": row.get("EduOrgINN"),
        "EduOrgOGRN": row.get("EduOrgOGRN"),
        "certificate_EduOrgFullName": row.get("EduOrgFullName"),
        "certificate_EduOrgShortName": row.get("EduOrgShortName"),
        "root_ActualEducationOrganization": _slim_aeo(root_aeo),
        "supplement_ActualEducationOrganization": _slim_aeo(sup_aeo),
        "supplement_meta": _pick_supplement_meta(sup),
    }


def iter_branch_supplements(row: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """По сертификату: ``(supplement_index, supplement, root_aeo, supplement_aeo)`` для правила 1."""
    root_aeo = row.get("ActualEducationOrganization")
    if not isinstance(root_aeo, dict):
        return
    for idx, sup in enumerate(row.get("Supplements") or []):
        if not isinstance(sup, dict):
            continue
        sup_aeo = sup.get("ActualEducationOrganization")
        if not isinstance(sup_aeo, dict):
            continue
        if is_branch_supplement_by_diff_aeo_id(root_aeo, sup_aeo):
            yield idx, sup, root_aeo, sup_aeo


def _path_for_report(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(_ROOT))
    except ValueError:
        return str(path.resolve())


def audit_certificate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Счётчики по одной строке JSONL (для тестов и сводки)."""
    root_aeo = row.get("ActualEducationOrganization")
    has_root = isinstance(root_aeo, dict)
    sup_aeo_total = 0
    same_id = 0
    branch_hits = 0
    incomparable = 0
    for sup in row.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        sup_aeo = sup.get("ActualEducationOrganization")
        if not isinstance(sup_aeo, dict):
            continue
        sup_aeo_total += 1
        if not has_root:
            incomparable += 1
            continue
        rid = _aeo_uid_token(root_aeo.get("Id"))
        sid = _aeo_uid_token(sup_aeo.get("Id"))
        if not rid or not sid:
            incomparable += 1
        elif rid == sid:
            same_id += 1
        else:
            branch_hits += 1
    return {
        "has_root_aeo": has_root,
        "supplement_aeo_cards": sup_aeo_total,
        "same_aeo_id_as_root": same_id,
        "branch_by_diff_aeo_id": branch_hits,
        "incomparable_aeo_id": incomparable,
        "has_any_branch": branch_hits > 0,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Аудит JSONL: филиалы (правило 1) — supplement AEO.Id ≠ корневой AEO.Id."
        ),
    )
    p.add_argument(
        "jsonl",
        type=Path,
        nargs="?",
        default=_ROOT / "out" / "data-20260403-structure-20160713.jsonl",
        help=(
            "Входной .jsonl (по умолчанию out/data-20260403-structure-20160713.jsonl, "
            "если файл есть)"
        ),
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"JSON-отчёт (по умолчанию {_DEFAULT_OUT})",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=200,
        metavar="N",
        help="Не больше N примеров в examples_branch_hits (0 = только счётчики)",
    )
    p.add_argument(
        "-b",
        "--branch-jsonl",
        nargs="?",
        const=_DEFAULT_BRANCH_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "Компактная строка на каждый supplement с правилом 1. "
            f"Флаг без PATH — {_DEFAULT_BRANCH_JSONL.relative_to(_ROOT)}"
        ),
    )
    p.add_argument(
        "-p",
        "--problem-jsonl",
        nargs="?",
        const=_DEFAULT_PROBLEM_JSONL,
        default=None,
        type=Path,
        metavar="PATH",
        help=(
            "Полные строки сертификатов с хотя бы одним филиалом по правилу 1. "
            f"Флаг без PATH — {_DEFAULT_PROBLEM_JSONL.relative_to(_ROOT)}"
        ),
    )
    args = p.parse_args()
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

    total = 0
    with_root_aeo = 0
    with_supplements = 0
    with_any_branch = 0
    supplement_aeo_cards = 0
    same_aeo_id = 0
    branch_hits = 0
    incomparable = 0
    is_for_branch_on_branch: dict[str, int] = {}
    examples: list[dict[str, Any]] = []

    branch_fh = (
        args.branch_jsonl.open("w", encoding="utf-8", newline="\n")
        if args.branch_jsonl
        else None
    )
    problem_fh = (
        args.problem_jsonl.open("w", encoding="utf-8", newline="\n")
        if args.problem_jsonl
        else None
    )

    with args.jsonl.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            s = raw_line.strip()
            if not s:
                continue
            total += 1
            try:
                row = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue

            per = audit_certificate_row(row)
            if per["has_root_aeo"]:
                with_root_aeo += 1
            if per["supplement_aeo_cards"]:
                with_supplements += 1
            supplement_aeo_cards += per["supplement_aeo_cards"]
            same_aeo_id += per["same_aeo_id_as_root"]
            branch_hits += per["branch_by_diff_aeo_id"]
            incomparable += per["incomparable_aeo_id"]

            cert_has_branch = False
            for idx, sup, root_aeo, sup_aeo in iter_branch_supplements(row):
                cert_has_branch = True
                ifb = sup.get("IsForBranch")
                key = (
                    "true"
                    if ifb is True
                    else "false"
                    if ifb is False
                    else "null"
                    if ifb is None
                    else str(ifb)
                )
                is_for_branch_on_branch[key] = is_for_branch_on_branch.get(key, 0) + 1
                rec = build_branch_hit_record(
                    row,
                    supplement_index=idx,
                    sup=sup,
                    root_aeo=root_aeo,
                    sup_aeo=sup_aeo,
                )
                if branch_fh is not None:
                    branch_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if len(examples) < args.limit:
                    examples.append(rec)

            if cert_has_branch:
                with_any_branch += 1
                if problem_fh is not None:
                    problem_fh.write(raw_line if raw_line.endswith("\n") else raw_line + "\n")

    if branch_fh is not None:
        branch_fh.close()
    if problem_fh is not None:
        problem_fh.close()

    out = {
        "source_jsonl": src_rel,
        "description_ru": (
            "Филиалы по правилу 1: у supplement ActualEducationOrganization.Id и у корневой AEO "
            "оба Id непусты и различаются (сравнение без учёта регистра). "
            "Совпадает с _aeo_supplement_uid_differs_from_root в convert.py."
        ),
        "rule_id": RULE_ID,
        "certificate_lines_total": total,
        "certificates_with_root_ActualEducationOrganization": with_root_aeo,
        "certificates_with_any_supplement_aeo": with_supplements,
        "certificates_with_any_branch_by_rule_1": with_any_branch,
        "supplement_aeo_cards_total": supplement_aeo_cards,
        "supplement_aeo_same_Id_as_root": same_aeo_id,
        "supplement_aeo_branch_by_diff_Id_rule_1": branch_hits,
        "supplement_aeo_incomparable_Id": incomparable,
        "branch_hits_IsForBranch_histogram": dict(sorted(is_for_branch_on_branch.items())),
        "outputs": {
            "branch_jsonl": _path_for_report(args.branch_jsonl),
            "problem_jsonl": _path_for_report(args.problem_jsonl),
        },
        "examples_branch_hits": examples,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Строк сертификатов: {total}\n"
        f"С корневой AEO: {with_root_aeo}\n"
        f"Сертификатов с ≥1 филиалом (правило 1): {with_any_branch}\n"
        f"Supplement AEO всего: {supplement_aeo_cards}\n"
        f"  тот же Id, что корень: {same_aeo_id}\n"
        f"  филиал (Id ≠ корня): {branch_hits}\n"
        f"  Id несравним (пустой): {incomparable}\n"
        f"Отчёт: {args.output.resolve()}"
        + (
            f"\nКомпактные филиалы: {args.branch_jsonl.resolve()}"
            if args.branch_jsonl
            else ""
        )
        + (
            f"\nПолные сертификаты: {args.problem_jsonl.resolve()}"
            if args.problem_jsonl
            else ""
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
