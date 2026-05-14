# Конвертер XML реестра аккредитации → JSONL

Потоковая конвертация выгрузок **ИС ГА** (Рособрнадзор) в **JSON Lines**: одна строка = один `<Certificate>`, UTF-8 без BOM.

**Контекст для ИИ-ассистента:** в корне лежит [`AGENTS.md`](AGENTS.md) — краткие правила, пути и CLI; удобно вставлять в начало промпта в новой сессии.

## Быстрый старт

От нуля до JSONL (Linux / macOS; в **Windows** вместо `source` выполните `.venv\Scripts\activate`):

```bash
git clone git@github.com:kscht/accredreestr_converter.git
cd accredreestr_converter

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1) Скрапер: записать URL последней выгрузки (data-YYYYMMDD-…) в download_urls.txt
python scrape_opendata.py -o download_urls.txt

# 2) Скачать XML в data/ по списку из файла
python download.py -o data/

# 3) Конвертация → out/<имя-xml>.jsonl (файл большой: десятки минут и сотни MB)
#    По умолчанию в JSONL не попадают сертификаты со StatusName «Недействующее» (см. отчёт omitted_inactive).
#    Полный снимок реестра — только с флагом: --include-inactive
mkdir -p out
python convert.py data/data-*-structure-*.xml \
  --progress-every 50000 \
  --report out/convert_report.json \
  --log-file out/convert.log
```

Короче, если не нужен отдельный шаг со **`download_urls.txt`**: шаги 1–2 можно заменить одной командой **`python download.py --discover -o data/`** (внутри вызывается тот же поиск URL, плюс сразу скачивание).

## Структура репозитория

- **`specs/`** — машиночитаемые артефакты: маппинги KG/SQL/Prisma, JSON Schema, эталонный XML структуры, `field_labels.json`.
- **`tools/`** — перегенерация (`generate_*`), случайные подвыборки JSONL, аналитика (`analyze_*`, `scan_*`), справочник программ (`extract_*`); см. таблицу ниже.
- **`docs/diagrams/`** — диаграммы (исходники и экспорт).
- **Корень** — основной CLI (`convert.py`, `download.py`, `scrape_opendata.py`), пакеты `sql_convert/`, `parquet_convert/`, `cypher_convert/`.

| Путь | Назначение |
|------|------------|
| `tools/generate_field_labels.py` | Генерация `specs/field_labels.json` из эталонной XML-схемы |
| `specs/field_labels.json` | Подписи полей для UI (`python tools/generate_field_labels.py`) |
| `convert.py` | Конвертация XML → JSONL, CLI |
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
| `tools/extract_unique_educational_programs.py` | Справочник уникальных `EducationalProgram` → `examples/educational_programs_unique.jsonl` (вход — JSONL из `convert.py`; сортировка по длине `Qualification` по убыванию, затем `UGSCode`) |
| `tools/scan_jsonl_placeholder_scalars.py` | Подсчёт скалярных плейсхолдеров в JSONL по путям (нули, тире, «н/д» и т.п.); см. `--help` |
| `docs/cypher_export.md` | JSONL → Cypher (Neo4j) по KG-mapping |
| `cypher_convert/export_cypher.py` | Экспорт `.cypher`: `python -m cypher_convert.export_cypher …` |
| `docs/sql_convert.md` | Пояснения к SQL: ключи, вложенность, типы |
| `docs/parquet_duckdb.md` | JSONL → DuckDB и Parquet |
| `docs/prisma.md` | Prisma: генерация schema, Datasource, ограничения |
| `docs/json_schema.md` | JSON Schema: проверка строк, ограничения |
| `sql_convert/import_sql.py` | Импорт JSONL в SQLite, PostgreSQL или MySQL (`python -m sql_convert.import_sql …`) |
| `sql_convert/sql_ddl.py` | DDL из `specs/sql/mapping.json` (в т.ч. диалект DuckDB) |
| `parquet_convert/import_duckdb.py` | Импорт JSONL в DuckDB и/или выгрузка таблиц в Parquet (`python -m parquet_convert.import_duckdb …`) |
| `download.py` | Скачивание XML (в т.ч. `--discover`) |
| `scrape_opendata.py` | Поиск актуальных URL XML на странице opendata |
| `specs/xml/data-20160908-structure-20160713.xml` | Эталон структуры полей (схема для неизвестных тегов) |
| `data/` | Скачанные `.xml` (в git не коммитятся, см. `.gitignore`) |
| `out/` | Результаты конвертации (`.jsonl`, логи, `--report`) — каталог в git не коммитится |
| `tests/` | `pytest`, фикстуры в `tests/fixtures/` |
| `requirements.txt` | `lxml`, `requests`, `pytest`, `jsonschema`, `psycopg[binary]`, `pymysql`, `duckdb` |
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

