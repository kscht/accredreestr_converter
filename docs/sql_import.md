# Импорт JSONL в SQL

Материал для **нормализованной** загрузки строк JSONL в реляционную СУБД (ориентир **PostgreSQL**): таблицы, ключи, откуда брать поля.

## Машиночитаемая карта

Файл **[`../sql/mapping.json`](../sql/mapping.json)** описывает:

- таблицы `certificates`, `supplements`, `decisions`, `educational_programs`, `actual_education_organizations`;
- составные **первичные ключи** (всегда участвуют `source_file` + `certificate_id`, где `certificate_id` — значение JSON `Id` корня строки);
- **внешние ключи** и каскады;
- соответствие **колонка SQL** ↔ **`from_json`** (имя ключа в объекте после разбора конвертером).

Импортёр: одна строка JSONL → `INSERT`/`COPY` в `certificates` + дочерние строки по массивам и вложенному объекту.

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

Та же декомпозиция сущностей, что в [`kg/mapping.json`](../kg/mapping.json): граф и SQL — два представления одной логики; при изменении структуры JSONL правьте оба mapping согласованно. Форма одной строки JSON — [`json-schema/certificate-line.schema.json`](../json-schema/certificate-line.schema.json), см. [`json_schema.md`](json_schema.md).

## Подписи колонок для UI

Русские подписи из паспорта набора — в [`field_labels.json`](../field_labels.json) (пути `Certificate/…`); для SQL можно сгенерировать view с комментариями `COMMENT ON COLUMN` по этому словарю.
