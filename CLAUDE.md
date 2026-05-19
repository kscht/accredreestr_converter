# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Назначение

Потоковая конвертация XML реестра госаккредитации образовательных организаций (Рособрнадзор, ИС ГА) в **JSON Lines** (UTF-8, без BOM). Ядро — `convert.py`, читающий `<Certificate>` поэлементно через `lxml.etree.iterparse` без загрузки XML в память.

## Команды

```bash
# Окружение (локально)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Через Docker (не нужно локальное venv)
docker compose build
docker compose run --rm converter python download.py --discover -o data/
docker compose run --rm converter python convert.py data/data-*-structure-*.xml --progress-every 50000
docker compose run --rm converter pytest

# Скачать последний снимок XML в data/
python download.py --discover -o data/

# Конвертация XML → JSONL (по умолчанию: out/<имя-xml>.jsonl)
python convert.py data/data-*-structure-*.xml --progress-every 50000 --report out/report.json

# Тесты
pytest
pytest tests/test_convert.py                         # только основные тесты конвертера
RUN_SLOW=1 pytest -k streaming                       # медленный потоковый тест
ACCRED_SQL_LIVE_SAMPLE=1 pytest tests/test_import_sql_live_sample.py -q
ACCRED_PARQUET_LIVE_SAMPLE=1 pytest tests/test_import_parquet_live_sample.py -q
ACCRED_SURREAL_LIVE=1 pytest tests/test_import_surreal.py -q  # нужен SurrealDB на ws://localhost:8000
```

## Архитектура

### Пайплайн `convert.py` (один `Certificate`)

```
elem_to_dict (парсинг + типизация)
  → strip_supplements_by_excluded_status
  → fill_aeo_coherent_inn_ogrn  (INN/OGRN/KPP в AEO и EduOrg* — по умолчанию)
  → fill_edulevel_from_programm_name
  → strip_degenerate_educational_program_stubs
  → normalize_edulevel_fz273
  → фильтры (inactive / outside-rf / invalid-ogrn / blocklist)
  → ensure_json_safe + omit_empty_json_values
  → запись строки JSONL
После закрытия XML → 2-й проход: backfill_edulevel_name_from_programm_code_neighbors_jsonl (перезаписывает файл)
```

### Ключевые константы в `convert.py`

- `CERTIFICATE_ROOT_STATUSES_OMITTED_FROM_JSONL` — статусы, при которых сертификат не пишется.
- `SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL` — статусы, при которых supplement удаляется из массива.
- `CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST` — жёсткий список `Certificate.Id` (UUID), никогда не попадающих в JSONL.
- `PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME` — школьные ступени для подстановки `EduLevelName`.
- `DEFAULT_SCHEMA_FILENAME` — путь к эталонному XML-схеме (`specs/xml/data-20160908-structure-20160713.xml`).

### Структура каталогов

- **`specs/`** — машиночитаемые артефакты: `sql/mapping.json`, `kg/mapping.json`, `prisma/mapping.json`, `json-schema/certificate-line.schema.json`, `edu_level_names_fz273_map.json`, `edu_level_names_vocab.json`, `field_labels.json`, `certificate_inn_overrides_by_ogrn.json`.
- **`tools/`** — перегенерация (`generate_*`), аудиты (`audit_*`), выборки (`extract_*`, `sample_*`), OpenRouter-черновик словаря.
- **`sql_convert/`** — `import_sql.py` (SQLite/PG/MySQL), `sql_ddl.py` (DDL по mapping).
- **`parquet_convert/`** — `import_duckdb.py` (DuckDB + Parquet).
- **`cypher_convert/`** — `export_cypher.py` (Neo4j Cypher по `specs/kg/mapping.json`).
- **`surreal_convert/`** — `import_surreal.py` (SurrealDB граф по `specs/kg/mapping.json`).
- **`tests/fixtures/`** — XML-фикстуры для `pytest`.
- **`data/`**, **`out/`** — не в репозитории (XML-снимки и результаты конвертации).

### Типизация полей (`normalize_scalar`)

| Группа | Правило |
|--------|---------|
| Булевы (`IsFederal`, `IsAccredited`, …) | `1/true/да` → `true`; иначе `null` + WARNING |
| Даты (`IssueDate`, `EndDate`, …) | → `YYYY-MM-DD`; иначе строка + WARNING |
| ИНН / КПП / ОГРН | только цифры после очистки; иначе `null`, счётчик `non_digit_ids` |
| `ProgrammCode`, `UGSCode` | шесть цифр → `XX.XX.XX`; уже разделённые точками — без изменений |
| `Qualification` | строка `"0"` → `null` |

### Связанные маппинги

Три файла описывают **одну** модель данных и должны обновляться согласованно при изменении конвертера:
- `specs/sql/mapping.json` — таблицы / PK / FK (используется SQL, DuckDB, Parquet, Prisma).
- `specs/kg/mapping.json` — узлы и рёбра для Knowledge Graph / Cypher / SurrealDB.
- `specs/json-schema/certificate-line.schema.json` — JSON Schema 2020-12 для одной строки JSONL.

Призма генерируется: `python tools/generate_prisma_schema.py`.  
JSON Schema: `python tools/generate_json_schema.py`.  
ER-диаграмма: `python tools/generate_sql_er_diagram.py`.

## Важные особенности

- **Второй проход** (`backfill_edulevel_name_from_programm_code_neighbors_jsonl`) пишет временный файл и **заменяет** выходной JSONL после первого прохода — не прерывайте процесс между этапами.
- **Компактный JSON по умолчанию**: ключи с `null`, пустыми `{}` и `[]` не пишутся. `--include-null-keys` возвращает полный набор полей.
- **`EduLevelName`** в `specs/edu_level_names_fz273_map.json`: в `entries` — только отличия от канона и `null`-цели; строка из `canonical_edu_level_names_fz273` без своей записи в `entries` — неявный identity.
- Имя исходного XML-файла **не попадает** в строку JSONL. Провенанс снимка добавляется вне конвертера.
- `tools/org_name_normalize.py` — вспомогательный модуль для черновика словаря наименований; **не** вызывается из `convert.py`.
- `tools/draft_org_name_dictionary_openrouter.py` требует переменной `OPENROUTER_API_KEY` (см. `.env.example`).
- Тесты на живой выборке (`test_import_sql_live_sample.py`, `test_import_parquet_live_sample.py`) требуют файла `out/sample_live_5000.jsonl` и соответствующих env-переменных.
