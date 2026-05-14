"""Импорт JSONL в SQLite, PostgreSQL или MySQL по specs/sql/mapping.json; опционально дамп .sql."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

from .sql_ddl import Dialect, build_create_statements, build_drop_statements, load_mapping, quote_ident

ExecuteFn = Callable[[str, tuple[Any, ...]], None]


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    """Разбор DSN вида mysql://user:pass@host:3306/dbname (или mariadb://)."""
    from urllib.parse import unquote, urlparse

    s = dsn.strip()
    if "://" not in s:
        s = "mysql://" + s
    p = urlparse(s)
    if p.scheme not in ("mysql", "mariadb"):
        raise ValueError(
            f"Ожидалась схема mysql:// или mariadb:// в --mysql, получено: {p.scheme!r}"
        )
    database = (p.path or "").lstrip("/")
    if not database:
        raise ValueError("В DSN MySQL должен быть указан путь к базе, напр. mysql://user@host/dbname")
    user = unquote(p.username) if p.username is not None else "root"
    password = unquote(p.password) if p.password is not None else ""
    host = p.hostname or "localhost"
    port = p.port or 3306
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
    }


def _adapt_scalar(val: Any, sql_type: str, dialect: Dialect) -> Any:
    if val is None:
        return None
    if sql_type == "BOOLEAN":
        if isinstance(val, bool):
            b = val
        elif isinstance(val, (int, float)) and val in (0, 1):
            b = bool(int(val))
        elif isinstance(val, str) and val.strip() in {"0", "1"}:
            b = val.strip() == "1"
        else:
            return None
        if dialect == "sqlite" or dialect == "mysql":
            return 1 if b else 0
        return b
    if sql_type == "DATE":
        return val if isinstance(val, str) else str(val)
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return val


