# Контекст проекта (для ассистента / промпта)

Файл в корне: **`AGENTS.md`** (в Cursor удобно ссылаться как `@AGENTS.md`). Скопируйте разделы в начало чата, чтобы восстановить контекст без длинного ввода.

## Назначение

Потоковая конвертация XML реестра **госаккредитации** образовательных организаций (Рособрнадзор, ИС ГА) в **JSON Lines** (UTF-8, без BOM). Крупные файлы не читаются целиком в память (`iterparse` по `Certificate`).

## Источник данных

- Страница: `https://isga.obrnadzor.gov.ru/accredreestr/opendata/` (Vue SPA).
- Список версий XML: тот же HTML, что у `https://isga.obrnadzor.gov.ru/api/spa/accredreestr/perechen` (iframe «Гиперссылки (URL) на версии набора данных»).
- **`scrape_opendata.py`** — находит `app.*.js`, путь iframe, парсит ссылки `*.xml`.
- **`download.py --discover`** — URL со страницы версий, **только последний снимок** по `data-YYYYMMDD-` в имени; **`--discover --all-versions`** — все ссылки. Потоковое скачивание в `data/` (`-o` = **каталог**). Список URL из файла: без аргументов читается **`download_urls.txt`** (или **`-c` / `--config`**).

## Эталон полей (схема)

- **`specs/xml/data-20160908-structure-20160713.xml`**; в коде имя файла — константа `DEFAULT_SCHEMA_FILENAME` в `convert.py`, путь по умолчанию — `specs/xml/<имя>`.
- Переопределение: **`--schema путь`**. Нужен для списка известных тегов (одно предупреждение на новый тег за прогон) и тестов `test_schema_compat.py`.

## Главные файлы

Каталог **`specs/`** — маппинги, JSON Schema, эталонный XML, `field_labels.json`. Каталог **`tools/`** — перегенерация, выборки, аналитика и справочники (см. таблицу).

