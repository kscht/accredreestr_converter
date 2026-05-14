# Экспорт в Cypher (Neo4j, Kuzu и др.)

CLI читает **JSONL** (выход **`convert.py`**, по умолчанию компактные строки) и пишет файл **`.cypher`**: операторы `MERGE` для узлов и рёбер по **[`../specs/kg/mapping.json`](../specs/kg/mapping.json)** (те же метки узлов, что в `node_kinds.kind`, и типы рёбер в верхнем регистре, см. ниже).

## Запуск

Из корня репозитория (с активированным venv):

```bash
python -m cypher_convert.export_cypher out/data.jsonl -o out/graph.cypher
python -m cypher_convert.export_cypher out/data.jsonl -o out/sample.cypher --limit 100
python -m cypher_convert.export_cypher out/data.jsonl -o out/graph.cypher --mapping specs/kg/mapping.json
python -m cypher_convert.export_cypher out/data.jsonl -o out/graph.cypher --semicolon
```

- **`--mapping`** — другой KG-mapping (по умолчанию `specs/kg/mapping.json`).
- **`--limit N`** — не более **N** непустых строк JSONL (счётчик по входу, как в `sql_convert`).
- **`--clear-graph`** — в **начало** файла добавить `MATCH (n) DETACH DELETE n;` (полное удаление узлов и связей в **текущей** базе Neo4j перед загрузкой; опасно на общей БД).

Готовый небольшой файл для просмотра схемы в Neo4j: **[`../examples/accred_graph_preview.cypher`](../examples/accred_graph_preview.cypher)** (одна строка из живой выгрузки, в начале — очистка графа, далее `--semicolon`). Перегенерация из корня:

```bash
head -n 1 out/sample_live_5000.jsonl > examples/_tmp_one.jsonl
python -m cypher_convert.export_cypher examples/_tmp_one.jsonl -o examples/accred_graph_preview.cypher --limit 1 --semicolon --clear-graph
rm examples/_tmp_one.jsonl
```

## Семантика

- Узлы сопоставляются по свойству **`uri`** — подстановка `id_template` из mapping (как в [`knowledge_graph.md`](knowledge_graph.md)).
- Решения **`Decision`** без непустого `Id` в JSON **не** создаются (нет устойчивого URI).
- **`EducationalProgram`**: в URI участвует **`program_slot`** (индекс в `EducationalPrograms[]`), как в SQL-mapping.
- Узел **`Region`**: непустой **`RegionName`** с корня сертификата или с **`ActualEducationOrganization`** — `MERGE` по **`uri`** = `urn:accred:v1:Region:<SHA-256 UTF-8 текста>`, свойство **`name`**. На **`Certificate`** и на **`ActualEducationOrganization`** поле `RegionName` в Cypher **не** выставляется; **`OGRN`**, **`INN`** и прочие поля карточки ОО остаются на узле **`ActualEducationOrganization`** (идентификатор узла по-прежнему по шаблону AEO из mapping, не по ОГРН).
- Рёбра **`IN_REGION`**: `Certificate` → `Region`, `ActualEducationOrganization` → `Region`.
- Рёбра **`HAS_EDUCATION_LEVEL`**: `EducationalProgram` → `EducationalLevel`. **`OFFERS_EDUCATION_LEVEL`**: каждая **`ActualEducationOrganization`** (корень сертификата и по приложению) → каждый уровень, встречающийся у программ в соответствующем контексте (для корневой ОО — объединение по всем программам строки; для ОО приложения — только программы этого приложения).
- Скалярные поля из `scalar_property_groups` попадают в **`SET`** с исходными именами JSON-ключей (кроме `EduLevelName` на программе и `RegionName` на сертификате/ОО — см. выше).
- Имена **переменных** Cypher (`c`, `s0`, `p_si0_0`, `elv0`, `d0`, `a0` и т.д.) — только для одного составного запроса на строку JSONL; на узлы в графе влияет только **`uri`** и метки.

Типы рёбер: `hasSupplement` → `HAS_SUPPLEMENT`, `hasDecision` → `HAS_DECISION`, `hasEducationalProgram` → `HAS_EDUCATIONAL_PROGRAM`, `hasEducationLevel` → `HAS_EDUCATION_LEVEL`, `offersEducationLevel` → `OFFERS_EDUCATION_LEVEL`, `inRegion` → `IN_REGION`, `hasActualEducationOrganization` → `HAS_ACTUAL_EDUCATION_ORGANIZATION`.

## Загрузка в Neo4j

В **Neo4j Browser** или **cypher-shell** выполните содержимое файла (или разбейте на части при очень больших выгрузках). При необходимости оберните в транзакцию по документации вашей версии Neo4j.

Один блок для одной строки JSONL — это **один составной запрос** Cypher (цепочка `MERGE`/`SET`); его можно выполнить целиком без `;` в конце. Если в Browser выделяете **несколько** блоков подряд и получаете ошибку парсера — перегенерируйте файл с флагом **`--semicolon`** или добавьте **`;`** вручную после последней строки каждого блока.

**Docker:** в Neo4j 5 для `NEO4J_AUTH=neo4j/…` пароль должен быть **не короче 8 символов** — иначе контейнер завершится с кодом **70** (см. логи `docker logs`).

## Kuzu

**[Kuzu](https://kuzudb.com)** — встраиваемая СУБД с диалектом Cypher; для прототипов и локальной аналитики без отдельного сервера Neo4j часто удобнее Docker/облака.

Отличия от Neo4j, важные для нашего файла:

1. **Схема обязательна.** Перед `MERGE` нужно один раз создать **node tables** и **rel tables** с типами свойств и `PRIMARY KEY` (например, для узлов — по **`uri`**). Конвертер **не** генерирует этот DDL: метки и поля перечислены в [`specs/kg/mapping.json`](../specs/kg/mapping.json), типы можно согласовать с [`specs/sql/mapping.json`](../specs/sql/mapping.json) или объявить всё как `STRING`, кроме очевидных `BOOL`.
2. **`MERGE`/`SET`** в Kuzu поддерживаются, но для **крупных** выгрузек документация рекомендует массовый импорт (**`COPY FROM`**, Parquet/CSV и т.д.), а не сотни тысяч отдельных `MERGE` из одного `.cypher`.
3. Подмножество Cypher **не полностью** совпадает с Neo4j — при сбоях смотрите [отличия Kuzu от Neo4j](https://docs.kuzudb.com/cypher/difference) и разделы про [`MERGE`](https://docs.kuzudb.com/import/merge).

Практический путь: на небольшой выборке (`--limit 50`) поднять схему вручную или скриптом, прогнать кусок `.cypher`, затем для полного реестра либо оставить Neo4j, либо строить пайплайн **Parquet → `COPY FROM`** по тем же сущностям, что и SQL-mapping.

## Связанные файлы

- [`knowledge_graph.md`](knowledge_graph.md) — общая логика графа.
- [`specs/sql/mapping.json`](../specs/sql/mapping.json) — реляционная проекция той же строки JSONL.
