"""Генерирует specs/prisma/schema.prisma из specs/sql/mapping.json и specs/prisma/mapping.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SQL_MAPPING_DEFAULT = ROOT / "specs" / "sql" / "mapping.json"
PRISMA_CONFIG_DEFAULT = ROOT / "specs" / "prisma" / "mapping.json"


def _on_delete_prisma(sql_on_delete: str) -> str:
    k = sql_on_delete.strip().upper().replace(" ", "")
    return {
        "CASCADE": "Cascade",
        "NOACTION": "NoAction",
        "RESTRICT": "Restrict",
        "SETNULL": "SetNull",
    }.get(k, "NoAction")


def _sql_type_to_prisma(sql_type: str, nullable: bool | None, *, in_primary_key: bool) -> str:
    opt = "?" if (nullable is not False and not in_primary_key) else ""
    if sql_type == "BOOLEAN":
        return f"Boolean{opt}"
    if sql_type == "DATE":
        return f"String{opt} @db.Text"
    return f"String{opt} @db.Text"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_schema(sql_mapping: dict[str, Any], prisma_cfg: dict[str, Any]) -> str:
    model_names: dict[str, str] = dict(prisma_cfg.get("model_names") or {})
    rel_names: dict[str, str] = dict(prisma_cfg.get("relation_names") or {})
    ds = prisma_cfg.get("generator", {}).get("datasource", {})
    provider = ds.get("provider", "postgresql")
    url_env = ds.get("url_env", "DATABASE_URL")

    lines: list[str] = [
        "// Сгенерировано generate_prisma_schema.py — не править вручную.",
        "// Источник: specs/sql/mapping.json + specs/prisma/mapping.json",
        "",
        'generator client {',
        '  provider = "prisma-client-js"',
        "}",
        "",
        "datasource db {",
        f'  provider = "{provider}"',
        f"  url      = env(\"{url_env}\")",
        "}",
        "",
    ]

    tables: list[dict[str, Any]] = list(sql_mapping["tables"])

    def model_for_table(tname: str) -> str:
        return model_names.get(tname, _default_model_name(tname))

    # FK -> (child_table, parent_table, child_cols, parent_cols, on_delete, relation_name)
    fk_edges: list[tuple[str, str, list[str], list[str], str, str]] = []
    for t in tables:
        ctab = t["name"]
        for fk in t.get("foreign_keys", []):
            ptab = fk["references_table"]
            cc = list(fk["columns"])
            pc = list(fk["references_columns"])
            od = fk.get("on_delete", "NO ACTION")
            rname = ""
            if ctab == "actual_education_organizations":
                if ptab == "certificates":
                    rname = rel_names.get(
                        "actual_education_organizations_to_certificate",
                        "AeoViaCertificate",
                    )
                elif ptab == "supplements":
                    rname = rel_names.get(
                        "actual_education_organizations_to_supplement",
                        "AeoViaSupplement",
                    )
            fk_edges.append((ctab, ptab, cc, pc, od, rname))

    # parent -> list of (child_model, child_table, fk_cols_child, fk_cols_parent, on_delete, rel_name)
    children: dict[str, list[tuple[str, str, list[str], list[str], str, str]]] = {}
    for ctab, ptab, cc, pc, od, rname in fk_edges:
        children.setdefault(ptab, []).append((ctab, ctab, cc, pc, od, rname))

    for t in tables:
        tname = t["name"]
        model = model_for_table(tname)
        desc = t.get("description_ru", "")
        pk = list(t["primary_key"])
        cols = list(t["columns"])
        pk_set = set(pk)

        lines.append(f"/// {desc}")
        lines.append(f"model {model} {{")

        col_names = {c["name"] for c in cols}
        for c in cols:
            cname = c["name"]
            nullable = c.get("nullable", True)
            st = c["sql_type"]
            lines.append(
                f"  {cname} {_sql_type_to_prisma(st, nullable, in_primary_key=cname in pk_set)}"
            )

        # Relations (many-to-one from this child table)
        for ctab, ptab, cc, pc, od, rname in fk_edges:
            if ctab != tname:
                continue
            parent_model = model_for_table(ptab)
            fname = _parent_field_name(ptab, tname)
            opt = "?" if _fk_optional(ctab, cc, col_names) else ""
            od_p = _on_delete_prisma(od)
            fields = ", ".join(cc)
            refs = ", ".join(pc)
            if rname:
                lines.append(
                    f"  {fname} {parent_model}{opt} @relation("
                    f'"{rname}", fields: [{fields}], references: [{refs}], onDelete: {od_p})'
                )
            else:
                lines.append(
                    f"  {fname} {parent_model}{opt} @relation("
                    f"fields: [{fields}], references: [{refs}], onDelete: {od_p})"
                )

        # Reverse one-to-many on parent
        for ch_tab, _ch, cc, pc, od, rname in children.get(tname, []):
            ch_model = model_for_table(ch_tab)
            arr_name = _child_array_field_name(ch_tab)
            if rname:
                lines.append(
                    f"  {arr_name} {ch_model}[] @relation(\"{rname}\")"
                )
            else:
                lines.append(f"  {arr_name} {ch_model}[]")

        pkf = ", ".join(pk)
        lines.append(f"  @@id([{pkf}])")
        lines.append(f'  @@map("{tname}")')
        lines.append("}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _default_model_name(table: str) -> str:
    if table.endswith("ies"):
        return table[:-3] + "y"
    if table.endswith("s"):
        return table[:-1].replace("_", " ").title().replace(" ", "")
    return table.title()


def _parent_field_name(parent_table: str, child_table: str) -> str:
    if parent_table == "certificates":
        return "certificate"
    if parent_table == "supplements":
        return "supplement"
    return parent_table.rstrip("s")


def _child_array_field_name(child_table: str) -> str:
    return {
        "supplements": "supplements",
        "decisions": "decisions",
        "educational_programs": "educational_programs",
        "actual_education_organizations": "actual_education_organizations",
    }.get(child_table, child_table)


def _fk_optional(child_table: str, fk_cols: list[str], col_names: set[str]) -> bool:
    if child_table != "actual_education_organizations":
        return False
    if fk_cols == ["source_file", "certificate_id", "supplement_id"]:
        return "supplement_id" in col_names
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sql-mapping",
        type=Path,
        default=SQL_MAPPING_DEFAULT,
        help="Путь к specs/sql/mapping.json",
    )
    p.add_argument(
        "--prisma-config",
        type=Path,
        default=PRISMA_CONFIG_DEFAULT,
        help="Путь к specs/prisma/mapping.json",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Куда записать schema.prisma (по умолчанию из specs/prisma/mapping.json)",
    )
    args = p.parse_args(argv)

    if not args.sql_mapping.is_file():
        print(f"Не найден файл: {args.sql_mapping}", file=sys.stderr)
        return 2
    if not args.prisma_config.is_file():
        print(f"Не найден файл: {args.prisma_config}", file=sys.stderr)
        return 2

    sql_mapping = _load_json(args.sql_mapping)
    prisma_cfg = _load_json(args.prisma_config)
    out = args.output
    if out is None:
        rel = prisma_cfg.get("generator", {}).get("schema_output", "specs/prisma/schema.prisma")
        out = ROOT / rel
    text = build_schema(sql_mapping, prisma_cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Записано: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