| Файл | Роль |
|------|------|
| `convert.py` | Парсинг, типы, CLI, `convert_many`, статистика; нормализация **`ProgrammCode`** и **`UGSCode`** (компактные шесть цифр → `XX.XX.XX`) |
| `tools/generate_field_labels.py` | JSON `specs/field_labels.json`: путь `Certificate/…` → русская подпись из схемы |
| `specs/field_labels.json` | Сгенерированный словарь подписей для UI (`python tools/generate_field_labels.py`) |
| `specs/kg/mapping.json` | Узлы/рёбра для Knowledge Graph из строк JSONL |
| `specs/sql/mapping.json` | Таблицы / PK / FK для импорта JSONL в SQL и для Prisma |
| `specs/prisma/mapping.json` | Метаданные генерации `specs/prisma/schema.prisma` |
| `tools/generate_prisma_schema.py` | Перегенерация `specs/prisma/schema.prisma` из `specs/sql/mapping.json` |
| `specs/prisma/schema.prisma` | Схема Prisma (не править вручную) |
| `specs/json-schema/certificate-line.schema.json` | JSON Schema (2020-12) для одной строки JSONL |
| `tools/generate_json_schema.py` | Перегенерация JSON Schema |
| `tools/sample_jsonl_lines.py` | Подвыборка N строк из большого JSONL (резервуар, один проход); пример: `out/sample_live_5000.jsonl` |
| `tools/generate_test_jsonl_samples.py` | Набор случайных JSONL 10/50/100/500/5000 строк в `examples/jsonl_samples/` |
| `tools/analyze_aeo_cert_vs_supplement.py` | Сводка AEO корень vs приложения; детерминированные `sample_*.jsonl` (первые N расхождений по файлу) в `examples/jsonl_samples_aeo_mismatch/`; `--no-samples` только stdout |
| `tools/extract_unique_educational_programs.py` | Уникальные программы без `Id` и без полей среза (`TypeName`, `EduNormativePeriod`, статусы аккредитации программы); **непустой `UGSName`**; **`Qualification`** по умолчанию может быть пустой (флаг **`--require-qualification`** — только с непустой квалификацией); канонизация хвоста `Qualification`; выход **по убыванию длины `Qualification`**, при равенстве — **`UGSCode`** и стабильный хвост → `examples/educational_programs_unique.jsonl` (обычно вход — полный JSONL после `convert.py --include-inactive`) |
| `tools/scan_jsonl_placeholder_scalars.py` | Потоковый подсчёт скалярных «плейсхолдеров» в JSONL (нули, тире, маркеры «нет данных» и т.п.) по JSON-путям; см. `--help` |
| `docs/cypher_export.md` | JSONL → Cypher (Neo4j) по `specs/kg/mapping.json` |
| `examples/accred_graph_preview.cypher` | Мини-пример графа (1 сертификат) для Neo4j Browser |
| `cypher_convert/export_cypher.py` | CLI: `python -m cypher_convert.export_cypher …` |
| `docs/sql_convert.md` | Пояснения к SQL-импорту |
| `docs/parquet_duckdb.md` | JSONL → DuckDB и экспорт Parquet |
| `docs/prisma.md` | Prisma: генерация, Datasource, ограничения |
| `docs/json_schema.md` | JSON Schema: валидация, перегенерация |
| `sql_convert/import_sql.py` | JSONL → SQLite / PostgreSQL / MySQL (`python -m sql_convert.import_sql`) |
| `sql_convert/sql_ddl.py` | DDL из `specs/sql/mapping.json` (SQLite, PostgreSQL, MySQL, DuckDB) |
| `parquet_convert/import_duckdb.py` | JSONL → DuckDB / Parquet (`python -m parquet_convert.import_duckdb`) |
| `download.py` | Скачивание XML, `--discover`, `--save-urls` |
| `scrape_opendata.py` | Только поиск URL |
| `tests/test_convert.py` | Основные тесты |
| `tests/test_json_schema.py` | JSON Schema vs фикстуры |
| `tests/test_field_labels.py` | Генерация подписей |
| `tests/test_export_cypher.py` | Экспорт Cypher по KG-mapping |
| `tests/test_sql_mapping.py` | Структура `specs/sql/mapping.json` |
| `tests/test_prisma_schema.py` | `specs/prisma/mapping.json`, генерация schema |
| `tests/test_schema_compat.py` | Константы ⊆ схема XML |
| `tests/test_scrape_opendata.py` | Парсер HTML perechen |
| `tests/test_import_sql.py` | Импорт JSONL в SQLite / PostgreSQL / MySQL (опц. интеграция по DSN) |
| `tests/test_import_sql_live_sample.py` | Опционально: импорт `out/sample_live_5000.jsonl` при **`ACCRED_SQL_LIVE_SAMPLE=1`** |
| `tests/test_import_parquet_live_sample.py` | Опционально: Parquet с той же выборкой при **`ACCRED_PARQUET_LIVE_SAMPLE=1`** |
| `tests/test_import_duckdb.py` | Импорт JSONL в DuckDB и Parquet (нужен пакет `duckdb`) |
| `tests/test_kg_mapping.py` | Структура и `format_version` в `specs/kg/mapping.json` |
| `tests/test_analyze_aeo_cert_vs_supplement.py` | CLI сводки AEO |
| `tests/test_generate_test_jsonl_samples.py` | Генерация `examples/jsonl_samples/sample_*.jsonl` |
| `tests/test_extract_unique_educational_programs.py` | Справочник уникальных программ |
| `tests/test_scan_jsonl_placeholder_scalars.py` | Сканер плейсхолдеров в JSONL |

## CLI `convert.py`

