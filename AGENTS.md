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

Каталог **`specs/`** — маппинги, JSON Schema, эталонный XML, `field_labels.json`. Каталог **`tools/`** — перегенерация, выборки, аналитика и справочники (см. таблицу и **[`docs/tools.md`](docs/tools.md)**).

| Файл | Роль |
|------|------|
| `convert.py` | Парсинг, типы, CLI, `convert_many`, статистика; нормализация **`ProgrammCode`** и **`UGSCode`** (компактные шесть цифр → `XX.XX.XX`); при совпадении UID AEO — дополнение пустых **INN**/**OGRN** в `ActualEducationOrganization` (корень и `Supplements[]`) из корневой AEO, **EduOrgINN**/**EduOrgOGRN** и supplement-карточек; отключение: **`--no-fill-aeo-coherent-inn-ogrn`** |
| `tools/generate_field_labels.py` | JSON `specs/field_labels.json`: путь `Certificate/…` → русская подпись из схемы |
| `specs/field_labels.json` | Сгенерированный словарь подписей для UI (`python tools/generate_field_labels.py`) |
| `specs/kg/mapping.json` | Узлы/рёбра для Knowledge Graph из строк JSONL |
| `specs/sql/mapping.json` | Таблицы / PK / FK для импорта JSONL в SQL и для Prisma |
| `specs/prisma/mapping.json` | Метаданные генерации `specs/prisma/schema.prisma` |
| `tools/generate_prisma_schema.py` | Перегенерация `specs/prisma/schema.prisma` из `specs/sql/mapping.json` |
| `specs/prisma/schema.prisma` | Схема Prisma (не править вручную) |
| `specs/json-schema/certificate-line.schema.json` | JSON Schema (2020-12) для одной строки JSONL |
| `tools/generate_json_schema.py` | Перегенерация JSON Schema |
| `tools/generate_sql_er_diagram.py` | `docs/diagrams/sql_schema_er.md` — Mermaid `erDiagram` из `specs/sql/mapping.json` (все колонки и FK, как в DDL) |
| `tools/sample_jsonl_lines.py` | Подвыборка N строк из большого JSONL (резервуар, один проход); пример: `out/sample_live_5000.jsonl` |
| `tools/generate_test_jsonl_samples.py` | Набор случайных JSONL 10/50/100/500/5000 строк в `examples/jsonl_samples/` |
| `tools/analyze_aeo_cert_vs_supplement.py` | Сводка AEO корень vs приложения; детерминированные `sample_*.jsonl` (первые N расхождений по файлу) в `examples/jsonl_samples_aeo_mismatch/`; `--no-samples` только stdout |
| `tools/extract_unique_educational_programs.py` | Уникальные программы без `Id` и без полей среза (`TypeName`, `EduNormativePeriod`, статусы аккредитации программы); **непустой `UGSName`**; **`Qualification`** по умолчанию может быть пустой (флаг **`--require-qualification`** — только с непустой квалификацией); канонизация хвоста `Qualification`; выход **по убыванию длины `Qualification`**, при равенстве — **`ProgrammCode`** (триплет по числам), затем **`UGSCode`**, имя и отпечаток → `examples/educational_programs_unique.jsonl` (вход — JSONL из **`convert.py`** с теми же **умолчаниями**, что у CLI: без «Недействующее», без псевдорегиона «за пределами РФ», компактный JSON без `null`/пустых `[]`/`{}`) |
| `tools/audit_dataset_identity_fields.py` | Сводка по **EduOrgINN**, **EduOrgOGRN**, **INN**/**OGRN** в корневом и вложенных **ActualEducationOrganization**; **`would_drop_if_require_*`**; **`INN`/`OGRN_missing_or_empty_with_same_aeo_Id_as_root`**; метрики **`*borrowable*`** — остаток в JSONL: при совпадении UID пустое поле при наличии донора по тем же правилам, что **`fill_aeo_coherent_inn_ogrn`** в **`convert.py`** (после конвертации с умолчанию часто нули); по умолчанию `examples/dataset_identity_fields_audit.json` |
| `tools/audit_aeo_supplement_root_id_with_identity_issues.py` | Строки с **любой** проблемой идентичности (как в `audit_dataset_identity_fields.py`): сводка по соотношению **`ActualEducationOrganization.Id`** в приложении с **`Id`** корневой AEO (`same` / `different` / `incomparable`); второй блок — только карточки supplement AEO с проблемой **INN** или **OGRN**; по умолчанию `examples/dataset_aeo_supplement_root_id_identity_issues.json` |
| `tools/audit_dataset_status.py` | Гистограммы корневых **`StatusName`** / **`TypeName`**; по умолчанию `examples/dataset_status_audit.json` |
| `tools/audit_dataset_region.py` | Гистограмма **`RegionName`**, счётчик псевдорегиона «за пределами РФ»; по умолчанию `examples/dataset_region_audit.json` |
| `tools/scan_jsonl_placeholder_scalars.py` | Потоковый подсчёт скалярных «плейсхолдеров» в JSONL (нули, тире, маркеры «нет данных» и т.п.) по JSON-путям; см. `--help` |
| `docs/tools.md` | Обзор **`tools/`**, аудиты, выборки; умолчания **`convert.py`** |
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
| `tests/test_generate_sql_er_diagram.py` | Генерация Mermaid ER из SQL-mapping |
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
| `tests/test_audit_dataset_identity_fields.py` | Аудит полей идентичности (ИНН/ОГРН) для PK |
| `tests/test_audit_aeo_supplement_root_id_with_identity_issues.py` | AEO Id корень vs приложение при проблемах идентичности |
| `tests/test_audit_dataset_status.py` | Аудит StatusName/TypeName |
| `tests/test_audit_dataset_region.py` | Аудит RegionName |
| `tests/test_scan_jsonl_placeholder_scalars.py` | Сканер плейсхолдеров в JSONL |

## CLI `convert.py`

- **Один** вход: по умолчанию **`out/<stem>.jsonl`**, иначе **`-o`**.
- **Несколько** без **`--merged`**: по файлу **`--out-dir/<stem>.jsonl`** (по умолчанию `out/`). **`-o` запрещён** (exit 2).
- **Несколько** + **`--merged`**: один файл, обязателен **`-o`**.
- **`--merged`** при одном входе — ошибка.

Опции: `--schema`, `--progress-every` (default 10000, `0` = тише), `--limit` (на каждый вход), **`--log-file`** (доп. лог; без него только stderr), `--report` (JSON-статистика; в `total` есть **`omitted_inactive`**, **`omitted_outside_rf_region`** и **`omitted_invalid_eduorg_ogrn`** — **`omitted_inactive`** и **`omitted_outside_rf_region`** ненулевые по умолчанию, если в XML были соответствующие строки; **`omitted_invalid_eduorg_ogrn`** — только при **`--omit-invalid-eduorg-ogrn`**; **`aeo_coherent_inn_ogrn_fills`** — сколько раз дополнены INN/OGRN в AEO при совпадении UID), `--strict`, **`--include-inactive`** (полный снимок по статусу, как в XML), **`--omit-inactive`** (избыточен: то же, что умолчание), **`--include-outside-rf-region`** (полный снимок по региону), **`--omit-outside-rf-region`** (избыточен: то же, что умолчание), **`--omit-invalid-eduorg-ogrn`**, **`--include-null-keys`** (полный JSON с `null` и пустыми `[]`/`{}`), **`--omit-null-keys`** (избыточен: то же, что умолчание), **`--no-fill-aeo-coherent-inn-ogrn`** (не дополнять INN/OGRN в AEO по согласованным источникам).

По умолчанию в JSONL **нет** строк со **`StatusName` «Недействующее»** на корне (`omitted_inactive`). С **`--include-inactive`** попадают и они. По умолчанию **нет** строк с псевдорегионом «за пределами РФ» на корневом `RegionName` (`omitted_outside_rf_region`); с **`--include-outside-rf-region`** — как в XML. С **`--omit-invalid-eduorg-ogrn`** не пишутся сертификаты без валидного корневого `EduOrgOGRN` (критерий «только цифры после очистки» как в `tools/audit_dataset_identity_fields.py`, блок `per_certificate.EduOrgOGRN`; `omitted_invalid_eduorg_ogrn` в отчёте). По умолчанию ключи с `null` и пустые вложенные `{}`/`[]` в JSON **не пишутся**; **`--include-null-keys`** возвращает полный набор полей.

В каждой записи JSONL **нет** служебного поля с именем файла XML: первичный ключ в SQL — **`certificate_id`** (корневой `Id`). Провенанс снимка реестра при необходимости добавляйте **вне конвертера** (отдельная колонка при загрузке, префикс в хранилище и т.п.).

## Решения (`Decisions`) без `Id` в JSONL

Пустой идентификатор документа в выгрузке → в JSON `Id: null` у элемента `Decisions[]`; **сертификат и организация в строке не теряются**. Импорт в SQL/DuckDB **не вставляет** такую позицию в таблицу `decisions` (нужен PK документа). См. `docs/sql_convert.md`, `docs/knowledge_graph.md`.

## Нормализация кодов в `convert.py`

- **`ProgrammCode`**, **`UGSCode`**: если после `clean_text` значение уже вида **`XX.XX.XX`**, оставляем; иначе убираются пробелы/дефисы и при ровно **шести цифрах** подряд вставляются точки (напр. `031501` → `03.15.01`, `090000` → `09.00.00`).
- **`Qualification`**: строка **`0`** (плейсхолдер) → **`null`**.

## Ошибки в полях (что в JSONL)

- **Дата** не распознана → **строка** (после очистки) + `WARNING`, `bad_dates`.
- **Булево** не распознано → **`null`** + `WARNING`, `bad_booleans`.
- **ИНН/КПП/ОГРН** не только цифры после очистки → **`null`** (ключ обычно не пишется при умолчании), `non_digit_ids` в отчёте; подробности — `logging.debug`.
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
