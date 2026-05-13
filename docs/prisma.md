# Prisma ORM

Материал для **Prisma Client** по той же реляционной проекции, что и SQL-импорт: таблицы, составные ключи и связи.

## Машиночитаемая карта

- **[`../specs/sql/mapping.json`](../specs/sql/mapping.json)** — каноническая схема таблиц, PK, FK (как для `sql_convert`).
- **[`../specs/prisma/mapping.json`](../specs/prisma/mapping.json)** — метаданные генерации: `provider`, имя `env` для URL, соответствие **имя таблицы → имя модели Prisma**, имена связей для двух путей `ActualEducationOrganization` → `Certificate` / `Supplement`.

## Генерация `schema.prisma`

Из корня репозитория:

```bash
python tools/generate_prisma_schema.py
```

По умолчанию читаются `specs/sql/mapping.json`, `specs/prisma/mapping.json`, результат пишется в **`specs/prisma/schema.prisma`**. После правок **`specs/sql/mapping.json`** перегенерируйте схему той же командой.

Опции: `--sql-mapping`, `--prisma-config`, `-o` / `--output`.

## Datasource

В сгенерированном файле указано `env("DATABASE_URL")`. Для проверки схемы без реальной БД:

```bash
DATABASE_URL="postgresql://user:pass@127.0.0.1:5432/dbname" npx prisma validate --schema=specs/prisma/schema.prisma
```

## Ограничения

- Типы **DATE** и «грязные» строки в SQL отражены как **`String @db.Text`**, как в консервативной политике `specs/sql/mapping.json`.
- Колонка **`program_slot`** в `EducationalProgram` — **`Int`** (составной PK вместе с файлами выгрузки и приложением); **`program_id`** — **`String?`** (идентификатор программы в реестре, может повторяться между строками).
- Две связи **`ActualEducationOrganization`** → сертификат и → приложение разведены именами релейшенов (`AeoViaCertificate`, `AeoViaSupplement`); частичная семантика FK на стороне SQL см. [`sql_convert.md`](sql_convert.md).
- Модель **`Decision`** соответствует только элементам `Decisions[]` с **непустым** `Id` в JSONL: иначе в источнике нет ключа документа, строка в `decisions` не создаётся при импорте, **`Certificate` при этом не отбрасывается** (см. [`sql_convert.md`](sql_convert.md)).

## Связь с KG и JSON Schema

Та же логика сущностей, что в [`specs/kg/mapping.json`](../specs/kg/mapping.json) и в [`specs/json-schema/certificate-line.schema.json`](../specs/json-schema/certificate-line.schema.json): при изменении структуры JSONL согласуйте `specs/sql/mapping.json`, затем перегенерируйте Prisma.
