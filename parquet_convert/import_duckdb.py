"""Импорт JSONL в DuckDB и опционально экспорт таблиц в Parquet (те же таблицы, что в sql_convert)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from sql_convert.import_sql import iter_certificate_inserts
from sql_convert.sql_ddl import Dialect, build_create_statements, build_drop_statements, load_mapping, quote_ident


def _insert_sql_duckdb(table: str, colnames: list[str]) -> str:
    """INSERT с плейсхолдерами ?, идентификаторы в кавычках как в DDL duckdb."""
    d: Dialect = "duckdb"
    q = ",".join(quote_ident(c, d) for c in colnames)
    ph = ",".join(["?"] * len(colnames))
    return f"INSERT INTO {quote_ident(table, d)} ({q}) VALUES ({ph})"


def import_one_certificate_duckdb(con: Any, mapping: dict[str, Any], obj: dict[str, Any]) -> None:
    """Одна строка JSONL → вставки во все таблицы. Типы скаляров как для PostgreSQL (bool остаётся bool)."""
    for table, cnames, row in iter_certificate_inserts("postgres", mapping, obj):
        con.execute(_insert_sql_duckdb(table, cnames), list(row))


def export_tables_to_parquet(con: Any, mapping: dict[str, Any], parquet_dir: Path) -> None:
    parquet_dir.mkdir(parents=True, exist_ok=True)
    for t in mapping["tables"]:
        name = t["name"]
        out = parquet_dir / f"{name}.parquet"
        qn = quote_ident(name, "duckdb")
        con.execute(f"COPY (SELECT * FROM {qn}) TO ? (FORMAT PARQUET)", [str(out.resolve())])


def import_jsonl_to_duckdb(
    jsonl_path: Path,
    *,
    duckdb_path: Path | None,
    parquet_dir: Path | None,
    mapping_path: Path | None,
    recreate: bool,
    limit: int | None,
) -> int:
    try:
        import duckdb
    except ImportError as exc:
        raise ImportError("Установите пакет duckdb: pip install duckdb") from exc

    if duckdb_path is None and parquet_dir is None:
        raise ValueError("Укажите --duckdb и/или --parquet-dir")

    if duckdb_path is None:
        # База только в памяти — без пересоздания таблиц вставки в пустую схему невозможны
        recreate = True

    mapping = load_mapping(mapping_path)
    drops = build_drop_statements(mapping, "duckdb")
    creates = build_create_statements(mapping, "duckdb")

    if duckdb_path is not None:
        duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(duckdb_path.resolve()))
    else:
        con = duckdb.connect(":memory:")

    try:
        if recreate:
            for s in drops:
                con.execute(s)
            for s in creates:
                con.execute(s)

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
                    import_one_certificate_duckdb(con, mapping, obj)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    logging.warning("Пропуск строки JSONL: %s", exc)
                if limit is not None and processed >= limit:
                    break
        logging.info(
            "Обработано строк JSONL: %s (успешно импортировано объектов: %s)",
            processed,
            ok,
        )

        if parquet_dir is not None:
            export_tables_to_parquet(con, mapping, parquet_dir.resolve())
            logging.info("Parquet записан в каталог: %s", parquet_dir)
    finally:
        con.close()
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Импорт JSONL (выход convert.py) в DuckDB и/или экспорт таблиц в Parquet по specs/sql/mapping.json.",
    )
    p.add_argument("jsonl", type=Path, help="Путь к .jsonl")
    p.add_argument(
        "--duckdb",
        type=Path,
        metavar="PATH",
        default=None,
        help="Файл базы DuckDB (создаётся при отсутствии). Можно не указывать, если нужен только --parquet-dir (тогда используется in-memory).",
    )
    p.add_argument(
        "--parquet-dir",
        type=Path,
        metavar="DIR",
        default=None,
        help="После импорта записать каждую таблицу в отдельный .parquet в этом каталоге",
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
        help="Удалить и заново создать таблицы перед импортом",
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
        import_jsonl_to_duckdb(
            args.jsonl.resolve(),
            duckdb_path=args.duckdb.resolve() if args.duckdb else None,
            parquet_dir=args.parquet_dir.resolve() if args.parquet_dir else None,
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
