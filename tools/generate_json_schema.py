"""Генерирует JSON Schema (draft 2020-12) для одной строки JSONL (объект сертификата + _source_file)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import convert

OUT_DEFAULT = REPO_ROOT / "specs" / "json-schema" / "certificate-line.schema.json"

# Скаляры на корне объекта (как в XML Certificate, без вложенных коллекций / AEO)
ROOT_SCALAR_TAGS: tuple[str, ...] = (
    "Id",
    "IsFederal",
    "StatusName",
    "TypeName",
    "RegionName",
    "RegionCode",
    "FederalDistrictName",
    "FederalDistrictShortName",
    "RegNumber",
    "SerialNumber",
    "FormNumber",
    "IssueDate",
    "EndDate",
    "ControlOrgan",
    "PostAddress",
    "EduOrgFullName",
    "EduOrgShortName",
    "EduOrgINN",
    "EduOrgKPP",
    "EduOrgOGRN",
    "IndividualEntrepreneurLastName",
    "IndividualEntrepreneurFirstName",
    "IndividualEntrepreneurMiddleName",
    "IndividualEntrepreneurAddress",
    "IndividualEntrepreneurEGRIP",
    "IndividualEntrepreneurINN",
)

SUPPLEMENT_JSON_KEYS: tuple[str, ...] = (
    "Id",
    "StatusName",
    "StatusCode",
    "Number",
    "SerialNumber",
    "FormNumber",
    "IssueDate",
    "IsForBranch",
    "Note",
    "EduOrgFullName",
    "EduOrgShortName",
    "EduOrgAddress",
    "EduOrgKPP",
)

DECISION_JSON_KEYS: tuple[str, ...] = (
    "Id",
    "DecisionTypeName",
    "OrderDocumentNumber",
    "OrderDocumentKind",
    "DecisionDate",
)

PROGRAM_JSON_KEYS: tuple[str, ...] = (
    "Id",
    "TypeName",
    "EduLevelName",
    "ProgrammName",
    "ProgrammCode",
    "UGSName",
    "UGSCode",
    "EduNormativePeriod",
    "Qualification",
    "IsAccredited",
    "IsCanceled",
    "IsSuspended",
)

AEO_JSON_KEYS: tuple[str, ...] = (
    "Id",
    "FullName",
    "ShortName",
    "HeadEduOrgId",
    "IsBranch",
    "PostAddress",
    "Phone",
    "Fax",
    "Email",
    "WebSite",
    "OGRN",
    "INN",
    "KPP",
    "HeadPost",
    "HeadName",
    "FormName",
    "KindName",
    "TypeName",
    "RegionName",
    "FederalDistrictShortName",
    "FederalDistrictName",
)


def _scalar_schema(tag: str) -> dict[str, Any]:
    if tag in convert.BOOL_FIELDS:
        return {"type": ["boolean", "null"]}
    if tag in convert.DATE_FIELDS:
        return {
            "type": ["string", "null"],
            "description": "Обычно YYYY-MM-DD; при сбое парсинга — произвольная строка (см. convert.py).",
        }
    return {"type": ["string", "null"]}


def _object_props(keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: _scalar_schema(k) for k in keys}


def build_schema_dict() -> dict[str, Any]:
    props: dict[str, Any] = {
        "_source_file": {
            "type": "string",
            "description": "Имя исходного XML (добавляет convert.py).",
        },
    }
    for tag in ROOT_SCALAR_TAGS:
        props[tag] = _scalar_schema(tag)

    props["ActualEducationOrganization"] = {
        "type": ["object", "null"],
        "additionalProperties": True,
        "properties": _object_props(AEO_JSON_KEYS),
    }
    props["Supplements"] = {
        "type": "array",
        "description": "Список объектов приложений (без обёртки ключа Supplement).",
        "items": {"$ref": "#/$defs/Supplement"},
    }
    props["Decisions"] = {
        "type": "array",
        "description": (
            "Решения (распорядительные документы), как в XML. Элемент с Id: null допустим; "
            "реляционный импорт по specs/sql/mapping.json не создаёт для него строку в "
            "таблице decisions, сертификат и остальные сущности из строки JSONL импортируются."
        ),
        "items": {"$ref": "#/$defs/Decision"},
    }

    supplement_props = _object_props(SUPPLEMENT_JSON_KEYS)
    supplement_props["EducationalPrograms"] = {
        "type": "array",
        "items": {"$ref": "#/$defs/EducationalProgram"},
    }
    supplement_props["ActualEducationOrganization"] = {
        "type": ["object", "null"],
        "additionalProperties": True,
        "properties": _object_props(AEO_JSON_KEYS),
    }

    decision_props = _object_props(DECISION_JSON_KEYS)
    decision_id_schema = dict(decision_props["Id"])
    decision_id_schema["description"] = (
        "Идентификатор распорядительного документа в выгрузке. null, если в XML пустой тег — "
        "в JSONL объект решения может содержать другие поля; реляционный импорт не добавляет "
        "строку в таблицу decisions без непустого Id, сертификат не отбрасывается."
    )
    decision_props["Id"] = decision_id_schema

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/kscht/accredreestr_converter/specs/json-schema/certificate-line.schema.json",
        "title": "Строка JSONL: свидетельство (Certificate)",
        "description": (
            "Один объект JSON из выхода convert.py: поля сертификата, "
            "массивы Supplements/Decisions, опциональный ActualEducationOrganization. "
            "Неизвестные теги из XML могут появиться как дополнительные ключи. "
            "Пустой Id у элемента Decisions означает отсутствие идентификатора документа в выгрузке, "
            "не «отсутствие организации»; см. docs/sql_convert.md."
        ),
        "type": "object",
        "required": ["_source_file"],
        "additionalProperties": True,
        "properties": props,
        "$defs": {
            "Supplement": {
                "type": "object",
                "additionalProperties": True,
                "properties": supplement_props,
            },
            "Decision": {
                "type": "object",
                "additionalProperties": True,
                "properties": decision_props,
            },
            "EducationalProgram": {
                "type": "object",
                "additionalProperties": True,
                "properties": _object_props(PROGRAM_JSON_KEYS),
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Сгенерировать JSON Schema для строки JSONL.")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=OUT_DEFAULT,
        help="Путь к .schema.json",
    )
    args = p.parse_args(argv)
    data = build_schema_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Записано: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
