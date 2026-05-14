#!/usr/bin/env python3
"""Сборка Mermaid erDiagram для GitHub из specs/sql/mapping.json (полные колонки и FK)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MAPPING = _ROOT / "specs" / "sql" / "mapping.json"
_DEFAULT_OUT = _ROOT / "docs" / "diagrams" / "sql_schema_er.md"

_SQL_TO_MERMAID: dict[str, str] = {
    "TEXT": "text",
    "INTEGER": "int",
    "BOOLEAN": "boolean",
    "DATE": "date",
}

# Подписи рёбер (родитель → ребёнок); при новых таблицах — запасной вариант в коде ниже.
_EDGE_LABELS: dict[tuple[str, str], str] = {
    ("certificates", "supplements"): "Supplements[]",
    ("certificates", "decisions"): "Decisions[]",
    ("certificates", "actual_education_organizations"): "ActualEducationOrganization (корень)",
    ("supplements", "educational_programs"): "EducationalPrograms[]",
    ("supplements", "actual_education_organizations"): "ActualEducationOrganization (в приложении)",
}


def _mermaid_scalar_type(sql_type: str) -> str:
    return _SQL_TO_MERMAID.get(sql_type, "text")


def _fk_column_sets(table: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for fk in table.get("foreign_keys", []):
        for c in fk.get("columns", []):
            out.add(c)
    return out


def _emit_entity(table: dict[str, Any]) -> list[str]:
    tname = table["name"]
    pk_set = set(table.get("primary_key", []))
    fk_cols = _fk_column_sets(table)
    lines = [f"  {tname} {{"]

    for col in table.get("columns", []):
        cname = col["name"]
        mt = _mermaid_scalar_type(str(col.get("sql_type", "TEXT")))
        tags: list[str] = []
        if cname in pk_set:
            tags.append("PK")
        if cname in fk_cols:
            tags.append("FK")
        # GitHub Mermaid: несколько модификаторов только через запятую (не «PK FK»).
        suffix = (" " + ", ".join(tags)) if tags else ""
        lines.append(f"    {mt} {cname}{suffix}")

    lines.append("  }")
    return lines


def _emit_edges(mapping: dict[str, Any]) -> list[str]:
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for t in mapping.get("tables", []):
        child = t["name"]
        for fk in t.get("foreign_keys", []):
            parent = fk["references_table"]
            key = (parent, child)
            if key in seen:
                continue
            seen.add(key)
            label = _EDGE_LABELS.get(key) or f"FK {parent}"
            safe = label.replace('"', "'")
            lines.append(f'  {parent} ||--o{{ {child} : "{safe}"')
    return lines


def build_markdown(mapping: dict[str, Any], mapping_rel_path: str = "../../specs/sql/mapping.json") -> str:
    body_lines = ["erDiagram", *_emit_edges(mapping), ""]
    for t in mapping.get("tables", []):
        body_lines.extend(_emit_entity(t))
        body_lines.append("")

    mermaid_block = "\n".join(body_lines).rstrip() + "\n"

    return f"""# Реляционная схема (SQL mapping)

Файл **генерируется** из [`{mapping_rel_path}`]({mapping_rel_path}) скриптом `tools/generate_sql_er_diagram.py` (все колонки и связи по `foreign_keys`, как в DDL/`sql_convert`). На GitHub блок **`mermaid`** отображается штатно.

```bash
python tools/generate_sql_er_diagram.py
```

## Таблицы и связи

```mermaid
{mermaid_block}```

## Заметки (политика данных, не видны на ER)

- **`decisions`**: элементы `Decisions[]` с пустым `Id` в JSONL **не вставляются**; сертификат в `certificates` остаётся.
- **`educational_programs`**: в PK входит **`program_slot`** (индекс в массиве), т.к. **`program_id`** из реестра может повторяться.
- **`actual_education_organizations`**: поле **`ae_scope`** (`certificate` | `supplement`); FK на `supplements` относится к строкам с областью приложения (см. [`sql_convert.md`](../sql_convert.md)).
"""


def main() -> int:
    p = argparse.ArgumentParser(
        description="Собрать docs/diagrams/sql_schema_er.md (Mermaid erDiagram) из specs/sql/mapping.json.",
    )
    p.add_argument(
        "--mapping",
        type=Path,
        default=_DEFAULT_MAPPING,
        help=f"Путь к mapping.json (по умолчанию {_DEFAULT_MAPPING})",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Выходной Markdown (по умолчанию {_DEFAULT_OUT})",
    )
    args = p.parse_args()
    if not args.mapping.is_file():
        print(f"Нет файла: {args.mapping}", file=sys.stderr)
        return 2

    mapping: dict[str, Any] = json.loads(args.mapping.read_text(encoding="utf-8"))
    try:
        md = build_markdown(mapping)
    except (KeyError, TypeError) as e:
        print(f"Некорректный mapping: {e}", file=sys.stderr)
        return 2

    out: Path = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8", newline="\n")
    print(f"Записано: {out.resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
