# Контекст проекта (для ассистента / промпта)

Файл в корне: **`AGENTS.md`** (в Cursor удобно ссылаться как `@AGENTS.md`). Скопируйте разделы в начало чата, чтобы восстановить контекст без длинного ввода.

## Назначение

Потоковая конвертация XML реестра **госаккредитации** образовательных организаций (Рособрнадзор, ИС ГА) в **JSON Lines** (UTF-8, без BOM). Крупные файлы не читаются целиком в память (`iterparse` по `Certificate`).

## Источник данных

- Страница: `https://isga.obrnadzor.gov.ru/accredreestr/opendata/` (Vue SPA).
- Список версий XML: тот же HTML, что у `https://isga.obrnadzor.gov.ru/api/spa/accredreestr/perechen` (iframe «Гиперссылки (URL) на версии набора данных»).
- **`scrape_opendata.py`** — находит `app.*.js`, путь iframe, парсит ссылки `*.xml`.
- **`download.py --discover`** — URL со страницы версий, **только последний снимок** по `data-YYYYMMDD-` в имени; **`--discover --all-versions`** — все ссылки. Потоковое скачивание в `data/` (`-o` = **каталог**).

## Эталон полей (схема)

- **`data-20160908-structure-20160713.xml`** в корне; в коде константа `DEFAULT_SCHEMA_FILENAME` в `convert.py`.
- Переопределение: **`--schema путь`**. Нужен для списка известных тегов (одно предупреждение на новый тег за прогон) и тестов `test_schema_compat.py`.

## Главные файлы

| Файл | Роль |
|------|------|
| `convert.py` | Парсинг, типы, CLI, `convert_many`, статистика |
| `generate_field_labels.py` | JSON `field_labels.json`: путь `Certificate/…` → русская подпись из схемы |
| `field_labels.json` | Сгенерированный словарь подписей для UI (перегенерация: `python generate_field_labels.py`) |
| `download.py` | Скачивание XML, `--discover`, `--save-urls` |
| `scrape_opendata.py` | Только поиск URL |
| `tests/test_convert.py` | Основные тесты |
| `tests/test_schema_compat.py` | Константы ⊆ схема XML |
| `tests/test_scrape_opendata.py` | Парсер HTML perechen |

## CLI `convert.py`

- **Один** вход: по умолчанию **`out/<stem>.jsonl`**, иначе **`-o`**.
- **Несколько** без **`--merged`**: по файлу **`--out-dir/<stem>.jsonl`** (по умолчанию `out/`). **`-o` запрещён** (exit 2).
- **Несколько** + **`--merged`**: один файл, обязателен **`-o`**.
- **`--merged`** при одном входе — ошибка.

Опции: `--schema`, `--progress-every` (default 10000, `0` = тише), `--limit` (на каждый вход), **`--log-file`** (доп. лог; без него только stderr), `--report` (JSON-статистика), `--strict`.

В каждой записи: **`_source_file`** — имя исходного XML.

## Ошибки в полях (что в JSONL)

- **Дата** не распознана → **строка** (после очистки) + `WARNING`, `bad_dates`.
- **Булево** не распознано → **`null`** + `WARNING`, `bad_booleans`.
- **ИНН/КПП/ОГРН** не только цифры → **строка** после очистки + `WARNING`, `non_digit_ids`.
- **Запись целиком** падает при обработке → строка в JSONL **не пишется**, `skipped` / `broken_records`.

## Парсинг

`lxml.etree.iterparse`, `events=("end",)`, `tag="Certificate"`, `huge_tree=True`, `recover=True`, файл в **`rb`**. После каждого `Certificate`: `elem.clear()` и удаление предыдущих siblings.

## Зависимости

`requirements.txt`: `lxml`, `requests`, `pytest`. В конвертере **нет** `xmltodict`, `pandas`, `pydantic`.

## Тесты

```bash
pytest
# опционально: RUN_SLOW=1 pytest -k streaming
```

## Каталоги и gitignore

- **`data/*.xml`** — не в репозитории (скачанные выгрузки).
- **`out/*.jsonl`** — не в репозитории. Повторный запуск с тем же именем **перезаписывает** файл (`"w"`).
