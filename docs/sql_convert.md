# Импорт JSONL в SQL

Материал для **нормализованной** загрузки строк JSONL в реляционную СУБД (ориентир **PostgreSQL**): таблицы, ключи, откуда брать поля.

## Машиночитаемая карта

Файл **[`../specs/sql/mapping.json`](../specs/sql/mapping.json)** описывает:

- таблицы `certificates`, `supplements`, `decisions`, `educational_programs`, `actual_education_organizations`;
- составные **первичные ключи** (всегда участвуют `source_file` + `certificate_id`, где `certificate_id` — значение JSON `Id` корня строки);
- **внешние ключи** и каскады;
- соответствие **колонка SQL** ↔ **`from_json`** (имя ключа в объекте после разбора конвертером).

Импортёр: одна строка JSONL → `INSERT`/`COPY` в `certificates` + дочерние строки по массивам и вложенному объекту.

Тот же файл служит источником для **Prisma** (`python tools/generate_prisma_schema.py`, см. [`prisma.md`](prisma.md)) и для **DuckDB / Parquet** (`python -m parquet_convert.import_duckdb`, см. [`parquet_duckdb.md`](parquet_duckdb.md)).

## Важные детали JSON (как в `convert.py`)

- Массив **`Supplements`** — это список **объектов полей приложения** (без лишней обёртки с ключом `Supplement` в JSON).
- Массив **`Decisions`** — список объектов решений (как в XML). **Свидетельство и организация** по строке JSONL **не отбрасываются**: в `certificates` (и остальные дочерние таблицы по маппингу) попадают как обычно.
- Строка в таблице **`decisions`** создаётся **только если** у элемента `Decisions[]` есть **непустой** **`Id`** — это идентификатор распорядительного документа в выгрузке и часть составного PK. Если в XML пустой `<Id/>` у решения, в JSON будет `Id: null`: в данных **нет стабильной ссылки на документ** (в т.ч. при «утерянном» документе в смысле реестра). Такой элемент **не вставляется** в `decisions` — это **не** утверждение, что организации нет; просто **отдельную сущность «документ»** в реляционной схеме без ключа хранить нельзя. Остальные поля того же объекта в JSONL по-прежнему доступны в исходной строке.
- Массив **`EducationalPrograms`** внутри каждого приложения — список объектов полей программы (без лишней обёртки с ключом `EducationalProgram` в JSON). В таблице **`educational_programs`** первичный ключ включает **`program_slot`** — порядковый индекс элемента в этом массиве (0, 1, …): идентификатор программы в реестре (**`program_id`**, JSON `Id`) **может повторяться** для разных периодов/строк выгрузки, это не ошибка данных.
- **`ActualEducationOrganization`**: либо один объект на корне сертификата, либо внутри элемента `Supplements[]` — в SQL это одна таблица с полем **`ae_scope`** (`certificate` | `supplement`) и **`supplement_id`** (NULL, если карточка относится к корню сертификата). Если **`Id`** в карточке на корне и **`Id`** в карточке внутри приложения **различаются**, в смысле реестра это обычно трактуется как **филиал** (приложение относится к отдельной ОО, на корне — головная/основная организация); дополнительно смотрите булево **`IsBranch`** в XML/JSON.

## Первичный ключ и дубликаты

Составной ключ `(source_file, certificate_id)` для **`certificates`** привязывает запись к **конкретной выгрузке** и **Id свидетельства в XML**. Дочерние таблицы расширяют этот префикс своими полями; полный перечень PK задан в [`specs/sql/mapping.json`](../specs/sql/mapping.json):

| Таблица | Первичный ключ (колонки) |
|---------|--------------------------|
| `certificates` | `source_file`, `certificate_id` |
| `supplements` | `source_file`, `certificate_id`, `supplement_id` |
| `decisions` | `source_file`, `certificate_id`, `decision_id` |
| `educational_programs` | `source_file`, `certificate_id`, `supplement_id`, **`program_slot`** |
| `actual_education_organizations` | `source_file`, `certificate_id`, `ae_scope`, `supplement_id`, `aeo_id` |