- **Один** вход: по умолчанию **`out/<stem>.jsonl`**, иначе **`-o`**.
- **Несколько** без **`--merged`**: по файлу **`--out-dir/<stem>.jsonl`** (по умолчанию `out/`). **`-o` запрещён** (exit 2).
- **Несколько** + **`--merged`**: один файл, обязателен **`-o`**.
- **`--merged`** при одном входе — ошибка.

Опции: `--schema`, `--progress-every` (default 10000, `0` = тише), `--limit` (на каждый вход), **`--log-file`** (доп. лог; без него только stderr), `--report` (JSON-статистика; в `total` есть **`omitted_inactive`** — ненулевой только без **`--include-inactive`**), `--strict`, **`--include-inactive`**, **`--omit-null-keys`** (не писать в JSON ключи с `null`/пустыми строками и пустыми вложенными `{}`/`[]` после нормализации — компактнее файл).

По умолчанию **без** `--include-inactive` такие сертификаты **пропускаются** (`omitted_inactive` в отчёте). Для аналитики и справочников по всем строкам реестра используйте **`--include-inactive`**.

В каждой записи: **`_source_file`** — имя исходного XML.

## Решения (`Decisions`) без `Id` в JSONL

Пустой идентификатор документа в выгрузке → в JSON `Id: null` у элемента `Decisions[]`; **сертификат и организация в строке не теряются**. Импорт в SQL/DuckDB **не вставляет** такую позицию в таблицу `decisions` (нужен PK документа). См. `docs/sql_convert.md`, `docs/knowledge_graph.md`.

## Нормализация кодов в `convert.py`

- **`ProgrammCode`**, **`UGSCode`**: если после `clean_text` значение уже вида **`XX.XX.XX`**, оставляем; иначе убираются пробелы/дефисы и при ровно **шести цифрах** подряд вставляются точки (напр. `031501` → `03.15.01`, `090000` → `09.00.00`).
- **`Qualification`**: строка **`0`** (плейсхолдер) → **`null`**.

## Ошибки в полях (что в JSONL)

- **Дата** не распознана → **строка** (после очистки) + `WARNING`, `bad_dates`.
- **Булево** не распознано → **`null`** + `WARNING`, `bad_booleans`.
- **ИНН/КПП/ОГРН** не только цифры → **строка** после очистки + `WARNING`, `non_digit_ids`.
- **Запись целиком** падает при обработке → строка в JSONL **не пишется**, `skipped` / `broken_records`.

## Парсинг

`lxml.etree.iterparse`, `events=("end",)`, `tag="Certificate"`, `huge_tree=True`, `recover=True`, файл в **`rb`**. После каждого `Certificate`: `elem.clear()` и удаление предыдущих siblings.

## Зависимости

`requirements.txt`: `lxml`, `requests`, `pytest`, **`jsonschema`**, **`psycopg[binary]`** (PostgreSQL), **`pymysql`** (MySQL), **`duckdb`**. В конвертере **нет** `xmltodict`, `pandas`, `pydantic`.

## Тесты

```bash
pytest
# опционально: RUN_SLOW=1 pytest -k streaming
# опционально: ACCRED_SQL_LIVE_SAMPLE=1 pytest tests/test_import_sql_live_sample.py -q
# опционально: ACCRED_PARQUET_LIVE_SAMPLE=1 pytest tests/test_import_parquet_live_sample.py -q
```

## Каталоги и gitignore

- **`specs/`** — маппинги KG/SQL/Prisma, JSON Schema, эталонный XML, `field_labels.json` (в git).
- **`docs/diagrams/`** — диаграммы (исходники Mermaid, экспорт изображений; в git).
- **`tools/`** — перегенерация (`generate_*`), выборки, аналитика и справочники (см. таблицу выше).
- **`data/*.xml`** — не в репозитории (скачанные выгрузки).
- **`out/`** — не в репозитории (JSONL, логи, отчёты `convert.py`). Повторный запуск с тем же именем файла **перезаписывает** его (`"w"`).
