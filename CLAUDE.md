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
docker compose run --rm converter sh -c \
  "python scrape_opendata.py -o data/download_urls.txt && python download.py -c data/download_urls.txt -o data/"
docker compose run --rm converter python convert.py data/data-*-structure-*.xml --progress-every 50000
docker compose run --rm converter pytest

# Скачать последний снимок XML в data/ (локально)
python scrape_opendata.py -o download_urls.txt
python download.py -o data/

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
  → fill_aeo_coherent_inn_ogrn  (INN/OGRN/KPP → _derived, по умолчанию)
  → fill_edulevel_from_programm_name  (EduLevelName → _derived)
  → strip_degenerate_educational_program_stubs
  → normalize_edulevel_fz273  (нормализованный EduLevelName → _derived)
  → annotate_derived_fields  (IsBranchSupplement, HasBranchSupplements → _derived)
  → build_graph_projection  (_graph → готовые поля для граф-вьювера)
  → фильтры (inactive / outside-rf / invalid-ogrn / blocklist)
  → ensure_json_safe + omit_empty_json_values
  → запись строки JSONL
После закрытия XML → 2-й проход: backfill_edulevel_name_from_programm_code_neighbors_jsonl
  (EduLevelName → _derived, перезаписывает файл; повторно вызывает build_graph_projection)
