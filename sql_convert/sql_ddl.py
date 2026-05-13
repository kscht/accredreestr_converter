"""DDL из specs/sql/mapping.json для SQLite, PostgreSQL, MySQL (InnoDB) и DuckDB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

Dialect = Literal["sqlite", "postgres", "mysql", "duckdb"]


def quote_ident(name: str, dialect: Dialect) -> str:
    if dialect == "mysql":
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def load_mapping(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parents[1] / "specs" / "sql" / "mapping.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _physical_type(sql_type: str, dialect: Dialect) -> str:
    if sql_type == "BOOLEAN":
        if dialect == "sqlite":
            return "INTEGER"
        if dialect == "mysql":
            return "TINYINT(1)"
        return "BOOLEAN"  # postgres, duckdb
    if sql_type == "DATE":
        return "TEXT"
    if sql_type == "INTEGER":
        if dialect == "mysql":
            return "INT"
        return "INTEGER"
    if sql_type == "TEXT":
        return "TEXT"
    return "TEXT"


def build_drop_statements(mapping: dict[str, Any], dialect: Dialect) -> list[str]:
    tables = list(mapping["tables"])
    tables.reverse()
    out: list[str] = []
    for t in tables:
        name = t["name"]
        if dialect in ("postgres", "duckdb"):
            out.append(f"DROP TABLE IF EXISTS {quote_ident(name, dialect)} CASCADE;")
        else:
            out.append(f"DROP TABLE IF EXISTS {quote_ident(name, dialect)};")
    return out


def build_create_statements(mapping: dict[str, Any], dialect: Dialect) -> list[str]:
    stmts: list[str] = []
    for t in mapping["tables"]:
        tname = t["name"]
        col_lines: list[str] = []
        for c in t["columns"]:
            cname = c["name"]
            phys = _physical_type(c["sql_type"], dialect)
            null_sql = " NOT NULL" if c.get("nullable") is False else ""
            col_lines.append(f"{quote_ident(cname, dialect)} {phys}{null_sql}")
        pk = ", ".join(quote_ident(x, dialect) for x in t["primary_key"])
        col_lines.append(f"PRIMARY KEY ({pk})")
        for fk in t.get("foreign_keys", []):
            cols = ", ".join(quote_ident(x, dialect) for x in fk["columns"])
            ref_t = fk["references_table"]
            ref_c = ", ".join(quote_ident(x, dialect) for x in fk["references_columns"])
            od = fk.get("on_delete", "NO ACTION")
            if dialect == "duckdb":
                # DuckDB: ON DELETE CASCADE / SET NULL / SET DEFAULT у FK не поддерживаются
                od = "NO ACTION"
            col_lines.append(
                f"FOREIGN KEY ({cols}) REFERENCES {quote_ident(ref_t, dialect)} ({ref_c}) ON DELETE {od}"
            )
        body = ",\n    ".join(col_lines)
        tail = ""
        if dialect == "mysql":
            tail = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        stmts.append(f"CREATE TABLE {quote_ident(tname, dialect)} (\n    {body}\n){tail};")
    return stmts