**`program_slot`** в JSONL **нет**: при импорте задаётся как **индекс** (0, 1, …) элемента в массиве `EducationalPrograms[]` внутри данного элемента `Supplements[]`. Колонка **`program_id`** хранит реестровый `Id` программы и **может повторяться** в нескольких строках таблицы.

При повторной загрузке того же файла используйте **`ON CONFLICT DO UPDATE`** или сначала удалите строки с этим `source_file`.

## Типы и «грязные» даты

В `mapping.json` для дат указан `DATE`. Если в JSON после конвертера осталась **не-ISO** строка, при загрузке либо кладите в **TEXT**, либо добавьте колонки `*_raw`, либо нормализуйте в ETL до `DATE`. Тип **`INTEGER`** используется для **`program_slot`** в `educational_programs` (см. раздел выше).

Булевы и числовые идентификаторы — см. раздел **«Обработка грязных данных»** в [`README.md`](../README.md).

## Ограничение по FK для `actual_education_organizations`

Вторая ссылка в `mapping.json` ведёт на `supplements`. В PostgreSQL при **`supplement_id` IS NULL** проверка внешнего ключа на родительскую строку **не требуется** (NULL в FK). Строки с `ae_scope = supplement` должны иметь непустой `supplement_id`, совпадающий с `supplements.supplement_id`.

## Связь с Knowledge Graph и JSON Schema

Та же декомпозиция сущностей, что в [`specs/kg/mapping.json`](../specs/kg/mapping.json): граф и SQL — два представления одной логики; при изменении структуры JSONL правьте оба mapping согласованно. Форма одной строки JSON — [`certificate-line.schema.json`](../specs/json-schema/certificate-line.schema.json), см. [`json_schema.md`](json_schema.md).

## Подписи колонок для UI

Русские подписи из паспорта набора — в [`specs/field_labels.json`](../specs/field_labels.json) (пути `Certificate/…`); для SQL можно сгенерировать view с комментариями `COMMENT ON COLUMN` по этому словарю.

## CLI-импортёр (`sql_convert/import_sql.py`)

Из корня репозитория (с активированным venv):

```bash
python -m sql_convert.import_sql out/data.jsonl --sqlite data/accred.db --recreate
python -m sql_convert.import_sql out/data.jsonl --postgres "postgresql://user:pass@localhost:5432/dbname" --recreate
python -m sql_convert.import_sql out/data.jsonl --mysql "mysql://user:pass@localhost:3306/dbname" --recreate
python -m sql_convert.import_sql out/data.jsonl --sql-out out/dump.sql --sql-dialect mysql --recreate
```

Тот же [`specs/sql/mapping.json`](../specs/sql/mapping.json) используется для всех целей: для MySQL DDL строится с обратными кавычками вокруг имён, `ENGINE=InnoDB`, `utf8mb4`; булевы колонки — `TINYINT(1)`.

- **`--recreate`** — выполнить `DROP TABLE …` (для PostgreSQL с `CASCADE`) и `CREATE TABLE` по [`specs/sql/mapping.json`](../specs/sql/mapping.json), затем импорт. Без флага таблицы должны уже существовать с той же схемой.
- **`--mapping`** — другой файл mapping (по умолчанию `specs/sql/mapping.json` в репозитории).
- **`--limit N`** — не более **N непустых** строк JSONL (счётчик по входу; ошибки импорта тоже расходуют лимит).

Для PostgreSQL нужен пакет **`psycopg[binary]`**, для MySQL — **`pymysql`** (см. `requirements.txt`). Опциональные интеграционные тесты: **`ACCRED_PG_TEST_DSN`**, **`ACCRED_MYSQL_TEST_DSN`**, затем `pytest` (см. `tests/test_import_sql.py`).
