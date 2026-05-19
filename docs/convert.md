# Логика `convert.py`: XML → JSONL

Потоковый конвертер выгрузки реестра госаккредитации (ИС ГА, Рособрнадзор) в **JSON Lines**: одна строка UTF-8 = один элемент `<Certificate>`. Исходный XML не читается целиком в память (`lxml.etree.iterparse` по тегу `Certificate`).

См. также: [`AGENTS.md`](../AGENTS.md) (краткий справочник), [`docs/tools.md`](tools.md) (аудиты по готовому JSONL), [`README.md`](../README.md) (CLI-примеры).

---

## Общая схема

```mermaid
flowchart TD
  XML[XML Certificate] --> Parse[elem_to_dict: парсинг и типизация полей]
  Parse --> StripSup[strip_supplements_by_excluded_status]
  StripSup --> AEO["Дозаполнение INN/OGRN/KPP → _derived"]
  AEO --> EduProg1["fill EduLevelName → _derived"]
  EduProg1 --> StripDeg[strip_degenerate_educational_program_stubs]
  StripDeg --> FZ273["normalize EduLevelName → _derived"]
  FZ273 --> Annotate["annotate_derived_fields: IsBranchSupplement, HasBranchSupplements → _derived"]
  Annotate --> Graph["build_graph_projection → _graph"]
  Graph --> Filter{Фильтры записи?}
  Filter -->|да, отсечь| Skip[Не пишем строку]
  Filter -->|нет| Compact[ensure_json_safe + omit_empty_json_values]
  Compact --> JSONL[Строка JSONL]
  JSONL --> Pass2["2-й проход: EduLevelName → _derived (по ProgrammCode)\n+ повторный build_graph_projection"]
  Pass2 --> Out[Готовый .jsonl]
```

**Важно:** второй проход (`backfill_edulevel_name_from_programm_code_neighbors_jsonl`) выполняется **после** закрытия XML и **перезаписывает** уже записанный файл JSONL (два чтения + временный файл).

---

## Принцип `_derived`: оригинал неприкосновенен

Все вычисленные, дозаполненные и нормализованные значения хранятся **только** в `obj["_derived"][key]` и **не мутируют** оригинальные XML-поля. Это позволяет потребителю отличить данные источника от данных конвертера.

| Уровень объекта | Поля в `_derived` | Причина появления |
|----------------|-------------------|-------------------|
| `Certificate` | `EduOrgINN`, `EduOrgOGRN` | отсутствовали в XML, заполнены из AEO |
| `Certificate` | `HasBranchSupplements` | вычислен |
| `Supplement` | `IsBranchSupplement` | вычислен |
| `ActualEducationOrganization` | `INN`, `OGRN`, `KPP` | отсутствовали в карточке АО |
| `EducationalProgram` | `EduLevelName` | пустой в XML / нестандартный (FZ-273) / заполнен по соседям |

**Хелперы** (используются внутри пайплайна):

- `_set_derived(obj, key, value)` — пишет в `obj["_derived"][key]`.
- `_get_effective(obj, key)` — возвращает `_derived[key]` при наличии, иначе `obj[key]`. Применяется во всех функциях, которые читают значения, заполненные предыдущими шагами цепочки.

**Исключение:** при `target_edu_level_name: null` в FZ-273 ключ `EduLevelName` удаляется **из обоих** мест — и из оригинала, и из `_derived`, поскольку значение признано некорректным.

---

## Этап 1. Парсинг XML (`elem_to_dict`)

Для каждого `<Certificate>` строится дерево словарей по эталонной структуре (`specs/xml/data-20160908-structure-20160713.xml`, список тегов для предупреждений о неизвестных полях).

| Конструкция XML | В JSON |
|-----------------|--------|
| `Supplements/Supplement` | `Supplements[]` |
| `Decisions/Decision` | `Decisions[]` |
| `EducationalPrograms/EducationalProgram` | `EducationalPrograms[]` внутри supplement |
| `ActualEducationOrganization` | вложенный объект (корень или supplement) |

Если в XML нет обёртки коллекции, в дереве парсера появляются пустые массивы (`Supplements`, `Decisions`, `EducationalPrograms`); при компактной записи пустые `[]` обычно **не попадают** в JSONL.

### Очистка текста (`clean_text`)

Для всех строковых полей до типизации:

- замена нестандартных пробелов (NBSP и т.п.) на обычный пробел;
- удаление управляющих символов C0/C1 (кроме `\t`, `\n`, `\r`);
- схлопывание пробелов, `strip`;
- пустые маркеры → `null`: `""`, `-`, `—`, `н/д`, `null`, `none` и др. (`EMPTY_MARKERS`).