def _table_columns(mapping: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    for t in mapping["tables"]:
        if t["name"] == table_name:
            return list(t["columns"])
    raise KeyError(table_name)


def _insert_sql(dialect: Dialect, table: str, colnames: list[str]) -> str:
    q = ",".join(quote_ident(c, dialect) for c in colnames)
    n = len(colnames)
    ph = ",".join(["?"] * n) if dialect == "sqlite" else ",".join(["%s"] * n)
    return f"INSERT INTO {quote_ident(table, dialect)} ({q}) VALUES ({ph})"


def _row_certificate(obj: dict[str, Any], cols: list[dict[str, Any]], dialect: Dialect) -> tuple[Any, ...]:
    vals: list[Any] = []
    for c in cols:
        fj = c.get("from_json")
        st = c["sql_type"]
        if fj:
            vals.append(_adapt_scalar(obj.get(fj), st, dialect))
        else:
            vals.append(None)
    return tuple(vals)


def _row_supplement(
    obj: dict[str, Any], sup: dict[str, Any], cols: list[dict[str, Any]], dialect: Dialect
) -> tuple[Any, ...]:
    vals: list[Any] = []
    for c in cols:
        n = c["name"]
        fj = c.get("from_json")
        st = c["sql_type"]
        if n == "certificate_id":
            vals.append(_adapt_scalar(obj.get("Id"), "TEXT", dialect))
        elif n == "supplement_id" and fj == "Id":
            vals.append(_adapt_scalar(sup.get("Id"), "TEXT", dialect))
        elif fj:
            vals.append(_adapt_scalar(sup.get(fj), st, dialect))
        else:
            vals.append(None)
    return tuple(vals)


def _row_decision(
    obj: dict[str, Any], dec: dict[str, Any], cols: list[dict[str, Any]], dialect: Dialect
) -> tuple[Any, ...]:
    vals: list[Any] = []
    for c in cols:
        n = c["name"]
        fj = c.get("from_json")
        st = c["sql_type"]
        if n == "certificate_id":
            vals.append(_adapt_scalar(obj.get("Id"), "TEXT", dialect))
        elif n == "decision_id" and fj == "Id":
            vals.append(_adapt_scalar(dec.get("Id"), "TEXT", dialect))
        elif fj:
            vals.append(_adapt_scalar(dec.get(fj), st, dialect))
        else:
            vals.append(None)
    return tuple(vals)


def _row_program(
    obj: dict[str, Any],
    sup: dict[str, Any],
    prog: dict[str, Any],
    cols: list[dict[str, Any]],
    dialect: Dialect,
    program_slot: int,
) -> tuple[Any, ...]:
    vals: list[Any] = []
    for c in cols:
        n = c["name"]
        fj = c.get("from_json")
        st = c["sql_type"]
        if n == "certificate_id":
            vals.append(_adapt_scalar(obj.get("Id"), "TEXT", dialect))
        elif n == "program_slot":
            vals.append(int(program_slot))
        elif n == "supplement_id" and fj == "Id":
            vals.append(_adapt_scalar(sup.get("Id"), "TEXT", dialect))
        elif n == "program_id" and fj == "Id":
            vals.append(_adapt_scalar(prog.get("Id"), "TEXT", dialect))
        elif fj:
            vals.append(_adapt_scalar(prog.get(fj), st, dialect))
        else:
            vals.append(None)
    return tuple(vals)


def _row_aeo(
    certificate_id: str,
    ae_scope: str,
    supplement_id: str | None,
    aeo: dict[str, Any],
    cols: list[dict[str, Any]],
    dialect: Dialect,
) -> tuple[Any, ...]:
    vals: list[Any] = []
    for c in cols:
        n = c["name"]
        fj = c.get("from_json")
        st = c["sql_type"]
        if n == "certificate_id":
            vals.append(_adapt_scalar(certificate_id, "TEXT", dialect))
        elif n == "ae_scope":
            vals.append(ae_scope)
        elif n == "supplement_id":
            vals.append(supplement_id)
        elif n == "aeo_id" and fj == "Id":
            vals.append(_adapt_scalar(aeo.get("Id"), "TEXT", dialect))
        elif fj:
            vals.append(_adapt_scalar(aeo.get(fj), st, dialect))
        else:
            vals.append(None)
    return tuple(vals)


def iter_certificate_inserts(
    dialect: Dialect,
    mapping: dict[str, Any],
    obj: dict[str, Any],
) -> Iterator[tuple[str, list[str], tuple[Any, ...]]]:
    """Проекция одной строки JSONL в набор строк INSERT (таблица, колонки, значения).

    Элементы ``Decisions[]`` без непустого JSON ``Id`` не порождают строку в таблице
    ``decisions`` (в выгрузке нет идентификатора документа для отдельной реляционной
    записи). Свидетельство и остальные дочерние сущности по строке JSONL импортируются
    как обычно; это не отказ от организации.
    """
    cert_cols = _table_columns(mapping, "certificates")
    cnames = [c["name"] for c in cert_cols]
    yield ("certificates", cnames, _row_certificate(obj, cert_cols, dialect))

    sup_cols = _table_columns(mapping, "supplements")
    snames = [c["name"] for c in sup_cols]
    for sup in obj.get("Supplements") or []:
        if isinstance(sup, dict):
            yield ("supplements", snames, _row_supplement(obj, sup, sup_cols, dialect))

    dec_cols = _table_columns(mapping, "decisions")
    dnames = [c["name"] for c in dec_cols]
    for dec in obj.get("Decisions") or []:
        if not isinstance(dec, dict):
            continue
        raw = dec.get("Id")
        if raw is None or (isinstance(raw, str) and not str(raw).strip()):
            # Нет идентификатора документа в выгрузке — строку в decisions не создаём
            continue
        yield ("decisions", dnames, _row_decision(obj, dec, dec_cols, dialect))

    prog_cols = _table_columns(mapping, "educational_programs")
    pnames = [c["name"] for c in prog_cols]
    for sup in obj.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        for program_slot, prog in enumerate(sup.get("EducationalPrograms") or []):
            if isinstance(prog, dict):
                yield (
                    "educational_programs",
                    pnames,
                    _row_program(obj, sup, prog, prog_cols, dialect, program_slot),
                )

    aeo_cols = _table_columns(mapping, "actual_education_organizations")
    anames = [c["name"] for c in aeo_cols]
    raw_id = obj.get("Id")
    if raw_id is None:
        return
    cid = str(raw_id).strip()
    if not cid:
        return
    root_aeo = obj.get("ActualEducationOrganization")
    if isinstance(root_aeo, dict) and root_aeo.get("Id") is not None:
        yield (
            "actual_education_organizations",
            anames,
            _row_aeo(cid, "certificate", None, root_aeo, aeo_cols, dialect),
        )
    for sup in obj.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        sid = sup.get("Id")
        if sid is None:
            continue
        sid_s = str(sid)
        sub = sup.get("ActualEducationOrganization")
        if isinstance(sub, dict) and sub.get("Id") is not None:
            yield (
                "actual_education_organizations",
                anames,
                _row_aeo(cid, "supplement", sid_s, sub, aeo_cols, dialect),
            )


def _sql_literal(value: Any, dialect: Dialect) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        if dialect == "postgres":
            return "TRUE" if value else "FALSE"
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "NULL"
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def insert_statement_literals(dialect: Dialect, table: str, colnames: list[str], row: tuple[Any, ...]) -> str:
    q = ",".join(quote_ident(c, dialect) for c in colnames)
    vals = ",".join(_sql_literal(v, dialect) for v in row)
    return f"INSERT INTO {quote_ident(table, dialect)} ({q}) VALUES ({vals});"


def import_one_certificate(
    execute: ExecuteFn,
    dialect: Dialect,
    mapping: dict[str, Any],
    obj: dict[str, Any],
) -> None:
    """Вставляет одну строку JSONL (объект сертификата) во все таблицы."""
    for table, cnames, row in iter_certificate_inserts(dialect, mapping, obj):
        execute(_insert_sql(dialect, table, cnames), row)


def export_jsonl_to_sql(
    jsonl_path: Path,
    sql_out_path: Path,
    *,
    dialect: Dialect,
    mapping_path: Path | None,
    recreate: bool,
    limit: int | None,
) -> int:
    """Пишет DDL (опционально) и INSERT в один .sql без подключения к СУБД."""
    mapping = load_mapping(mapping_path)
    drops = build_drop_statements(mapping, dialect)
    creates = build_create_statements(mapping, dialect)

    sql_out_path.parent.mkdir(parents=True, exist_ok=True)
    with sql_out_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("-- Generated from JSONL by sql_convert.import_sql\n")
        if dialect == "sqlite":
            fh.write("PRAGMA foreign_keys = ON;\n")
        elif dialect == "mysql":
            fh.write("SET NAMES utf8mb4;\n")
        if recreate:
            for s in drops:
                fh.write(s + "\n")
            for s in creates:
                fh.write(s + "\n")
        fh.write("BEGIN;\n")
        processed = 0
        ok = 0
        with jsonl_path.open(encoding="utf-8") as jf:
            for line in jf:
                line = line.strip()
                if not line:
                    continue
                processed += 1
                try:
                    obj = json.loads(line)
                    for table, cnames, row in iter_certificate_inserts(dialect, mapping, obj):
                        fh.write(insert_statement_literals(dialect, table, cnames, row) + "\n")
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    logging.warning("Пропуск строки JSONL: %s", exc)
                if limit is not None and processed >= limit:
                    break
        fh.write("COMMIT;\n")
    logging.info(
        "Записано в SQL %s объектов из %s обработанных строк JSONL → %s",
        ok,
        processed,
        sql_out_path,
    )
    return 0


def import_jsonl(
    jsonl_path: Path,
    *,
    dialect: Dialect,
    sqlite_path: Path | None = None,
    postgres_conninfo: str | None = None,
    mysql_dsn: str | None = None,
    mapping_path: Path | None = None,
    recreate: bool,
    limit: int | None,
) -> int:
    mapping = load_mapping(mapping_path)
    drops = build_drop_statements(mapping, dialect)
    creates = build_create_statements(mapping, dialect)

    if dialect == "sqlite":
        import sqlite3

        if sqlite_path is None:
            raise ValueError("Для sqlite укажите --sqlite путь")
        conn: Any = sqlite3.connect(str(sqlite_path))
        conn.execute("PRAGMA foreign_keys = ON")

        def execute(sql: str, params: tuple[Any, ...]) -> None:
            conn.execute(sql, params)

    elif dialect == "postgres":
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "Для --postgres установите: pip install 'psycopg[binary]'"
            ) from exc
        if not postgres_conninfo:
            raise ValueError("Для postgres укажите --postgres DSN")
        conn = psycopg.connect(postgres_conninfo)
        conn.autocommit = False

        def execute(sql: str, params: tuple[Any, ...]) -> None:
            conn.execute(sql, params)

    elif dialect == "mysql":
        try:
            import pymysql
        except ImportError as exc:
            raise ImportError("Для --mysql установите: pip install pymysql") from exc
        if not mysql_dsn:
            raise ValueError("Для mysql укажите --mysql DSN")
        kw = _parse_mysql_dsn(mysql_dsn)
        conn = pymysql.connect(**kw, charset="utf8mb4")
        conn.autocommit = False

        def execute(sql: str, params: tuple[Any, ...]) -> None:
            with conn.cursor() as cur:
                cur.execute(sql, params)

    else:
        raise ValueError(f"Прямой импорт не поддержан для диалекта: {dialect!r}")

    try:
        if recreate:
            for s in drops:
                execute(s, ())
            for s in creates:
                execute(s, ())
            if dialect == "sqlite":
                conn.commit()
            else:
                conn.commit()

        processed = 0
        ok = 0
        with jsonl_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                processed += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    logging.warning("Пропуск строки JSONL (не JSON): %s", exc)
                    if limit is not None and processed >= limit:
                        break
                    continue
                try:
                    import_one_certificate(execute, dialect, mapping, obj)
                    conn.commit()
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    logging.warning("Пропуск строки JSONL: %s", exc)
                if limit is not None and processed >= limit:
                    break
        logging.info(
            "Обработано строк JSONL: %s (успешно импортировано объектов: %s)",
            processed,
            ok,
        )
    finally:
        conn.close()
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Импорт JSONL (выход convert.py) в SQLite, PostgreSQL, MySQL или файл .sql по specs/sql/mapping.json.",
    )
    p.add_argument("jsonl", type=Path, help="Путь к .jsonl")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--sqlite",
        type=Path,
        metavar="PATH",
        help="Файл базы SQLite (создаётся при отсутствии)",
    )
    g.add_argument(
        "--postgres",
        type=str,
        metavar="DSN",
        help='Строка подключения psycopg, напр. postgresql://user:pass@localhost:5432/dbname',
    )
    g.add_argument(
        "--mysql",
        type=str,
        metavar="DSN",
        help="mysql://user:pass@host:3306/dbname (или mariadb://…); нужен пакет pymysql",
    )
    g.add_argument(
        "--sql-out",
        type=Path,
        metavar="PATH",
        help="Записать DDL (с --recreate) и INSERT в .sql без подключения к СУБД",
    )
    p.add_argument(
        "--sql-dialect",
        choices=("sqlite", "postgres", "mysql"),
        default="sqlite",
        help="Диалект для --sql-out (по умолчанию sqlite)",
    )
    p.add_argument(
        "--mapping",
        type=Path,
        default=None,
        help="Путь к specs/sql/mapping.json (по умолчанию из каталога репозитория)",
    )
    p.add_argument(
        "--recreate",
        action="store_true",
        help="Перед импортом удалить и заново создать таблицы (PG: CASCADE; MySQL/SQLite: DROP по порядку)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Обработать не более N непустых строк JSONL (включая пропущенные из-за ошибок)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    args = _parse_args(argv)
    if not args.jsonl.is_file():
        logging.error("Файл не найден: %s", args.jsonl)
        return 2
    try:
        if args.sql_out is not None:
            export_jsonl_to_sql(
                args.jsonl.resolve(),
                args.sql_out.resolve(),
                dialect=args.sql_dialect,
                mapping_path=args.mapping.resolve() if args.mapping else None,
                recreate=args.recreate,
                limit=args.limit,
            )
        else:
            if args.sqlite is not None:
                db_dialect: Dialect = "sqlite"
            elif args.postgres is not None:
                db_dialect = "postgres"
            elif args.mysql is not None:
                db_dialect = "mysql"
            else:
                raise RuntimeError("CLI: ожидался один из --sqlite, --postgres, --mysql")
            import_jsonl(
                args.jsonl.resolve(),
                dialect=db_dialect,
                sqlite_path=args.sqlite.resolve() if args.sqlite else None,
                postgres_conninfo=args.postgres,
                mysql_dsn=args.mysql,
                mapping_path=args.mapping.resolve() if args.mapping else None,
                recreate=args.recreate,
                limit=args.limit,
            )
    except ImportError as exc:
        logging.error("%s", exc)
        return 2
    except (OSError, ValueError) as exc:
        logging.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
