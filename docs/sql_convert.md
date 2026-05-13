# Импорт JSONL в SQL

Материал для **нормализованной** загрузки строк JSONL в реляционную СУБД (ориентир **PostgreSQL**): таблицы, ключи, откуда брать поля.

## Машиночитаемая карта

Файл **[`../specs/sql/mapping.json`](../specs/sql/mapping.json)** описывает:

- таблицы `certificates`, `supplements`, `decisions`, `educational_programs`, `actual_education_organizations`;
- составные **первичные ключи** (всегда участвуют `source_file` + `certificate_id`, где `certificate_id` — значение JSON `Id` корня строки);
- **внешние ключи** и каскады;
- соответствие **колонка SQL** ↔ **`from_json`** (имя ключа в объекте после разбора конвертером).

Импортёр: одна строка JSONL → `INSERT`/`COPY` в `certificates` + дочерние строки по массивам и вложенному объекту.

Тот же файл служит источником для **Prisma** (`python tools/generate_prisma_schema.py`, см. [`prisma.md`](prisma.md)).

## Важные детали JSON (как в `convert.py`)

- Массив **`Supplements`** — это список **объектов полей приложения** (без лишней обёртки с ключом `Supplement` в JSON).
- Аналогично **`Decisions`** и **`EducationalPrograms`** внутри приложения.
- **`ActualEducationOrganization`**: либо один объект на корне сертификата, либо внутри элемента `Supplements[]` — в SQL это одна таблица с полем **`ae_scope`** (`certificate` | `supplement`) и **`supplement_id`** (NULL, если карточка относится к корню сертификата).

## Первичный ключ и дубликаты

Составной ключ `(source_file, certificate_id)` однозначно привязывает запись к **конкретной выгрузке** и **Id в XML**. При повторной загрузке того же файла используйте **`ON CONFLICT DO UPDATE`** или сначала удалите строки с этим `source_file`.

## Типы и «грязные» даты

В `mapping.json` для дат указан `DATE`. Если в JSON после конвертера осталась **не-ISO** строка, при загрузке либо кладите в **TEXT**, либо добавьте колонки `*_raw`, либо нормализуйте в ETL до `DATE`.

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
- **`--limit N`** — обработать только первые N строк JSONL (отладка).

Для PostgreSQL нужен пакет **`psycopg[binary]`**, для MySQL — **`pymysql`** (см. `requirements.txt`). Опциональные интеграционные тесты: **`ACCRED_PG_TEST_DSN`**, **`ACCRED_MYSQL_TEST_DSN`**, затем `pytest` (см. `tests/test_import_sql.py`).