```

### Структура `_derived`

Все вычисленные/дозаполненные поля хранятся в ключе `_derived` на соответствующем уровне вложенности — **оригинальные XML-поля не мутируются**. Наличие поля в `_derived` означает, что в оригинальном датасете оно отсутствовало или было нестандартным.

| Уровень | `_derived`-поля | Причина |
|---------|-----------------|---------|
| `Certificate` | `HasBranchSupplements`, `EduOrgINN`, `EduOrgOGRN` | вычислен / отсутствовал в XML |
| `Supplement` | `IsBranchSupplement` | вычислен |
| `ActualEducationOrganization` | `INN`, `OGRN`, `KPP` | отсутствовали в карточке АО |
| `EducationalProgram` | `EduLevelName` | пустой или нестандартный уровень в XML |

Хелперы: `_set_derived(obj, key, value)` и `_get_effective(obj, key)` (читает сначала `_derived`, затем оригинал — используется внутри цепочки fill-функций).

### Структура `_graph`

`build_graph_projection(record)` формирует готовую проекцию для граф-вьювера — чистые поля без грязных оригиналов и без необходимости знать правила `_derived`. Вызывается в конце пайплайна и повторно после 2-го прохода.

```json
{
  "org": {
    "ogrn": "...", "inn": "...",
    "display_name": "Гимназия №1",
    "founder_key": "municipal:Брянская область",
    "founder_label": "Муниципальный, Брянская область"
  },
  "region": "Брянская область",
  "region_short": "Брянская",
  "control_organ": "Министерство образования ...",
  "control_organ_short": "Минобр Брянской",
  "edu_levels": ["Основное общее образование"],
  "edu_levels_short": ["ООО"],
  "programs": [
    {"code": "44.02.01", "ugs_code": "44.00.00", "edu_level": "СПО", "edu_level_short": "СПО"}
  ],
  "branches": [
    {"ogrn": "...", "display_name": "...", "edu_levels": [...], "edu_levels_short": [...], "programs": [...]}
  ]
}
```

Вспомогательные функции (`_graph`-блок в `convert.py`):

| Функция | Назначение |
|---------|------------|
| `make_display_name(full, short)` | Короткое имя узла — из кавычек, без ОПФ-обёртки |
| `shorten_region_name(name)` | Регион без «область/край/…»: «Брянская», «г. Москва» → «Москва» |
| `shorten_edu_level(name, code)` | Аббревиатура уровня: ДО/НОО/ООО/СОО/СПО/ДПО/Бакалавриат/…/ПКВК; для ПКВК с кодом уточняет подтип (06=Аспирантура, 07=Адъюнктура, 08=Ординатура, 09=Ассистентура) |
| `make_control_organ_display(name)` | «Министерство образования Брянской области» → «Минобр Брянской» |
| `_co_extract_region(text)` | Регион из конца строки ControlOrgan (родительный падеж) |
| `_derive_founder(is_federal, form_name, region_name, edu_levels)` | Синтетический учредитель: `{key, label}` |
| `_graph_collect_programs(supplement)` | edu_levels + programs (с edu_level_short) из одного supplement |

### Ключевые константы в `convert.py`

- `CERTIFICATE_ROOT_STATUSES_OMITTED_FROM_JSONL` — статусы, при которых сертификат не пишется.
- `SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL` — статусы, при которых supplement удаляется из массива.
- `CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST` — жёсткий список `Certificate.Id` (UUID), никогда не попадающих в JSONL.
- `PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME` — школьные ступени для подстановки `EduLevelName`.
- `DEFAULT_SCHEMA_FILENAME` — путь к эталонному XML-схеме (`specs/xml/data-20160908-structure-20160713.xml`).
- `_GRAPH_HIGHER_EDU_LEVELS` — уровни ВО для вывода учредителя «Минобрнауки» (при `IsFederal=true`).
- `_EDU_LEVEL_SHORT` — словарь канонических сокращений 10 уровней ФЗ-273.
- `_PKVK_BY_CODE_SEGMENT` — сегмент кода → подтип ПКВК (`06`→Аспирантура, `07`→Адъюнктура, `08`→Ординатура, `09`→Ассистентура).
- `_CO_TYPE_MAP` — правила сокращений для `ControlOrgan` (Рособрнадзор, Минобр, Миннауки, …).
- `_CO_GENITIVE_END` — регекс для извлечения региона из конца строки ControlOrgan (родительный падеж).

### Структура каталогов

- **`specs/`** — машиночитаемые артефакты: `sql/mapping.json`, `kg/mapping.json`, `prisma/mapping.json`, `json-schema/certificate-line.schema.json`, `edu_level_names_fz273_map.json`, `edu_level_names_vocab.json`, `field_labels.json`, `certificate_inn_overrides_by_ogrn.json`.
- **`tools/`** — перегенерация (`generate_*`), аудиты (`audit_*`), выборки (`extract_*`, `sample_*`), OpenRouter-черновик словаря.
- **`sql_convert/`** — `import_sql.py` (SQLite/PG/MySQL), `sql_ddl.py` (DDL по mapping).
- **`parquet_convert/`** — `import_duckdb.py` (DuckDB + Parquet).
- **`cypher_convert/`** — `export_cypher.py` (Neo4j Cypher по `specs/kg/mapping.json`).
- **`surreal_convert/`** — `import_surreal.py` (SurrealDB граф по `specs/kg/mapping.json`).
- **`viewer/`** — граф-вьювер: `api/` (FastAPI, SurrealDB backend), `web/` (React + Cytoscape.js).
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

- **`_derived` vs оригинал**: все вычисляемые поля пишутся только в `_derived`; XML-поля остаются нетронутыми. Внутри цепочки fill-функций используйте `_get_effective(obj, key)` — читает `_derived` с приоритетом над оригиналом.
- **`_graph`**: `build_graph_projection` вызывается **дважды** — в первом проходе и после 2-го прохода (backfill EduLevelName), чтобы `_graph.programs[].edu_level` всегда отражал финальное значение. Все вспомогательные функции (`make_display_name`, `shorten_edu_level`, `make_control_organ_display`, `_derive_founder`) объявлены в секции `# ---- Функции построения _graph`.
- **Второй проход** (`backfill_edulevel_name_from_programm_code_neighbors_jsonl`) пишет временный файл и **заменяет** выходной JSONL после первого прохода — не прерывайте процесс между этапами.
- **Компактный JSON по умолчанию**: ключи с `null`, пустыми `{}` и `[]` не пишутся. `--include-null-keys` возвращает полный набор полей.
- **`EduLevelName`** в `specs/edu_level_names_fz273_map.json`: в `entries` — только отличия от канона и `null`-цели; строка из `canonical_edu_level_names_fz273` без своей записи в `entries` — неявный identity. При `target=null` ключ удаляется из **обоих** мест (оригинал и `_derived`).
- Имя исходного XML-файла **не попадает** в строку JSONL. Провенанс снимка добавляется вне конвертера.
- `tools/org_name_normalize.py` — вспомогательный модуль для черновика словаря наименований; **не** вызывается из `convert.py`.
- `tools/draft_org_name_dictionary_openrouter.py` требует переменной `OPENROUTER_API_KEY` (см. `.env.example`).
- Тесты на живой выборке (`test_import_sql_live_sample.py`, `test_import_parquet_live_sample.py`) требуют файла `out/sample_live_5000.jsonl` и соответствующих env-переменных.

## Viewer (граф-вьювер)

```bash
# Запуск полного стека (SurrealDB + API + Web)
docker compose --profile viewer up -d

# Импорт JSONL в SurrealDB (из хоста с активированным venv)
python -m surreal_convert.import_surreal out/data.jsonl --url ws://127.0.0.1:8000 --recreate

# Открыть в браузере
# http://127.0.0.1:8020
```

`BIND_IP` в `.env` управляет адресом биндинга всех портов (SurrealDB 8000, API 8010, Web 8020). По умолчанию `127.2.0.1`; для WSL2 с `networkingMode=mirrored` установить `127.0.0.1`.
