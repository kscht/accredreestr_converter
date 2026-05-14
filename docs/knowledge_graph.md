# Knowledge Graph из JSONL

Материал для генерации **графа знаний** (property graph, RDF, Datalog как EDB): какие **сущности** и **связи** вытекают из одной строки JSONL и как строить стабильные идентификаторы.

## Исходные данные

- Одна строка JSONL = один объект **свидетельства** (логически «корень» — поля верхнего уровня, как в XML `Certificate`).
- **`_source_file`** — имя XML-выгрузки; включайте в URI или в свойства узла для **провенанса** и различения снимков реестра.
- По умолчанию в JSONL **не попадают** сертификаты со **`StatusName` «Недействующее»** на корне; для графа по **полному** снимку реестра используйте JSONL, собранный с **`convert.py --include-inactive`** (см. [`README`](../README.md)).
- Реляционный импорт и Prisma/DuckDB используют [`specs/sql/mapping.json`](../specs/sql/mapping.json): там зафиксированы PK (в т.ч. **`program_slot`** для строк программы, см. [`sql_convert.md`](sql_convert.md)).

## Машиночитаемая карта

Файл **[`../specs/kg/mapping.json`](../specs/kg/mapping.json)** задаёт:

- виды узлов (`Certificate`, `Supplement`, `Decision`, `EducationalProgram`, `EducationalLevel`, `Region`, `ActualEducationOrganization`);
- шаблоны глобальных `id` (`urn:accred:v1:…`);
- группы скалярных полей, которые логично повесить как **атрибуты** на соответствующий узел;
- виды рёбер (`hasSupplement`, `hasDecision`, …) и откуда они берутся в JSON.

Импортёр читает JSONL построчно, для каждой строки создаёт узлы и рёбра по этой схеме.

## RDF (по желанию)

Шаблоны `urn:accred:v1:…` можно трактовать как **IRI** субъектов/объектов. Литералы — из скалярных полей; тип XSD для дат — по возможности после нормализации (`xsd:date`), иначе `xsd:string`. Предикаты вынесите в свой словарь (например, префикс `accred:`), имена предикатов можно согласовать с `edge_kinds.predicate` в `mapping.json`.

## Property graph (Neo4j, Kuzu, JanusGraph, …)

- **Метки узлов** = `node_kinds.kind` (в т.ч. `EducationalLevel` для `EduLevelName` программ, `Region` для `RegionName` сертификата и ОО).
- **Рёбра** = `edge_kinds.predicate` (или короткие имена без конфликтов).
- Свойства — из `scalar_property_groups` для соответствующего `kind`; ключи JSON сохраняйте как имена свойств или нормализуйте в snake_case.

## Важные ограничения

1. **Поле `Id` повторяется** в разных вложенных объектах (свидетельство, приложение, решение, программа, ОО). Глобальный идентификатор узла **нельзя** строить только из `Id` — в `mapping.json` шаблоны это учитывают (цепочка родительских ключей + `_source_file`).
2. **Дублирование организации**: на корне сертификата есть плоские `EduOrg*` и отдельно вложенный **`ActualEducationOrganization`** — в аналитике это может быть один реальный субъект или два представления; правило слияния задаётся вами (например, связь `ALIAS_ORG` при совпадении ИНН после очистки). **Разные `Id` у `ActualEducationOrganization` на корне и внутри `Supplements[]`** в одной строке JSONL в типичном случае означают, что во вложенной карточке указана **отдельная ОО (часто филиал)**, а на корне — головная/основная организация; дополнительно используйте поле `IsBranch` в выгрузке.
3. **Грязные идентификаторы** в JSON остаются строками — для `same_as` по ИНН/ОГРН нужна **нормализация** на стороне импорта.
4. **Узел `Decision` и пустой `Decisions[].Id`**: шаблон `urn:…:Decision:…:{Decision.Id}` требует непустого идентификатора документа. Если `Id` у элемента решения пустой, **узел Decision и ребро `hasDecision` для этой позиции строить нельзя** (нет устойчивого IRI), при этом **узел `Certificate` и организация** из той же строки JSONL остаются валидными. Импорт в SQL/DuckDB по репозиторию в таких случаях **не создаёт строку в таблице `decisions`**, но **не отклоняет** сертификат целиком.
5. **`EducationalProgram`**: в шаблоне URI участвует **`program_slot`** (индекс в `EducationalPrograms[]` внутри данного приложения) вместе с `EducationalProgram.Id`, потому что идентификатор программы в реестре может повторяться для разных периодов аккредитации.

## Связь с подписями полей

Русские подписи из паспорта набора — в **`specs/field_labels.json`** (пути вида `Certificate/…`). Их можно подвесить как `rdfs:label` / свойство `ui_label` на предикатах или свойствах графа.

## Параллельно: SQL, Prisma и DuckDB/Parquet

Та же декомпозиция строки описана для реляционной загрузки: [`specs/sql/mapping.json`](../specs/sql/mapping.json), [`sql_convert.md`](sql_convert.md). Схема Prisma генерируется из того же SQL-mapping: [`specs/prisma/mapping.json`](../specs/prisma/mapping.json), [`prisma.md`](prisma.md). Для DuckDB и Parquet — [`parquet_duckdb.md`](parquet_duckdb.md). Для проверки формы JSON — [`specs/json-schema/certificate-line.schema.json`](../specs/json-schema/certificate-line.schema.json), [`json_schema.md`](json_schema.md). Для **Cypher**: Neo4j напрямую; **Kuzu** — встраиваемый движок с подмножеством Cypher, нужна предварительная схема и учёт отличий от Neo4j ([`cypher_export.md`](cypher_export.md)). Модуль: `cypher_convert.export_cypher`.

## Диаграммы

Черновики и экспорт схем пайплайна (Mermaid, изображения) — в **[`diagrams/`](diagrams/)**. Реляционная схема БД по SQL-mapping: **[`diagrams/sql_schema_er.md`](diagrams/sql_schema_er.md)** (Mermaid `erDiagram`, рендер на GitHub).
