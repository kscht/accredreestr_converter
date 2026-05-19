# Импорт в SurrealDB (`surreal_convert`)

CLI читает **JSONL** (выход **`convert.py`**) и импортирует граф в **SurrealDB** по **[`../specs/kg/mapping.json`](../specs/kg/mapping.json)** — те же 7 видов узлов и 7 видов рёбер, что и для Cypher/Neo4j, но через нативную graph-модель SurrealDB (таблицы-узлы и таблицы-рёбра `UPSERT`).

## Запуск

Из корня репозитория (с активированным venv):

```bash
# Локально — нужен SurrealDB на http://localhost:8000
python -m surreal_convert.import_surreal out/data.jsonl --recreate
python -m surreal_convert.import_surreal out/data.jsonl --limit 100 --recreate

# Тонкая настройка скорости (больше батч + больше воркеров)
python -m surreal_convert.import_surreal out/data.jsonl --recreate --batch 1000 --workers 8
```

Через Docker Compose (`surrealdb` запускается с профилем `surreal`):

```bash
docker compose --profile surreal up -d surrealdb
docker compose run --rm converter \
  python -m surreal_convert.import_surreal out/data.jsonl \
  --url http://surrealdb:8000 --recreate
```

Основные опции:

| Опция | По умолчанию | Описание |
|-------|-------------|----------|
| `--url` | `http://localhost:8000` | HTTP(S) или WS(S) URL SurrealDB (`ws://` конвертируется в `http://`) |
| `--ns` | `accred` | Namespace |
| `--db` | `accred` | Database |
| `--user` | `root` | Имя пользователя |
| `--password` | `root` | Пароль |
| `--batch N` | `500` | Сертификатов на один HTTP-запрос |
| `--workers N` | `4` | Параллельных HTTP-запросов |
| `--limit N` | — | Не более N строк JSONL |
| `--recreate` | — | `REMOVE TABLE IF EXISTS` + CREATE вместо UPSERT (быстрее) |
| `--mapping` | `specs/kg/mapping.json` | Свой путь к KG-mapping |

Полный список: `python -m surreal_convert.import_surreal --help`.

## Производительность

Транспорт — **httpx async HTTP POST `/sql`** (параллельные батчи). При `--recreate`:
- используется **CREATE** вместо UPSERT — нет проверки существования записи, заметно быстрее;
- рекомендованный режим при полной пересборке базы (граф очищается перед каждым импортом).

Без `--recreate` используется UPSERT — поведение идемпотентно (повторный прогон обновляет значения).

## Схема графа

Узлы (таблицы SurrealDB):

| Таблица | Описание |
|---------|----------|
| `certificate` | Аккредитационный сертификат |
| `supplement` | Приложение к свидетельству |
| `decision` | Решение (Выдача, Аннулирование, …) |
| `educational_program` | Образовательная программа |
| `educational_level` | Уровень образования по ФЗ-273 |
| `region` | Регион (из `RegionName`) |
| `actual_education_organization` | Фактическая ОО (корень + supplement) |

Рёбра (edge-таблицы SurrealDB):

| Таблица | Направление |
|---------|-------------|
| `has_supplement` | `certificate` → `supplement` |
| `has_decision` | `certificate` → `decision` |
| `has_educational_program` | `supplement` → `educational_program` |
| `has_education_level` | `educational_program` → `educational_level` |
| `offers_education_level` | `actual_education_organization` → `educational_level` |
| `in_region` | `certificate` / `actual_education_organization` → `region` |
| `has_actual_education_organization` | `certificate` / `supplement` → `actual_education_organization` |

## Семантика

- Каждый узел и каждое ребро записываются через `UPSERT` — импорт **идемпотентен**: повторный прогон обновляет значения, не создаёт дубликатов.
- Ключи узлов — исходные идентификаторы JSONL (`Certificate.Id` и т.п.). Ключи рёбер — детерминированная конкатенация идентификаторов `in`/`out`.
- Каждый узел получает поле **`uri`** — стабильный `urn:accred:v1:<Kind>:<key>`, аналогичный Cypher-экспорту.
- Узел `region` мержится по SHA-256 UTF-8 от `RegionName` — одно имя = один узел независимо от числа сертификатов. То же для `educational_level`.
- `Decision` без непустого `Id` в JSONL **не создаётся** (нет устойчивого ключа) — как в SQL и Cypher.
- Скалярные поля из `scalar_property_groups` mapping попадают в `SET` с исходными JSON-именами, кроме `EduLevelName` (вынесено в `educational_level`) и `RegionName` (вынесено в `region`).

## Сравнение с Cypher (Neo4j)

| | SurrealDB | Neo4j (Cypher) |
|-|-----------|----------------|
| Узлы | `UPSERT table:\`key\` SET …` | `MERGE (n:Label {uri:…}) SET …` |
| Рёбра | `UPSERT edge:\`key\` SET in=…, out=…` | `MERGE (a)-[r:TYPE]->(b)` |
| Идемпотентность | детерминированный ключ записи | `MERGE` по `uri` |

Семантика узлов и набор свойств **идентичны** Cypher-экспорту.

## Примеры SurrealQL

```surql
-- Свидетельства конкретного региона
SELECT *, ->in_region->region.name AS region_name FROM certificate
WHERE ->in_region->region.name = "г. Москва";

-- Уровни образования, которые предлагает ОО
SELECT FullName, ->offers_education_level->educational_level.name AS levels
FROM actual_education_organization LIMIT 10;

-- Программы приложения
SELECT * FROM supplement WHERE ->has_actual_education_organization->actual_education_organization.INN = "7701234567";
```

## Связанные файлы

- [`knowledge_graph.md`](knowledge_graph.md) — общая логика графа (узлы, рёбра, `uri`, связи).
- [`cypher_export.md`](cypher_export.md) — Cypher/Neo4j: та же модель, другой синтаксис.
- [`../specs/kg/mapping.json`](../specs/kg/mapping.json) — JSON-описание узлов и рёбер.
- [`../surreal_convert/import_surreal.py`](../surreal_convert/import_surreal.py) — исходный код импортёра.