### Типизация скалярных полей (`normalize_scalar`)

| Группа полей | Поведение |
|--------------|-----------|
| **Булевы** (`IsFederal`, `IsAccredited`, …) | `1`/`true`/`да` → `true`, `0`/`false`/`нет` → `false`; иначе `null` + `WARNING`, счётчик `bad_booleans` |
| **Даты** (`IssueDate`, `EndDate`, `DecisionDate`) | Распознанные форматы → `YYYY-MM-DD`; иначе остаётся очищенная строка + `WARNING`, `bad_dates` |
| **ИНН/КПП/ОГРН** (корень и AEO) | После удаления пробелов и дефисов — **только цифры**; иначе `null` (ключ часто не пишется), счётчик `non_digit_ids`, детали в логе `DEBUG` |
| **`ProgrammCode`**, **`UGSCode`** | Если уже `XX.XX.XX` — без изменений; иначе шесть цифр подряд → точки (`031501` → `03.15.01`) |
| **`Qualification`** | Строка `"0"` (плейсхолдер) → `null` |
| Остальные строки | После `clean_text` как есть |

### Наименования организаций (без display v1)

Поля **`EduOrgFullName`**, **`EduOrgShortName`**, **`FullName`**, **`ShortName`** (корень и supplement) попадают в JSONL **как очищенный текст из XML** — без правил display v1 из `org_name_normalize.py` (ОПФ, кавычки, КАПС и т.д.). Типографическая нормализация и черновик словаря — **вне** конвертера: [`docs/tools.md`](tools.md) (OpenRouter, `diff_org_name_dictionaries.py`).

Идентификаторы в отчёте: `INN`, `KPP`, `OGRN`, `EduOrgINN`, `EduOrgKPP`, `EduOrgOGRN`, `IndividualEntrepreneurINN`, `IndividualEntrepreneurEGRIP`.

### Неизвестные теги

Тег, отсутствующий в эталонной схеме, парсится, но даёт **одно** `WARNING` на имя тега за прогон; имя попадает в `unknown_tags` отчёта `--report`.

### Битые записи

Исключение при обработке одного `Certificate` → строка **не пишется**, `skipped` / `broken_records`. С флагом `--strict` конвертация **прерывается**.

---

## Этап 2. Постобработка одной записи (до записи в JSONL)

Порядок вызовов в `convert_one` (для каждого сертификата, прошедшего парсер):

### 2.1. Срез приложений по статусу

**`strip_supplements_by_excluded_status`** (при `omit_inactive=True`, по умолчанию):

из `Supplements[]` **удаляются** элементы, у которых `StatusName` ∈

- «Недействующее»
- «Прекращено»
- «Лишен аккредитации»

Счётчик в отчёте: **`stripped_supplements_by_status`** (сумма удалённых элементов по всему файлу; на одном сертификате может быть >1).

Полный снимок приложений как в XML: **`--include-inactive`**.

### 2.2. Дозаполнение идентичности AEO и EduOrg (по умолчанию включено)

Отключение всего блока: **`--no-fill-aeo-coherent-inn-ogrn`**.

#### Согласованные UID

Две карточки `ActualEducationOrganization` считаются «одной организацией», если:

- совпадают `Id` (без учёта регистра UUID);
- если **оба** `HeadEduOrgId` непусты — они тоже должны совпадать.

#### `fill_aeo_inn_ogrn_from_coherent_certificate_sources`

1. **Supplement с тем же UID, что корневая AEO** — пустые `INN`/`OGRN` → `_derived` supplement-AEO (донор: корневая AEO или `EduOrgINN`/`EduOrgOGRN` на сертификате).
2. **Supplement с другим `Id`** (филиал/площадка) — аналогично, донор тот же.
3. **Корневая AEO** — пустые `INN`/`OGRN` → `_derived` корневой AEO (донор: supplement с тем же UID, иначе `EduOrg*` на сертификате).

Счётчики: блок **`aeo_coherent_inn_ogrn_fills`** в `--report`.

#### `fill_certificate_eduorg_inn_ogrn_from_near_aeo`

Если на корне `Certificate` нет валидных **цифровых** `EduOrgINN` / `EduOrgOGRN` (проверяется через `_get_effective`):

- сначала из supplement-AEO с тем же UID;
- иначе из корневой AEO (через `_get_effective` — учитывает уже заполненное на шаге выше).

Результат → `Certificate._derived.EduOrgINN` / `EduOrgOGRN`.

