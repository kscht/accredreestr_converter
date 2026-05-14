# JSONL → DuckDB и Parquet

Нормализованная загрузка строк JSONL (выход `convert.py`) в **DuckDB** и опциональный экспорт таблиц в **Parquet**. Источник схемы тот же, что для SQL-импорта: **[`../specs/sql/mapping.json`](../specs/sql/mapping.json)** (см. [`sql_convert.md`](sql_convert.md)). Проекция строки совпадает с `sql_convert` (в т.ч. элементы `Decisions[]` **без** непустого `Id` не попадают в таблицу **`decisions`**, сертификат импортируется; в **`educational_programs`** строки различаются **`program_slot`**, повтор **`program_id`** из реестра допустим).

## CLI

Из корня репозитория (с активированным venv и установленным **`duckdb`**):

```bash
# Файл DuckDB на диске
python -m parquet_convert.import_duckdb out/data.jsonl --duckdb data/warehouse.duckdb --recreate

# Только Parquet (база in-memory; таблицы всегда пересоздаются перед импортом)
python -m parquet_convert.import_duckdb out/data.jsonl --parquet-dir out/parquet --recreate

# И то и другое: загрузить в .duckdb и дополнительно выгрузить .parquet
python -m parquet_convert.import_duckdb out/data.jsonl --duckdb data/warehouse.duckdb --parquet-dir out/parquet --recreate
```

- **`--recreate`** — выполнить `DROP TABLE … CASCADE` и `CREATE TABLE` по mapping (для файла `.duckdb` без этого флага таблицы должны уже существовать с той же схемой).
- **`--mapping`** — другой файл mapping (по умолчанию `specs/sql/mapping.json`).
- **`--limit N`** — не более **N непустых** строк JSONL (счётчик по входу; строки с ошибками импорта тоже учитываются).

## DDL и внешние ключи

Для DuckDB в [`sql_convert/sql_ddl.py`](../sql_convert/sql_ddl.py) используется диалект **`duckdb`**: у внешних ключей принудительно **`ON DELETE NO ACTION`**, потому что в DuckDB нельзя задать `ON DELETE CASCADE` / `SET NULL` / `SET DEFAULT` для FK.

## Зависимости

Пакет **`duckdb`** — в [`requirements.txt`](../requirements.txt). Остальные модули репозитория для этого CLI не требуются.

## Локальная выборка из полной выгрузки

Каталог **`out/`** в git не коммитится. Чтобы получить воспроизводимую подвыборку из большого `.jsonl` (например, для локальной проверки импорта):

```bash
python tools/sample_jsonl_lines.py out/data-20260403-structure-20160713.jsonl \
  -o out/sample_live_5000.jsonl -n 5000 --seed 42
```

Резервуарный алгоритм: один проход по файлу, память O(N). **`--seed`** фиксирует состав строк при тех же входе и N.

Набор фиксированных случайных выборок **10 / 50 / 100 / 500 / 5000** строк (разные seed для каждого размера) в **`examples/jsonl_samples/`**:

```bash
python tools/generate_test_jsonl_samples.py
# или явно:
python tools/generate_test_jsonl_samples.py out/data-20260403-structure-20160713.jsonl -o examples/jsonl_samples
```

Опции: **`--sizes`**, **`--seed-base`**. Одна строка — один объект сертификата, как в полном JSONL.

## Опциональный тест на живой подвыборке

При наличии **`out/sample_live_5000.jsonl`** (см. команды выше):

```bash
ACCRED_PARQUET_LIVE_SAMPLE=1 pytest tests/test_import_parquet_live_sample.py -q
```

Тест грузит **первые 100** непустых строк `out/sample_live_5000.jsonl` в in-memory DuckDB (счётчик как у CLI `--limit`), пишет **`.parquet`** по каждой таблице из `specs/sql/mapping.json` во временный каталог и проверяет **100** строк в `certificates.parquet`. Полный прогон 5000+ строк в Parquet оставьте для ручного CLI — в pytest это слишком долго. В CI по умолчанию не запускается (нет файла в `out/` и переменная не задана).

## Связь с Knowledge Graph и Prisma

Та же декомпозиция сущностей, что в [`knowledge_graph.md`](knowledge_graph.md): граф, SQL/Prisma и DuckDB/Parquet — разные представления одной логики строки JSONL.
