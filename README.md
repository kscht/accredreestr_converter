# Конвертер XML реестра аккредитации → JSONL

Потоковая конвертация выгрузок **ИС ГА** (Рособрнадзор) в **JSON Lines**: одна строка = один `<Certificate>`, UTF-8 без BOM.

**Контекст для ИИ-ассистента:** в корне лежит [`AGENTS.md`](AGENTS.md) — краткие правила, пути и CLI; удобно вставлять в начало промпта в новой сессии.

## Быстрый старт

### Локально (Linux / macOS)

В **Windows** вместо `source` выполните `.venv\Scripts\activate`.

```bash
git clone git@github.com:kscht/accredreestr_converter.git
cd accredreestr_converter

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Найти URL последней выгрузки и сохранить в download_urls.txt (gitignored)
python scrape_opendata.py -o download_urls.txt

# Скачать XML в data/  (читает download_urls.txt по умолчанию)
python download.py -o data/

# Конвертация → out/<имя-xml>.jsonl
# По умолчанию: без «Недействующее/Прекращено/Лишен» на корне и в Supplements,
# без псевдорегиона «за пределами РФ», компактный JSON (без null и пустых []/{})).
# Полный снимок: --include-inactive --include-outside-rf-region --include-null-keys
mkdir -p out
python convert.py data/data-*-structure-*.xml \
  --progress-every 50000 \
  --report out/convert_report.json \
  --log-file out/convert.log
```

### Через Docker

Если не нужно настраивать Python-окружение — `data/` и `out/` монтируются с хоста:

```bash
git clone git@github.com:kscht/accredreestr_converter.git
cd accredreestr_converter

docker compose build

# Найти URL и скачать XML — оба шага в одном контейнере, download_urls.txt в data/
docker compose run --rm converter sh -c \
  "python scrape_opendata.py -o data/download_urls.txt && python download.py -c data/download_urls.txt -o data/"

docker compose run --rm converter python convert.py data/data-*-structure-*.xml \
  --progress-every 50000 --report out/convert_report.json
docker compose run --rm converter pytest
```

## Структура репозитория

- **`specs/`** — машиночитаемые артефакты: маппинги KG/SQL/Prisma, JSON Schema, эталонный XML структуры, `field_labels.json`.
- **`tools/`** — перегенерация (`generate_*`), случайные подвыборки JSONL, аналитика (`analyze_*`, `scan_*`), справочник программ (`extract_*`), опционально черновик словаря имён OpenRouter и аудит филиалов; см. таблицу ниже и **[`docs/tools.md`](docs/tools.md)**.
- **`docs/tools.md`** — обзор скриптов **`tools/`**, аудитов и связь с умолчаниями **`convert.py`**.
- **`docs/convert.md`** — подробная логика **`convert.py`**: парсинг, срезы, нормализация кодов/ступеней ФЗ-273, дозаполнения, глобальный 2-й проход по программам, отчёт `--report`.
- **`docs/diagrams/`** — диаграммы (исходники и экспорт).
- **Корень** — основной CLI (`convert.py`, `download.py`, `scrape_opendata.py`), пакеты `sql_convert/`, `parquet_convert/`, `cypher_convert/`, `surreal_convert/`; `Dockerfile`, `docker-compose.yml`.