Счётчики: **`certificate_EduOrg_inn_ogrn_backfill_from_near_aeo`**.

#### Ручной справочник ОГРН → ИНН

Файл по умолчанию: **`specs/certificate_inn_overrides_by_ogrn.json`**.

**`apply_certificate_inn_from_manual_ogrn_map`**: при известном ОГРН пишет отсутствующие `EduOrgINN` → `Certificate._derived` и/или `INN` → `ActualEducationOrganization._derived`. Если заданы и `EduOrgOGRN`, и `ActualEducationOrganization.OGRN`, они должны **совпадать**, иначе правило не применяется.

Отключение: **`--no-certificate-inn-overrides-by-ogrn`**. Свой файл: **`--certificate-inn-overrides-by-ogrn-json`**.

Счётчики: **`certificate_INN_manual_override_by_OGRN_map`**.

#### «Пустые оболочки» supplement AEO

**`fill_degenerate_supplement_aeo_identity_from_certificate_donors`**: если у supplement-`ActualEducationOrganization` **нет** валидных цифровых `INN` и `OGRN` (проверяется через `_get_effective`), значения `INN` / `OGRN` / `KPP` копируются в `supplement.ActualEducationOrganization._derived`.

Счётчики: **`supplement_ActualEducationOrganization_degenerate_identity_shell_fill`**.

### 2.3. Программы: `EduLevelName`

#### Подстановка из `ProgrammName`

**`fill_edulevel_name_from_programm_name_when_implied`**: при **пустом** `EduLevelName` (проверяется через `_get_effective`), если `ProgrammName` совпадает с одной из школьных ступеней реестра (`PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME`), значение пишется в `EducationalProgram._derived.EduLevelName`.

Отключение: **`--no-fill-edulevel-from-programm-name`**.

Счётчик: **`educational_program_EduLevelName_from_ProgrammName_when_empty`**.

#### Удаление дегенеративных «заглушек»

**`strip_degenerate_educational_program_stubs`** выполняется **до** нормализации ФЗ-273.

Позиция удаляется из `Supplements[].EducationalPrograms[]`, если одновременно:

- нет валидного `ProgrammCode` (нормализованный вид `XX.YY.ZZ`, не `--` и не мусор);
- пустой `ProgrammName`;
- пустой `EduLevelName`.

Типичный случай в XML: узел только с `Id`. Сертификат в JSONL **остаётся**; соседние программы не трогаются. Если программ не осталось — ключ `EducationalPrograms` у supplement убирается.

Счётчик: **`stripped_degenerate_educational_programs`**.

**Зачем до ФЗ-273:** если маппинг позже удалит `EduLevelName` (`target_edu_level_name: null`), программа с осмысленным уровнем в реестре **не** считается заглушкой и не вырезается.

#### Нормализация по ФЗ-273

**`normalize_edu_level_names_via_fz273_map`**: читает значение через `_get_effective(pr, "EduLevelName")` и по файлу **`specs/edu_level_names_fz273_map.json`**:

| Ситуация | Действие |
|----------|----------|
| Строка в `entries` → целевое имя (≠ источнику) | Нормализованное значение → `_derived.EduLevelName`; оригинал не тронут |
| Строка в `entries` → `null` | Ключ `EduLevelName` удаляется **из оригинала и из `_derived`** |
| Строка совпадает с каноном, нет в `entries` | Без изменения |
| Не в `entries` и не в каноне | Без изменения + счётчик `unknown_registry_level_programs` |

Отключение: **`--no-normalize-edu-level-names-fz273`**. Свой JSON: **`--edu-level-names-fz273-map-json`**.

Счётчики: **`educational_program_EduLevelName_fz273_map`**.

---

## Этап 3. Фильтры: целая строка сертификата не пишется

Проверки выполняются **после** постобработки. Первое сработавшее условие отсекает запись (цепочка `if / elif`):

| Условие | Флаг / константа | Счётчик отчёта |
|---------|------------------|----------------|
| Корневой `StatusName` ∈ «Недействующее», «Прекращено», «Лишен аккредитации» | по умолчанию `omit_inactive=True` | `omitted_inactive` |
| Корневой `RegionName` = псевдорегион «за пределами РФ» | по умолчанию `omit_outside_rf_region=True` | `omitted_outside_rf_region` |
| Нет валидного `EduOrgOGRN` (только цифры после очистки) | **`--omit-invalid-eduorg-ogrn`** (по умолчанию **выкл.**) | `omitted_invalid_eduorg_ogrn` |
| `Certificate.Id` в жёстком блоклисте | `CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST` в коде | `omitted_certificate_personal_blocklist` |