**Решения без идентификатора документа:** если у `<Decision>` в выгрузке пустой `<Id/>`, конвертер честно кладёт в JSON `Decisions[]` объект с `Id: null` (организация и свидетельство в строке **остаются**). При загрузке в SQL/DuckDB/Parquet по `specs/sql/mapping.json` строка в таблице **`decisions`** для такого элемента **не создаётся** (нужен непустой ключ документа); это не означает «нет организации», а означает «нет отдельной реляционной записи о документе без `Id` в источнике». Подробнее: [`docs/sql_convert.md`](docs/sql_convert.md), [`docs/knowledge_graph.md`](docs/knowledge_graph.md).

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
| **Все** статусы (в т.ч. «Недействующее») | `python convert.py data/file.xml -o out/full.jsonl --include-inactive` |
| Компактный JSON (без ключей с `null`/пустыми строками и пустых `{}`/`[]`) | `python convert.py data/file.xml -o out/c.jsonl --omit-null-keys` |

По умолчанию записи со **`StatusName` «Недействующее»** на корне сертификата **не попадают** в JSONL; в отчёте `--report` смотрите **`omitted_inactive`**. Для **полного** числа сертификатов из XML добавьте **`--include-inactive`** (тогда `omitted_inactive` будет **0**).

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
python convert.py data/big.xml -o out/full.jsonl --include-inactive
python convert.py data/big.xml -o out/compact.jsonl --omit-null-keys
```

Своя схема для проверки неизвестных тегов:

```bash
python convert.py input.xml -o out.jsonl --schema specs/xml/data-20160908-structure-20160713.xml
```

## Справочник уникальных программ (`tools/extract_unique_educational_programs.py`)

Один проход по JSONL сертификатов: уникальные `EducationalProgram` (дедуп по полям без `Id`), фильтр по непустому **`UGSName`**. **`Qualification`** в выгрузке ИС ГА часто пустая (в т.ч. для СПО **09.02.07**) — по умолчанию такие строки **включаются** в справочник; флаг **`--require-qualification`** возвращает отбор только с непустой квалификацией. Канонизация хвоста `Qualification` для строк; выход **отсортирован по убыванию длины `Qualification`**, при равенстве — по **`UGSCode`** и стабильному хвосту.

```bash
python tools/extract_unique_educational_programs.py out/data-*-structure-*.jsonl \
  -o examples/educational_programs_unique.jsonl
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

## Обработка «грязных» данных

- Нормализация пробелов и невидимых символов (`clean_text`), `ensure_json_safe` перед `json.dumps`.
- **`ProgrammCode`**, **`UGSCode`**: старый формат из шести цифр подряд (например `031501`, `090000`) приводится к виду **`XX.XX.XX`**; уже разделённые точками значения не меняются.
- **`Qualification`**: плейсхолдер **`0`** в XML → **`null`** в JSON. Полный обзор похожих скаляров по файлу: **`python tools/scan_jsonl_placeholder_scalars.py путь.jsonl`** (см. `--help`, **`--limit`**).
- **Даты:** распространённые форматы; таймзона (`Z`, `±HH:MM`, при наличии `:` в строке — ещё `±HH`, `±HHMM`, напр. `2010-06-18 00:00:00+04`). Успех → строка **`YYYY-MM-DD`**; иначе в JSON остаётся **очищенная строка** + `WARNING`.
- **Булевы:** не распознано → **`null`** + `WARNING`.
- **ИНН/КПП/ОГРН:** после очистки не только цифры → в JSON **строка** как есть + `WARNING`.
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