| Путь | Назначение |
|------|------------|
| `docs/tools.md` | Обзор **`tools/`**: генерация, выборки, аудиты; умолчания **`convert.py`** и поля ИНН/КПП/ОГРН |
| `docs/convert.md` | Логика конвертера: чистки, нормализация, дозаполнения, счётчики отчёта |
| `tools/generate_field_labels.py` | Генерация `specs/field_labels.json` из эталонной XML-схемы |
| `specs/field_labels.json` | Подписи полей для UI (`python tools/generate_field_labels.py`) |
| `convert.py` | Конвертация XML → JSONL, CLI; дозаполнение ИНН/ОГРН/КПП в AEO и на корне сертификата (см. `convert.py` docstring и **`AGENTS.md`**); отключение дозаполнений AEO/сертификата: **`--no-fill-aeo-coherent-inn-ogrn`**; ручной ОГРН→ИНН: **`specs/certificate_inn_overrides_by_ogrn.json`**, **`--no-certificate-inn-overrides-by-ogrn`**, **`--certificate-inn-overrides-by-ogrn-json`** |
| `specs/kg/mapping.json` | Карта узлов/рёбер для Knowledge Graph из JSONL |
| `specs/sql/mapping.json` | Таблицы / PK / FK для импорта JSONL в SQL и для генерации Prisma |
| `specs/prisma/mapping.json` | Метаданные генерации `specs/prisma/schema.prisma` |
| `tools/generate_prisma_schema.py` | Генерация `specs/prisma/schema.prisma` из `specs/sql/mapping.json` |
| `specs/prisma/schema.prisma` | Схема Prisma (перегенерировать после смены SQL-mapping) |
| `specs/json-schema/certificate-line.schema.json` | JSON Schema (2020-12) для одной строки JSONL |
| `tools/generate_json_schema.py` | Перегенерация JSON Schema |
| `tools/generate_sql_er_diagram.py` | Mermaid ER по `specs/sql/mapping.json` → `docs/diagrams/sql_schema_er.md` |
| `tools/sample_jsonl_lines.py` | Случайная подвыборка N строк из большого JSONL (резервуар, один проход) |
| `tools/generate_test_jsonl_samples.py` | Набор выборок 10/50/100/500/5000 строк → `examples/jsonl_samples/sample_*.jsonl` |
| `tools/analyze_aeo_cert_vs_supplement.py` | Сводка несовпадений AEO (корень сертификата vs приложения); образцы в `examples/jsonl_samples_aeo_mismatch/sample_*.jsonl` |
| `tools/extract_unique_educational_programs.py` | Справочник уникальных `EducationalProgram` → `examples/educational_programs_unique.jsonl` (вход — JSONL из `convert.py`; сортировка: длина `Qualification` по убыванию, затем `ProgrammCode` как `XX.XX.XX` по числам, затем `UGSCode` так же, хвост — имя и отпечаток) |
| `tools/audit_dataset_identity_fields.py` | Сводка по **EduOrgINN**, **EduOrgOGRN**, **INN**/**OGRN** в корневом и вложенных **ActualEducationOrganization** (приложения): непустые значения, «только цифры» после очистки, **`would_drop_if_require_*`**, плюс сколько карточек в приложении с пустым INN/OGRN при **совпадении UID-полей AEO** с корнем (`Id` без учёта регистра; при двусторонней заполненности — **`HeadEduOrgId`**); метрики **`*borrowable*`** — **остаток** в файле при том же UID и доноре (**корневая AEO** и/или **EduOrgINN** / **EduOrgOGRN**; правила как у **`fill_aeo_coherent_inn_ogrn`** в **`convert.py`**) → `examples/dataset_identity_fields_audit.json` |
| `tools/audit_aeo_supplement_root_id_with_identity_issues.py` | Строки с **любой** проблемой идентичности (как в `audit_dataset_identity_fields.py`): разрез **`ActualEducationOrganization.Id`** в приложении относительно корня (`same` / `different` / несравнимо); второй блок — только supplement AEO с проблемой **INN** или **OGRN** → `examples/dataset_aeo_supplement_root_id_identity_issues.json` |
| `tools/audit_dataset_status.py` | Гистограммы корневых **`StatusName`** и **`TypeName`** → `examples/dataset_status_audit.json` |
| `tools/audit_dataset_region.py` | Гистограмма **`RegionName`**, счётчик псевдорегиона «за пределами РФ» → `examples/dataset_region_audit.json` |
| `tools/scan_jsonl_placeholder_scalars.py` | Подсчёт скалярных плейсхолдеров в JSONL по путям (нули, тире, «н/д» и т.п.); см. `--help` |
| `tools/org_name_normalize.py` | Вспомогательные функции для черновика словаря имён (**вне** конвертера); см. **`docs/tools.md`** |
| `tools/draft_org_name_dictionary_openrouter.py` | Черновик словаря через OpenRouter (**`httpx`**, **`OPENROUTER_API_KEY`**); см. **`.env.example`** и **`docs/tools.md`** |
| `tools/diff_org_name_dictionaries.py` | Сравнение JSON черновиков (в т.ч. две модели в одном файле v2) |
| `tools/audit_dataset_branches.py` | Аудит supplement-филиалов (AEO Id ≠ корня) → `examples/dataset_branches_audit.json` |
| `docs/cypher_export.md` | JSONL → Cypher (Neo4j) по KG-mapping |
| `cypher_convert/export_cypher.py` | Экспорт `.cypher`: `python -m cypher_convert.export_cypher …` |
| `docs/sql_convert.md` | Пояснения к SQL: ключи, вложенность, типы |
| `docs/parquet_duckdb.md` | JSONL → DuckDB и Parquet |
| `docs/prisma.md` | Prisma: генерация schema, Datasource, ограничения |
| `docs/json_schema.md` | JSON Schema: проверка строк, ограничения |
| `sql_convert/import_sql.py` | Импорт JSONL в SQLite, PostgreSQL или MySQL (`python -m sql_convert.import_sql …`) |
| `sql_convert/sql_ddl.py` | DDL из `specs/sql/mapping.json` (в т.ч. диалект DuckDB) |
| `parquet_convert/import_duckdb.py` | Импорт JSONL в DuckDB и/или выгрузка таблиц в Parquet (`python -m parquet_convert.import_duckdb …`) |
| `surreal_convert/import_surreal.py` | Импорт JSONL в SurrealDB как граф по `specs/kg/mapping.json` (`python -m surreal_convert.import_surreal …`) |
| `download.py` | Скачивание XML (в т.ч. `--discover`) |
| `scrape_opendata.py` | Поиск актуальных URL XML на странице opendata |
| `specs/xml/data-20160908-structure-20160713.xml` | Эталон структуры полей (схема для неизвестных тегов) |
| `data/` | Скачанные `.xml` (в git не коммитятся, см. `.gitignore`) |
| `out/` | Результаты конвертации (`.jsonl`, логи, `--report`) — каталог в git не коммитится |
| `tests/` | `pytest`, фикстуры в `tests/fixtures/` |
| `requirements.txt` | `lxml`, `requests`, `httpx`, `pytest`, `jsonschema`, `psycopg[binary]`, `pymysql`, `duckdb`, `surrealdb` |
| `Dockerfile` | Образ Python 3.12 с зависимостями проекта |
| `docker-compose.yml` | `converter` (основной), `surrealdb` (профиль `surreal`), `postgres` (профиль `sql`) |
| `AGENTS.md` | Краткий контекст для ИИ / нового чата |

## Откуда брать данные

Страница открытых данных:  
https://isga.obrnadzor.gov.ru/accredreestr/opendata/

Варианты:

1. **`python download.py --discover -o data/`** — найдёт ссылки и скачает **только последний снимок** (максимальная дата `data-YYYYMMDD-` в имени файла). Все версии: **`--discover --all-versions`**.
2. **`python scrape_opendata.py`** — те же URL в stdout (по умолчанию тоже только последний снимок); **`--all-versions`** — полный список; **`--json`** — JSON; **`-o файл`** — записать в файл.
3. Вручную: URL в **`download_urls.txt`** (или другой файл — **`download.py -c путь`**) либо аргументами **`download.py`**.

### Как устроен автопоиск (`scrape_opendata.py`)

Страница — SPA; строка **«Гиперссылки (URL) на версии набора данных»** — это **iframe** с HTML тем же endpoint, что  
`https://isga.obrnadzor.gov.ru/api/spa/accredreestr/perechen`.  
Скрипт тянет `app.*.js`, вытаскивает путь iframe, парсит `<a href="...xml">`.  
По умолчанию **`download.py --discover`** и **`scrape_opendata.py`** оставляют только файлы с **максимальной** датой в фрагменте имени `data-YYYYMMDD-` (один актуальный снимок); полный список версий — флаг **`--all-versions`**.

## Схема XML

Корень: `OpenData` → `Certificates` → `Certificate`. Коллекции: `Supplements`/`Supplement`, `Decisions`/`Decision`, `EducationalPrograms`/`EducationalProgram`; вложенность `ActualEducationOrganization`.  
В JSON каждая строка — **только поля сертификата** из XML (без имени исходного файла); при слиянии нескольких XML в один JSONL следите за уникальностью корневого `Id`.

**Решения без идентификатора документа:** если у `<Decision>` в выгрузке пустой `<Id/>`, в объекте решения поле **`Id`** становится **`null`**; при **компактном** JSON (по умолчанию **`omit_null_keys`**) ключ **`Id`** в таком элементе **может отсутствовать** — смысл тот же. Организация и свидетельство в строке JSONL **остаются**. При загрузке в SQL/DuckDB/Parquet по `specs/sql/mapping.json` строка в таблице **`decisions`** для такого элемента **не создаётся** (нужен непустой ключ документа); это не означает «нет организации», а означает «нет отдельной реляционной записи о документе без `Id` в источнике». Подробнее: [`docs/sql_convert.md`](docs/sql_convert.md), [`docs/knowledge_graph.md`](docs/knowledge_graph.md).

## Установка

Полный сценарий с активацией venv и pip — в разделе **[Быстрый старт](#быстрый-старт)** выше.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Нужен **Python 3.10+**.

## Скачивание (`download.py`)

```bash
python download.py --discover -o data/
python download.py --discover --all-versions -o data/   # все XML со страницы версий
python download.py --discover -o data/ --save-urls download_urls.txt
python download.py "https://..." "https://..." -o data/
python download.py   # без URL — читает download_urls.txt (по умолчанию; см. -c/--config)
```

Потоково по 1 МБ, опционально `Range` (отключить: **`--no-resume`**); при ошибке HTTP частичный файл удаляется.

## Конвертация (`convert.py`)

| Ситуация | Команда |
|----------|---------|
| Один XML, выход по умолчанию | `python convert.py data/file.xml` → `out/file.jsonl` |
| Один XML, свой путь | `python convert.py data/file.xml -o out/custom.jsonl` |
| Несколько XML → **отдельные** файлы | `python convert.py a.xml b.xml c.xml --out-dir out/` |
| Несколько XML → **один** файл | `python convert.py a.xml b.xml c.xml --merged -o out/all.jsonl` |
| **Полный снимок по статусу** (корневой `StatusName` и все `Supplements[]` как в XML) | `python convert.py data/file.xml -o out/full.jsonl --include-inactive` |
| **Включить записи с псевдорегионом «за пределами РФ»** (как в XML) | `python convert.py data/file.xml -o out/with_abroad.jsonl --include-outside-rf-region` |
| **Только с валидным `EduOrgOGRN`** на корне (цифры после очистки; см. `tools/audit_dataset_identity_fields.py`, блок `per_certificate.EduOrgOGRN`) | `python convert.py data/file.xml -o out/with_ogrn.jsonl --omit-invalid-eduorg-ogrn` |
| **JSON со всеми ключами, в т.ч. `null` и пустые `[]`/`{}`** (как сразу после парсера) | `python convert.py data/file.xml -o out/verbose.jsonl --include-null-keys` |
| **Без дозаполнения AEO/сертификата** (ИНН/ОГРН/КПП, подъём EduOrg*, «оболочки» supplement, ручной ОГРН→ИНН) | `python convert.py data/file.xml -o out/raw_aeo.jsonl --no-fill-aeo-coherent-inn-ogrn` |
| **Без ручного справочника ОГРН→ИНН** (по умолчанию читается `specs/certificate_inn_overrides_by_ogrn.json`, если есть) | `python convert.py data/file.xml -o out/no_ogrn_map.jsonl --no-certificate-inn-overrides-by-ogrn` |
| **Свой JSON ОГРН→ИНН** | `python convert.py data/file.xml -o out/custom.jsonl --certificate-inn-overrides-by-ogrn-json /path/to/map.json` |

По умолчанию в JSONL **не** попадают сертификаты с корневым **`StatusName`** из набора **«Недействующее»**, **«Прекращено»**, **«Лишен аккредитации»** (в отчёте **`omitted_inactive`** — число отсечённых строк); из **`Supplements[]`** перед записью **удаляются** элементы с **`StatusName`** из того же набора (счётчик **`stripped_supplements_by_status`** в **`--report`**). Полный снимок по статусу как в XML — **`--include-inactive`**. Также из **`Supplements[].EducationalPrograms[]`** удаляются дегенеративные «заглушки» (только `Id` без валидного `ProgrammCode`, `ProgrammName` и `EduLevelName`); счётчик в **`--report`**: **`total.stripped_degenerate_educational_programs`**. По умолчанию **не** попадают строки с корневым **`RegionName` «образовательные учреждения, находящиеся за пределами Российской Федерации»** (**`omitted_outside_rf_region`** в отчёте); полный снимок по региону — **`--include-outside-rf-region`**. Строки **без** валидного **`EduOrgOGRN`** по умолчанию **включаются**; для среза — **`--omit-invalid-eduorg-ogrn`** (**`omitted_invalid_eduorg_ogrn`**). По умолчанию в каждой строке **не пишутся** ключи с **`null`**, пустой строкой и пустыми вложенными **`{}`**/**`[]`**; «как в сыром дереве парсера» — **`--include-null-keys`**. Флаги **`--omit-inactive`**, **`--omit-outside-rf-region`**, **`--omit-null-keys`** избыточны (то же, что умолчание).

