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

Каталог **`specs/`** — маппинги, JSON Schema, эталонный XML, `field_labels.json`. Каталог **`tools/`** — скрипты `generate_*`.

| Файл | Роль |
|------|------|
| `convert.py` | Парсинг, типы, CLI, `convert_many`, статистика |
| `tools/generate_field_labels.py` | JSON `specs/field_labels.json`: путь `Certificate/…` → русская подпись из схемы |
| `specs/field_labels.json` | Сгенерированный словарь подписей для UI (`python tools/generate_field_labels.py`) |
| `specs/kg/mapping.json` | Узлы/рёбра для Knowledge Graph из строк JSONL |
| `specs/sql/mapping.json` | Таблицы / PK / FK для импорта JSONL в SQL и для Prisma |
| `specs/prisma/mapping.json` | Метаданные генерации `specs/prisma/schema.prisma` |
| `tools/generate_prisma_schema.py` | Перегенерация `specs/prisma/schema.prisma` из `specs/sql/mapping.json` |
| `specs/prisma/schema.prisma` | Схема Prisma (не править вручную) |
| `specs/json-schema/certificate-line.schema.json` | JSON Schema (2020-12) для одной строки JSONL |
| `tools/generate_json_schema.py` | Перегенерация JSON Schema |
| `docs/knowledge_graph.md` | Пояснения к KG |
| `docs/sql_convert.md` | Пояснения к SQL-импорту |
| `docs/prisma.md` | Prisma: генерация, Datasource, ограничения |
| `docs/json_schema.md` | JSON Schema: валидация, перегенерация |
| `sql_convert/import_sql.py` | JSONL → SQLite / PostgreSQL / MySQL (`python -m sql_convert.import_sql`) |
| `sql_convert/sql_ddl.py` | DDL из `specs/sql/mapping.json` |
| `download.py` | Скачивание XML, `--discover`, `--save-urls` |
| `scrape_opendata.py` | Только поиск URL |
| `tests/test_convert.py` | Основные тесты |
| `tests/test_json_schema.py` | JSON Schema vs фикстуры |
| `tests/test_field_labels.py` | Генерация подписей |
| `tests/test_kg_mapping.py` | Структура `specs/kg/mapping.json` |
| `tests/test_sql_mapping.py` | Структура `specs/sql/mapping.json` |
| `tests/test_prisma_schema.py` | `specs/prisma/mapping.json`, генерация schema |
| `tests/test_schema_compat.py` | Константы ⊆ схема XML |
| `tests/test_scrape_opendata.py` | Парсер HTML perechen |
| `tests/test_import_sql.py` | Импорт JSONL в SQLite / PostgreSQL / MySQL (опц. интеграция по DSN) |

## CLI `convert.py`

- **Один** вход: по умолчанию **`out/<stem>.jsonl`**, иначе **`-o`**.
- **Несколько** без **`--merged`**: по файлу **`--out-dir/<stem>.jsonl`** (по умолчанию `out/`). **`-o` запрещён** (exit 2).
- **Несколько** + **`--merged`**: один файл, обязателен **`-o`**.
- **`--merged`** при одном входе — ошибка.

Опции: `--schema`, `--progress-every` (default 10000, `0` = тише), `--limit` (на каждый вход), **`--log-file`** (доп. лог; без него только stderr), `--report` (JSON-статистика), `--strict`.

В каждой записи: **`_source_file`** — имя исходного XML.

## Ошибки в полях (что в JSONL)

- **Дата** не распознана → **строка** (после очистки) + `WARNING`, `bad_dates`.
- **Булево** не распознано → **`null`** + `WARNING`, `bad_booleans`.
- **ИНН/КПП/ОГРН** не только цифры → **строка** после очистки + `WARNING`, `non_digit_ids`.
- **Запись целиком** падает при обработке → строка в JSONL **не пишется**, `skipped` / `broken_records`.

## Парсинг

`lxml.etree.iterparse`, `events=("end",)`, `tag="Certificate"`, `huge_tree=True`, `recover=True`, файл в **`rb`**. После каждого `Certificate`: `elem.clear()` и удаление предыдущих siblings.

## Зависимости

`requirements.txt`: `lxml`, `requests`, `pytest`, **`jsonschema`**, **`psycopg[binary]`** (PostgreSQL), **`pymysql`** (MySQL). В конвертере **нет** `xmltodict`, `pandas`, `pydantic`.

## Тесты

```bash
pytest
# опционально: RUN_SLOW=1 pytest -k streaming
```

## Каталоги и gitignore

- **`specs/`** — маппинги KG/SQL/Prisma, JSON Schema, эталонный XML, `field_labels.json` (в git).
- **`tools/`** — скрипты перегенерации.
- **`data/*.xml`** — не в репозитории (скачанные выгрузки).
- **`out/`** — не в репозитории (JSONL, логи, отчёты `convert.py`). Повторный запуск с тем же именем файла **перезаписывает** его (`"w"`).