Полный снимок по статусу/региону: **`--include-inactive`**, **`--include-outside-rf-region`**.

### Компактный JSON (по умолчанию)

Перед записью строки:

1. **`ensure_json_safe`** — удаление недопустимых для JSON управляющих символов в строках.
2. **`omit_empty_json_values`** (по умолчанию **вкл.**) — убрать ключи с `null`, пустыми строками, пустыми `{}` / `[]`; пустые объекты внутри списков тоже выбрасываются.

Полное дерево как после парсера: **`--include-null-keys`**.

В JSONL **нет** поля `_source_file` / имени XML-файла; провенанс снимка добавляйте при загрузке снаружи.

---

## Этап 4. Второй проход по JSONL (`ProgrammCode` → `EduLevelName`)

**`backfill_edulevel_name_from_programm_code_neighbors_jsonl`** (по умолчанию **вкл.**):

1. **Проход 1:** по всему файлу для каждого нормализованного `ProgrammCode` (`XX.YY.ZZ`) строится частота непустых значений `EduLevelName`, читаемых через `_get_effective` (учитывает `_derived`).
2. Выбирается уровень с **максимальной** частотой; при равенстве — **лексикографически минимальная** строка.
3. **Проход 2:** у программ с пустым `_get_effective(pr, "EduLevelName")` и тем же кодом значение пишется в `_derived.EduLevelName`; файл перезаписывается атомарно через `*.neighbor_tmp`.

Отключение: **`--no-fill-edulevel-from-programm-code-neighbors`**.

Счётчик: **`educational_program_EduLevelName_neighbor_backfill_from_ProgrammCode_global_pass`**.

Глобальность: доноры могут быть на **других** сертификатах в том же файле JSONL.

---

## Этап 5. Проекция `_graph` (`build_graph_projection`)

После `annotate_derived_fields` и **до** записи строки вызывается `build_graph_projection(record)` — функция формирует ключ `_graph` с готовыми полями для граф-вьювера. Граф строится **напрямую из `_graph`**, без необходимости знать правила `_derived` или обращаться к оригинальным XML-полям.

Функция вызывается **дважды**: в первом проходе и после 2-го прохода (backfill EduLevelName по соседям), чтобы `_graph.programs[].edu_level` всегда отражал финальное значение.

### Структура `_graph`

```json
{
  "org": {
    "ogrn": "1234567890123",
    "inn": "1234567890",
    "display_name": "Гимназия №1",
    "founder_key": "municipal:Брянская область",
    "founder_label": "Муниципальный, Брянская область"
  },
  "region": "Брянская область",
  "region_short": "Брянская",
  "control_organ": "Министерство образования и науки Брянской области",
  "control_organ_short": "Минобр Брянской",
  "edu_levels": ["Основное общее образование", "Среднее общее образование"],
  "edu_levels_short": ["ООО", "СОО"],
  "programs": [
    {
      "code": "44.02.01",
      "ugs_code": "44.00.00",
      "edu_level": "Среднее профессиональное образование",
      "edu_level_short": "СПО"
    }
  ],
  "branches": [
    {
      "ogrn": "...",
      "inn": "...",
      "display_name": "Филиал №1",
      "edu_levels": ["Начальное общее образование"],
      "edu_levels_short": ["НОО"],
      "programs": [...]
    }
  ]
}
```

Пустые списки и `None`-значения в `_graph` не включаются. `edu_levels_short` / `region_short` / `control_organ_short` пишутся только если значение отличается от оригинала.

### Вспомогательные функции

| Функция | Назначение |
|---------|------------|
| `make_display_name(full, short)` | Извлекает короткое имя для узла: сначала из кавычек `«…»` (innermost), затем убирает ОПФ-обёртку, аббревиатуры и хвосты |
| `shorten_region_name(name)` | Регион без суффикса «область/край/…»: «Брянская», «г. Москва» → «Москва», «Республика Татарстан» → «Татарстан» |
| `shorten_edu_level(name, code=None)` | Аббревиатура уровня образования: ДО/НОО/ООО/СОО/СПО/ДПО/Бакалавриат/Специалитет/Магистратура/ПКВК; для ПКВК с `code` уточняет подтип по второму сегменту (`06`→Аспирантура, `07`→Адъюнктура, `08`→Ординатура, `09`→Ассистентура) |
| `make_control_organ_display(name)` | Сокращает ControlOrgan: «Министерство образования Брянской области» → «Минобр Брянской», «Рособрнадзор» остаётся как есть; таблица правил — `_CO_TYPE_MAP` |
| `_co_extract_region(text)` | Извлекает регион из конца строки ControlOrgan (родительный падеж): «…Брянской области» → «Брянской» |
| `_derive_founder(is_federal, form_name, region_name, edu_levels)` | Синтетический учредитель: `IsFederal+ВО` → Минобрнауки, `IsFederal` без ВО → Минпросвещения, «муниципальное» → municipal:region, «государственное» → regional:region, частные → private |
| `_graph_collect_programs(supplement)` | Собирает уникальные `edu_levels` и `programs` (с `code`, `ugs_code`, `edu_level`, `edu_level_short`) из одного supplement |

