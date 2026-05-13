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
mkdir -p out
python convert.py data/data-*-structure-*.xml \
  --progress-every 50000 \
  --report out/convert_report.json \
  --log-file out/convert.log
```

Короче, если не нужен отдельный шаг со **`download_urls.txt`**: шаги 1–2 можно заменить одной командой **`python download.py --discover -o data/`** (внутри вызывается тот же поиск URL, плюс сразу скачивание).

## Структура репозитория

| Путь | Назначение |
|------|------------|
| `convert.py` | Конвертация XML → JSONL, CLI |
| `download.py` | Скачивание XML (в т.ч. `--discover`) |
| `scrape_opendata.py` | Поиск актуальных URL XML на странице opendata |
| `data-20160908-structure-20160713.xml` | Эталон структуры полей (схема для неизвестных тегов) |
| `data/` | Скачанные `.xml` (в git не коммитятся, см. `.gitignore`) |
| `out/` | Результаты `.jsonl` (в git не коммитятся) |
| `tests/` | `pytest`, фикстуры в `tests/fixtures/` |
| `requirements.txt` | `lxml`, `requests`, `pytest` |
| `AGENTS.md` | Краткий контекст для ИИ / нового чата |

## Откуда брать данные

Страница открытых данных:  
https://isga.obrnadzor.gov.ru/accredreestr/opendata/

Варианты:

1. **`python download.py --discover -o data/`** — найдёт ссылки и скачает **только последний снимок** (максимальная дата `data-YYYYMMDD-` в имени файла). Все версии: **`--discover --all-versions`**.
2. **`python scrape_opendata.py`** — те же URL в stdout (по умолчанию тоже только последний снимок); **`--all-versions`** — полный список; **`--json`** — JSON; **`-o файл`** — записать в файл.
3. Вручную: URL в **`download_urls.txt`** или аргументами **`download.py`**.

### Как устроен автопоиск (`scrape_opendata.py`)

Страница — SPA; строка **«Гиперссылки (URL) на версии набора данных»** — это **iframe** с HTML тем же endpoint, что  
`https://isga.obrnadzor.gov.ru/api/spa/accredreestr/perechen`.  
Скрипт тянет `app.*.js`, вытаскивает путь iframe, парсит `<a href="...xml">`.  
По умолчанию **`download.py --discover`** и **`scrape_opendata.py`** оставляют только файлы с **максимальной** датой в фрагменте имени `data-YYYYMMDD-` (один актуальный снимок); полный список версий — флаг **`--all-versions`**.

## Схема XML

Корень: `OpenData` → `Certificates` → `Certificate`. Коллекции: `Supplements`/`Supplement`, `Decisions`/`Decision`, `EducationalPrograms`/`EducationalProgram`; вложенность `ActualEducationOrganization`.  
В JSON каждая строка содержит **`_source_file`** — имя исходного XML (без пути).

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
python download.py   # без URL — читает download_urls.txt (создаст шаблон при отсутствии)
```

Потоково по 1 МБ, опционально `Range`; при ошибке HTTP частичный файл удаляется.

## Конвертация (`convert.py`)

| Ситуация | Команда |
|----------|---------|
| Один XML, выход по умолчанию | `python convert.py data/file.xml` → `out/file.jsonl` |
| Один XML, свой путь | `python convert.py data/file.xml -o out/custom.jsonl` |
| Несколько XML → **отдельные** файлы | `python convert.py a.xml b.xml c.xml --out-dir out/` |
| Несколько XML → **один** файл | `python convert.py a.xml b.xml c.xml --merged -o out/all.jsonl` |

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
```

Своя схема для проверки неизвестных тегов:

```bash
python convert.py input.xml -o out.jsonl --schema data-20160908-structure-20160713.xml
```

## Обработка «грязных» данных

- Нормализация пробелов и невидимых символов (`clean_text`), `ensure_json_safe` перед `json.dumps`.
- **Даты:** распространённые форматы; таймзона (`Z`, `±HH:MM`, при наличии `:` в строке — ещё `±HH`, `±HHMM`, напр. `2010-06-18 00:00:00+04`). Успех → строка **`YYYY-MM-DD`**; иначе в JSON остаётся **очищенная строка** + `WARNING`.
- **Булевы:** не распознано → **`null`** + `WARNING`.
- **ИНН/КПП/ОГРН:** после очистки не только цифры → в JSON **строка** как есть + `WARNING`.
- Пустые маркеры → `null`; битая запись → `skipped`, при `--strict` — остановка.

## Пример строки JSONL

```json
{"Id":"123","IsFederal":true,"Supplements":[],"Decisions":[],"_source_file":"federal.xml"}
```

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
SELECT _source_file, count(*) FROM read_json_auto('out/merged.jsonl') GROUP BY 1;
```
(DuckDB / аналог)

## Тесты

```bash
pytest
```

Долгий тест: `RUN_SLOW=1 pytest -k streaming`.