При включённом **`fill_aeo_coherent_inn_ogrn`** (по умолчанию): дозаполнение **INN**/**OGRN**/**KPP** в **`ActualEducationOrganization`** (корень и **`Supplements[]`**) из согласованных источников, ветка «филиал по `Id`», подъём **EduOrgINN**/**EduOrgOGRN** на **`Certificate`**, финальный проход по «пустым оболочкам» supplement AEO без цифровых ИНН/ОГРН; отдельно (если не **`--no-certificate-inn-overrides-by-ogrn`**) — ручной JSON **`specs/certificate_inn_overrides_by_ogrn.json`** (ОГРН→ИНН на корне сертификата и в корневой AEO). В отчёте **`--report`**: **`total.aeo_coherent_inn_ogrn_fills`**, **`certificate_EduOrg_inn_ogrn_backfill_from_near_aeo`**, **`certificate_INN_manual_override_by_OGRN_map`**, **`supplement_ActualEducationOrganization_degenerate_identity_shell_fill`**, **`omitted_certificate_personal_blocklist`** (срез по жёсткому списку **`Certificate.Id`** в коде — **`CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST`**). С **`--no-fill-aeo-coherent-inn-ogrn`** отключаются согласованные дозаполнения AEO, подъём **EduOrg*** и проход по «оболочкам»; ручной ОГРН→ИНН при этом **по-прежнему** применяется, если не указан **`--no-certificate-inn-overrides-by-ogrn`**.

При **нескольких** входах без `--merged` путь **`-o` указывать нельзя** (выходы только `out-dir/<имя>.jsonl`).  
Флаг **`--merged`** допустим **только** при двух и более входах.

**Логи:** отдельный файл только с **`--log-file путь`** (или перенаправление `2>файл.log` в shell); иначе сообщения идут в stderr.

Дополнительно:

```bash
python convert.py data/big.xml -o out/big.jsonl --progress-every 5000
python convert.py data/big.xml -o out/sample.jsonl --limit 1000
python convert.py data/big.xml -o out/big.jsonl --log-file logs/convert.log
python convert.py data/big.xml -o out/big.jsonl --report out/stats.json
python convert.py data/big.xml -o out/big.jsonl --strict
python convert.py data/big.xml -o out/with_abroad.jsonl --include-outside-rf-region
python convert.py data/big.xml -o out/with_ogrn.jsonl --omit-invalid-eduorg-ogrn
python convert.py data/big.xml -o out/verbose.jsonl --include-null-keys
```

Своя схема для проверки неизвестных тегов:

```bash
python convert.py input.xml -o out.jsonl --schema specs/xml/data-20160908-structure-20160713.xml
```

Полный снимок по статусу (в XML в т.ч. «Недействующее», «Прекращено», «Лишен аккредитации» на корне и те же статусы в `Supplements[]`), **без** среза по ИНН/ОГРН (в `convert.py` таких срезов нет; опционально только `--omit-invalid-eduorg-ogrn`):

```bash
python convert.py data/data-20260403-structure-20160713.xml \
  -o out/data-20260403-structure-20160713_full.jsonl \
  --include-inactive --include-outside-rf-region --include-null-keys --progress-every 50000
python tools/audit_dataset_identity_fields.py out/data-20260403-structure-20160713_full.jsonl \
  -o examples/dataset_identity_fields_audit_full.json
python tools/audit_dataset_status.py out/data-20260403-structure-20160713_full.jsonl -o examples/dataset_status_audit_full.json
python tools/audit_dataset_region.py out/data-20260403-structure-20160713_full.jsonl -o examples/dataset_region_audit_full.json
```

## Справочник уникальных программ (`tools/extract_unique_educational_programs.py`)

Один проход по JSONL сертификатов (обычно выход `convert.py` **по умолчанию** — без «Недействующее»; для всех статусов добавьте **`--include-inactive`** при конвертации): уникальные `EducationalProgram` (дедуп по полям без `Id`), фильтр по непустому **`UGSName`**. **`Qualification`** в выгрузке ИС ГА часто пустая (в т.ч. для СПО **09.02.07**) — по умолчанию такие строки **включаются** в справочник; флаг **`--require-qualification`** возвращает отбор только с непустой квалификацией. Канонизация хвоста `Qualification` для строк; выход **отсортирован по убыванию длины `Qualification`**, при равенстве — по **`ProgrammCode`** (стандартный **`XX.XX.XX`** — по трём числам), затем **`UGSCode`** так же, затем имя программы и стабильный отпечаток.

```bash
python tools/extract_unique_educational_programs.py out/data-*-structure-*.jsonl \
  -o examples/educational_programs_unique.jsonl
# Контроль: типичная СПО-строка с пустым Qualification — ProgrammCode 09.02.07 (поиск: rg '09\.02\.07' examples/educational_programs_unique.jsonl).
# только с непустой квалификацией (старый режим):
python tools/extract_unique_educational_programs.py out/data.jsonl -o out/nom.jsonl --require-qualification
```

## Импорт в SQL (`sql_convert`)

После конвертации в JSONL — загрузка в **SQLite**, **PostgreSQL** или **MySQL** по `specs/sql/mapping.json`:

```bash
python -m sql_convert.import_sql out/data.jsonl --sqlite data/accred.db --recreate
python -m sql_convert.import_sql out/data.jsonl --postgres "postgresql://user:pass@localhost:5432/db" --recreate
python -m sql_convert.import_sql out/data.jsonl --mysql "mysql://user:pass@localhost:3306/db" --recreate
```

Подробности и опции — в [`docs/sql_convert.md`](docs/sql_convert.md) (PK по таблицам, `program_slot`, политика `decisions`).

## Импорт в DuckDB и Parquet (`parquet_convert`)

Та же нормализация по `specs/sql/mapping.json`, что и для SQL — в **DuckDB** (файл `.duckdb`) и при необходимости в набор **`.parquet`** (по одному файлу на таблицу):

```bash
python -m parquet_convert.import_duckdb out/data.jsonl --duckdb data/warehouse.duckdb --recreate
python -m parquet_convert.import_duckdb out/data.jsonl --parquet-dir out/parquet --recreate
```

Подробности — в [`docs/parquet_duckdb.md`](docs/parquet_duckdb.md).

## Импорт в SurrealDB (`surreal_convert`)

JSONL → граф в **SurrealDB** по `specs/kg/mapping.json` (7 видов узлов, 7 видов рёбер). Импорт идемпотентен: рёбра хранятся через `UPSERT` с детерминированным ключом.

```bash
# Локально (нужен SurrealDB на ws://localhost:8000)
python -m surreal_convert.import_surreal out/data.jsonl --recreate

# Через Docker: запустить SurrealDB как compose-сервис и импортировать
docker compose --profile surreal up -d surrealdb
docker compose run --rm converter \
  python -m surreal_convert.import_surreal out/data.jsonl \
  --url ws://surrealdb:8000 --recreate
```

Опции: `--url` (по умолчанию `ws://localhost:8000`), `--ns` (`accred`), `--db` (`accred`), `--user`, `--password`, `--batch N`, `--limit N`, `--recreate` (удалить таблицы перед загрузкой), `--mapping` (свой путь к `mapping.json`).

## Граф-вьювер (`viewer`)

Интерактивный браузер графа: поиск организации → раскрытие связей (Cytoscape.js). Требует заполненной SurrealDB.

```bash
# Запустить весь стек: SurrealDB + FastAPI + React/Vite
docker compose --profile viewer up -d

# Импортировать JSONL локально (venv активирован)
python -m surreal_convert.import_surreal out/data.jsonl --url ws://127.0.0.1:8000 --recreate

# Открыть в браузере: http://127.0.0.1:8020
```

`BIND_IP` в `.env` управляет адресом биндинга всех портов (по умолчанию `127.2.0.1`). Для WSL2 с `networkingMode=mirrored` → установить `127.0.0.1`.

| Сервис | Порт | Описание |
|--------|------|----------|
| SurrealDB | 8000 | граф-база данных |
| API | 8010 | FastAPI: `/api/search`, `/api/expand`, `/api/health` |
| Web | 8020 | React + Cytoscape.js |

## Обработка «грязных» данных и провенанс (`_derived`)

- Нормализация пробелов и невидимых символов (`clean_text`), `ensure_json_safe` перед `json.dumps`.
- **`ProgrammCode`**, **`UGSCode`**: старый формат из шести цифр подряд (например `031501`, `090000`) приводится к виду **`XX.XX.XX`**; уже разделённые точками значения не меняются.
- **`Qualification`**: плейсхолдер **`0`** в XML → **`null`** в JSON. Полный обзор похожих скаляров по файлу: **`python tools/scan_jsonl_placeholder_scalars.py путь.jsonl`** (см. `--help`, **`--limit`**).
- **`_derived`**: все вычисленные и дозаполненные поля хранятся в `obj["_derived"]`, не мутируя оригинальные XML-значения. Наличие поля в `_derived` — сигнал о проблеме в исходном датасете.

| Уровень | `_derived`-поле | Означает |
|---------|-----------------|---------|
| `Certificate` | `EduOrgINN` / `EduOrgOGRN` | не заполнено в XML, взято из AEO |
| `Certificate` | `HasBranchSupplements` | есть приложения на филиалы |
| `Supplement` | `IsBranchSupplement` | приложение относится к филиалу |
| `ActualEducationOrganization` | `INN` / `OGRN` / `KPP` | отсутствовали в карточке АО |
| `EducationalProgram` | `EduLevelName` | пустой или нестандартный уровень |
- **Даты:** распространённые форматы; таймзона (`Z`, `±HH:MM`, при наличии `:` в строке — ещё `±HH`, `±HHMM`, напр. `2010-06-18 00:00:00+04`). Успех → строка **`YYYY-MM-DD`**; иначе в JSON остаётся **очищенная строка** + `WARNING`.
- **Булевы:** не распознано → **`null`** + `WARNING`.
- **ИНН/КПП/ОГРН:** после очистки не только цифры → **`null`** (при компактном JSON ключ обычно отсутствует); в отчёте `non_digit_ids`; детали в логе только на уровне **DEBUG**.
- Пустые маркеры → `null`; битая запись → `skipped`, при `--strict` — остановка.

## Пример строки JSONL

```json
{"Id":"123","IsFederal":true,"Supplements":[],"Decisions":[]}
```

## Knowledge Graph, SQL, DuckDB/Parquet, Prisma и JSON Schema

Для **графа** (property graph, RDF, Datalog как EDB):

- [`specs/kg/mapping.json`](specs/kg/mapping.json);
- [`docs/knowledge_graph.md`](docs/knowledge_graph.md).

Для **Neo4j (Cypher)** по тому же KG-mapping:

- [`docs/cypher_export.md`](docs/cypher_export.md);
- **`python -m cypher_convert.export_cypher`** — JSONL → файл `.cypher`.

Для **SurrealDB** (граф, по тому же KG-mapping):

- [`docs/surreal_convert.md`](docs/surreal_convert.md);
- [`surreal_convert/import_surreal.py`](surreal_convert/import_surreal.py);
- **`python -m surreal_convert.import_surreal`** — JSONL → SurrealDB, UPSERT-узлы и рёбра с детерминированным ключом (идемпотентно).

Для **реляционной** загрузки (PostgreSQL и аналоги):

- [`specs/sql/mapping.json`](specs/sql/mapping.json);
- [`docs/sql_convert.md`](docs/sql_convert.md).

Для **DuckDB** и колоночных файлов **Parquet** (та же схема таблиц):

- [`docs/parquet_duckdb.md`](docs/parquet_duckdb.md).

Для **Prisma ORM** (клиент по той же схеме, что и SQL):

- [`specs/prisma/mapping.json`](specs/prisma/mapping.json), [`specs/prisma/schema.prisma`](specs/prisma/schema.prisma);
- перегенерация: **`python tools/generate_prisma_schema.py`**;
- [`docs/prisma.md`](docs/prisma.md).

Для **валидации** структуры одной строки JSONL (IDE, CI, внешние пайплайны):

- [`specs/json-schema/certificate-line.schema.json`](specs/json-schema/certificate-line.schema.json);
- [`docs/json_schema.md`](docs/json_schema.md);
- перегенерация: **`python tools/generate_json_schema.py`**.

Карты KG/SQL/Prisma, экспорт Cypher и схема JSON описывают одну модель данных; при изменении конвертера обновляйте их согласованно. Импорт в DuckDB/Parquet использует тот же SQL-mapping.

## Работа с результатом

После **`--merged -o out/merged.jsonl`**:

```bash
jq -c 'select(.RegionName=="г. Москва")' out/merged.jsonl | head
```

```python
import pandas as pd
df = pd.read_json("out/merged.jsonl", lines=True)
```

```sql
SELECT Id, count(*) FROM read_json_auto('out/merged.jsonl') GROUP BY 1;
```
(DuckDB / аналог)

## Тесты

```bash
pytest
```

Долгий тест: `RUN_SLOW=1 pytest -k streaming`.

Импорт **живой** подвыборки в SQLite (нужен файл `out/sample_live_5000.jsonl`, см. [`docs/parquet_duckdb.md`](docs/parquet_duckdb.md)):

```bash
ACCRED_SQL_LIVE_SAMPLE=1 pytest tests/test_import_sql_live_sample.py -q
```

Экспорт **Parquet** по той же подвыборке (in-memory DuckDB, первые **100** непустых строк файла — см. `tests/test_import_parquet_live_sample.py`):

```bash
ACCRED_PARQUET_LIVE_SAMPLE=1 pytest tests/test_import_parquet_live_sample.py -q
```

Живой импорт в **SurrealDB** (нужен SurrealDB на `ws://localhost:8000`):

```bash
ACCRED_SURREAL_LIVE=1 pytest tests/test_import_surreal.py -q
# Свой URL: ACCRED_SURREAL_URL=ws://localhost:8000 ACCRED_SURREAL_LIVE=1 pytest tests/test_import_surreal.py -q
```