### Учредитель (`founder_key` / `founder_label`)

В XML нет прямого поля «учредитель» — он выводится синтетически:

| Условие | `founder_key` | `founder_label` |
|---------|---------------|-----------------|
| `IsFederal=true` + уровни ВО | `federal:nauka` | Минобрнауки России |
| `IsFederal=true` без ВО | `federal:prosv` | Минпросвещения России |
| `FormName` ∋ «муниципальное» | `municipal:<region>` | Муниципальный, `<region>` |
| `FormName` ∋ «государственное» | `regional:<region>` | Субъект РФ, `<region>` |
| Частные формы | `private` | Частный учредитель |
| Остальные | `unknown` | Учредитель неизвестен |

`_GRAPH_HIGHER_EDU_LEVELS` — frozenset четырёх уровней ВО, используется для различия Минобрнауки / Минпросвещения.

---

## Отчёт `--report`

JSON со сводкой по прогону. Основные блоки в `total`:

| Ключ | Смысл |
|------|--------|
| `processed` | Записано строк JSONL |
| `skipped` | Пропущено из-за исключения при разборе |
| `omitted_inactive` | Не записаны целые сертификаты (статус на корне) |
| `omitted_outside_rf_region` | Не записаны (псевдорегион) |
| `omitted_invalid_eduorg_ogrn` | Не записаны (нет валидного EduOrgOGRN) |
| `stripped_supplements_by_status` | Удалено элементов `Supplements[]` |
| `omitted_certificate_personal_blocklist` | Блоклист по `Certificate.Id` |
| `warnings` | `bad_dates`, `bad_booleans`, `non_digit_ids`, `broken_records`, `unknown_tags` |
| `aeo_coherent_inn_ogrn_fills` | Дозаполнения INN/OGRN в AEO |
| `certificate_EduOrg_inn_ogrn_backfill_from_near_aeo` | Подъём EduOrg* на корне |
| `certificate_INN_manual_override_by_OGRN_map` | Ручной ОГРН→ИНН |
| `supplement_ActualEducationOrganization_degenerate_identity_shell_fill` | Оболочки supplement AEO |
| `educational_program_EduLevelName_from_ProgrammName_when_empty` | Школьные ступени из имени программы |
| `stripped_degenerate_educational_programs` | Вырезаны заглушки программ |
| `educational_program_EduLevelName_neighbor_backfill_from_ProgrammCode_global_pass` | 2-й проход по коду |
| `educational_program_EduLevelName_fz273_map` | Переименования / очистки ФЗ-273 |
| `elapsed_seconds` | Время прогона |

---

## Связанные артефакты и ограничения

| Артефакт | Назначение |
|----------|------------|
| `specs/xml/data-20160908-structure-20160713.xml` | Эталон тегов |
| `specs/edu_level_names_fz273_map.json` | Маппинг `EduLevelName` |
| `specs/certificate_inn_overrides_by_ogrn.json` | Ручные ОГРН→ИНН |
| `specs/json-schema/certificate-line.schema.json` | Схема одной строки JSONL |

**`Decisions[]`:** пустой `Id` документа в XML → в JSON `Id: null`; сертификат сохраняется. Импорт в SQL/DuckDB такие решения **не вставляет** (нужен PK) — см. [`docs/sql_convert.md`](sql_convert.md).

**Справочник уникальных программ** (`tools/extract_unique_educational_programs.py`) намеренно **не** включает в дедупликацию `TypeName`, `EduNormativePeriod`, статусы аккредитации программы — см. help утилиты.

---

## Типичная команда

```bash
python convert.py data/data-20260403-structure-20160713.xml \
  -o out/data-20260403-structure-20160713.jsonl \
  --report out/data-20260403-structure-20160713.report.json \
  --progress-every 10000 \
  --log-file out/convert.log
```

Полный снимок как в XML (все статусы, регион, null-ключи):

```bash
python convert.py data/file.xml -o out/full.jsonl \
  --include-inactive --include-outside-rf-region --include-null-keys
```
