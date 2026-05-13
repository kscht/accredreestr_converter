# JSON Schema для строки JSONL

Описание **одного объекта** в файле `.jsonl` (одна строка после `json.loads`): выход `convert.py`.

## Файлы

| Файл | Назначение |
|------|------------|
| [`../json-schema/certificate-line.schema.json`](../json-schema/certificate-line.schema.json) | Схема draft 2020-12 |
| [`../generate_json_schema.py`](../generate_json_schema.py) | Перегенерация схемы из списков полей и констант `convert.py` |

Пересборка после изменения типов или набора полей в конвертере:

```bash
python generate_json_schema.py
# или
python generate_json_schema.py -o json-schema/certificate-line.schema.json
```

## Проверка данных

Пример с [check-jsonschema](https://github.com/python-jsonschema/check-jsonschema) или [ajv-cli](https://github.com/ajv-validator/ajv-cli) (устанавливаются отдельно):

```bash
# одна строка в файл для проверки
head -n 1 out/data.jsonl > /tmp/one.json
python -c "import json; o=json.load(open('/tmp/one.json')); json.dump(o, open('/tmp/one.obj.json','w'), ensure_ascii=False)"
# далее валидатор CLI по документации инструмента
```

В тестах репозитория используется пакет **`jsonschema`** (`pip install -r requirements.txt`).

## Ограничения схемы

- **`additionalProperties: true`** на корне и на вложенных объектах: в выгрузке могут появиться **новые теги** XML → новые ключи JSON; конвертер только предупреждает, но пишет их в объект.
- **Даты**: в схеме указан тип `string | null`; успешный парсинг даёт `YYYY-MM-DD`, иначе остаётся произвольная строка — отдельный `format: date` не используется, чтобы не отвергать «грязные» значения.
- Схема **не** описывает порядок ключей и **не** дублирует бизнес-правила (уникальность Id между сущностями и т.д.) — только типичная форма JSON.

## Связь с KG и SQL

Те же логические сущности: [`kg/mapping.json`](../kg/mapping.json), [`sql/mapping.json`](../sql/mapping.json). Подписи полей — [`field_labels.json`](../field_labels.json). При добавлении полей в конвертер обновляйте **`generate_json_schema.py`** и перегенерируйте **`certificate-line.schema.json`**.
