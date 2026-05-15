# Скрипты каталога `tools/`

Обзор утилит в **`tools/`** и связь с **`convert.py`**. Входом для аналитики и выборок обычно служит **JSONL** из конвертера.

## Связь с `convert.py` (кратко)

По умолчанию CLI/API пишет **компактный** JSONL:

- без сертификатов с **«срезанными»** корневыми статусами: **`StatusName`** на **`Certificate`** не из набора, который по умолчанию **не пишется** (см. `convert.CERTIFICATE_ROOT_STATUSES_OMITTED_FROM_JSONL`: в т.ч. «Недействующее», «Прекращено», «Лишен аккредитации»); из **`Supplements[]`** при этом удаляются элементы с **`StatusName`** из `convert.SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL` (те же три строки для приложений);
- без строк с псевдорегионом **«за пределами РФ»** на корневом **`RegionName`**;
- без сертификатов, чей **`Certificate.Id`** входит в **`convert.CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST`** (жёсткий список в коде; в отчёте **`omitted_certificate_personal_blocklist`**);
- без ключей со значением **`null`**, пустой строкой и пустыми **`{}`** / **`[]`** после нормализации (**`omit_null_keys`**);
- с дозаполнением при **`fill_aeo_coherent_inn_ogrn`** (по умолчанию): **INN** / **OGRN** / **KPP** в **`ActualEducationOrganization`** (корень и **`Supplements[]`**) из согласованных доноров, ветка «филиал по `Id`», подъём **EduOrgINN**/**EduOrgOGRN** с корня/supplement, «оболочки» supplement AEO без цифровых ИНН/ОГРН; отключение: **`--no-fill-aeo-coherent-inn-ogrn`**;
- с ручным JSON **ОГРН→ИНН** по умолчанию из **`specs/certificate_inn_overrides_by_ogrn.json`**, если файл есть; отключение: **`--no-certificate-inn-overrides-by-ogrn`**, свой путь: **`--certificate-inn-overrides-by-ogrn-json`**.

Полный снимок как в XML по статусу, региону и полям: **`--include-inactive`**, **`--include-outside-rf-region`**, **`--include-null-keys`**.

Поля **`INN`**, **`KPP`**, **`OGRN`**, **`EduOrgINN`**, **`EduOrgKPP`**, **`EduOrgOGRN`**, **`IndividualEntrepreneurINN`**, **`IndividualEntrepreneurEGRIP`**: после удаления пробелов и дефисов в JSON попадают **только** значения, где остались **одни цифры**; иначе в объекте будет **`null`**, а при компактном выводе **ключ часто отсутствует**. Счётчик отклонённых значений — **`non_digit_ids`** в JSON-отчёте **`--report`**; в лог — **`DEBUG`**, не **`WARNING`**.

---

## Генерация артефактов из схемы / кода

| Скрипт | Назначение | Типичная команда |
|--------|------------|------------------|
| **`generate_field_labels.py`** | `specs/field_labels.json` — пути `Certificate/…` → русские подписи из эталонного XML структуры | `python tools/generate_field_labels.py` |
| **`generate_json_schema.py`** | `specs/json-schema/certificate-line.schema.json` из полей и констант `convert.py` | `python tools/generate_json_schema.py` |
| **`generate_prisma_schema.py`** | `specs/prisma/schema.prisma` из `specs/sql/mapping.json` + `specs/prisma/mapping.json` | `python tools/generate_prisma_schema.py` |
| **`generate_sql_er_diagram.py`** | `docs/diagrams/sql_schema_er.md` (Mermaid ER) из `specs/sql/mapping.json` | `python tools/generate_sql_er_diagram.py` |

---

## Подвыборки и тестовые наборы JSONL

| Скрипт | Назначение | Вход / выход |
|--------|------------|----------------|
| **`sample_jsonl_lines.py`** | Резервуарная случайная подвыборка **N** непустых строк за один проход | JSONL → stdout или файл; см. `--help` |
| **`generate_test_jsonl_samples.py`** | Набор файлов `sample_10.jsonl` … `sample_5000.jsonl` с разными seed | По умолчанию самый крупный `out/data-*.jsonl` или явный путь; выход — `examples/jsonl_samples/` |

---

## Аналитика и аудиты по готовому JSONL

| Скрипт | Назначение | Выход по умолчанию |
|--------|------------|---------------------|
| **`audit_dataset_identity_fields.py`** | ИНН/ОГРН на корне и в **`ActualEducationOrganization`** (корень и **`Supplements[]`**): пустые, «только цифры» после очистки, срезы **`would_drop_if_require_*`**, а также сколько карточек в приложении с пустым INN/OGRN при **совпадении UID-полей** с корневой AEO (`Id` без учёта регистра; при непустом **`HeadEduOrgId`** с обеих сторон — он тоже должен совпадать). Дополнительно: счётчики **`*borrowable*`** — **остаток** в данном JSONL: при том же UID ещё есть пустое INN/OGRN и пригодный донор (**корневая AEO** и/или **EduOrgINN** / **EduOrgOGRN** на корне Certificate; только цифры после очистки; те же правила, что **`fill_aeo_coherent_inn_ogrn`** в **`convert.py`**). После конвертации с умолчанию часто **нули**. **Не** читает XML. | `examples/dataset_identity_fields_audit.json` |
| **`audit_aeo_supplement_root_id_with_identity_issues.py`** | Только строки, где есть **хотя бы одна** проблема с полями идентичности (те же критерии, что у **`audit_dataset_identity_fields.py`**): разрез карточек supplement AEO по **`Id` = / ≠ / несравнимо** с **`Id`** корневой AEO; отдельно — только карточки с проблемой **INN** или **OGRN** в приложении. | `examples/dataset_aeo_supplement_root_id_identity_issues.json` |
| **`registry_status_vocab.py`** | Уникальные **`StatusName`** на корне **`Certificate`** и в **`Supplements[]`**: гистограммы, отсортированные наборы, **по одному примеру** (`certificate_id`, индекс supplement) на каждое значение (первое вхождение в файле). | `examples/registry_status_names_vocab.json` |
| **`extract_unique_edu_level_names.py`** | Уникальные непустые **`EduLevelName`** в **`Supplements[].EducationalPrograms[]`**: отсортированный список, гистограмма, счётчики (в т.ч. пустые уровни). Выход в репозитории — **`specs/edu_level_names_vocab.json`**. | `specs/edu_level_names_vocab.json` |
| **(справочник)** | **`specs/edu_level_names_fz273_map.json`** — целевые уровни по ФЗ-273 и маппинг строк из **`edu_level_names_vocab.json`**: `mapping_kind` включает в т.ч. `identity`, `umbrella_term_mapped`, `manual_review_basis_ugs`, `manual_review_basis_region`, `ambiguous_umbrella_term`, `technical_placeholder`; для части записей `target_edu_level_name` — `null` (`REQUIRES_MANUAL_REVIEW` / `NO_CANONICAL_TARGET`). Покрытие vocab — **`tests/test_edu_level_names_fz273_map.py`**. Словарь в **`convert.py`** не используется. **Примеры полных строк** для редких уровней (ручной отбор из снимка vocab): **`examples/certificate_lines_edu_level_name_obschee_obrazovanie_sample.jsonl`**, **`examples/certificate_lines_edu_level_name_professionalnoe_obuchenie_sample.jsonl`**, **`examples/certificate_lines_edu_level_name_professionalnoe_obrazovanie_sample.jsonl`**. | `specs/edu_level_names_fz273_map.json` |
| **`sample_one_certificate_per_edu_level_name.py`** | На каждый уровень из **`unique_edu_level_names`** — одна выборка: по умолчанию сертификат с **наибольшей заполненностью** (при равенстве — случайный tie, **`--seed`**). Выход: **`EduLevelName`**, **`programs`** из одного объекта (первая подходящая программа; `EduLevelName` в объекте не дублируется при наличии других полей). **`--uniform-random`** — без приоритета заполненности. | `examples/certificate_sample_one_random_per_edu_level_name.jsonl` |
| **`audit_dataset_status.py`** | Гистограммы корневых **`StatusName`**, **`TypeName`** | `examples/dataset_status_audit.json` |
| **`audit_dataset_null_statusname.py`** | Сертификаты и элементы **`Supplements[]`**, где **`StatusName`** отсутствует, **`null`** или пустая строка: счётчики, примеры (**`--limit`**), объединение по строке в отчёте; полные строки входа: **`-p`** / **`--problem-jsonl`** [PATH] (корень **или** supplement); **без PATH после `-p`** — **`examples/certificate_lines_StatusName_nullish.jsonl`**; **`-f`** (только корень) | `examples/dataset_null_statusname_audit.json` |
| **`audit_dataset_edu_program_levels.py`** | **`EduLevelName`** в программах: гистограмма, классификация сертификата (по **непустым** уровням), отдельно — **пустые** `EduLevelName` (программы и сертификаты, примеры, разрез по классу); выгрузки: полные строки — **`-p`**, **`--school-jsonl`**, **`--mixed-jsonl`**, **`--empty-level-jsonl`** [PATH] (крупные `.jsonl` в **`.gitignore`**); по одной программе — **`--empty-program-jsonl`** [PATH] (по умолчанию `examples/edu_programs_empty_EduLevelName.jsonl`) | `examples/dataset_edu_program_levels_audit.json` |
| **`audit_dataset_region.py`** | Гистограмма **`RegionName`**, счётчик псевдорегиона «за пределами РФ» **в данном файле** (после конвертации по умолчанию таких строк в JSONL нет — см. **`omitted_outside_rf_region`** в отчёте `convert.py`) | `examples/dataset_region_audit.json` |
| **`extract_branch_supplement_aeo_inn_gap_jsonl.py`** | Выборка карточек supplement **`ActualEducationOrganization`**, где **`Id` ≠ `Id` корня** (филиал в смысле проекта), **INN** пуст, донор INN есть как у **`convert._donor_inn_for_supplement`**. Строки — объекты **`branch_supplement_aeo_inn_gap_v1`** (не полный сертификат). Флаг **`--limit N`** — только первые N карточек для просмотра. Крупный **`examples/branch_supplement_aeo_inn_gap.jsonl`** в **`.gitignore`**; в репозитории — короткий пример **`examples/branch_supplement_aeo_inn_gap_sample.jsonl`**. | `-o` / **`--limit`** |
| **`audit_branch_supplement_aeo_inn_gap.py`** | Сводка по JSONL из **`extract_branch_supplement_aeo_inn_gap_jsonl.py`**: OGRN-дыра при доноре сверху, **`HeadEduOrgId`**, гистограмма **`IsForBranch`**, сверка **`donor_inn_digits`**. | `examples/dataset_branch_supplement_aeo_inn_gap_audit.json` |
| **`analyze_aeo_cert_vs_supplement.py`** | Сравнение **`Id`** у **`ActualEducationOrganization`** на корне и в приложениях; срезы «интересных» строк | `examples/jsonl_samples_aeo_mismatch/sample_*.jsonl` |
| **`scan_jsonl_placeholder_scalars.py`** | Подсчёт скалярных плейсхолдеров по путям в JSON | см. `--help` |

После смены логики нормализации идентификаторов **или** дозаполнения AEO в **`convert.py`** пересоберите JSONL и заново запустите аудиты (**`audit_dataset_identity_fields.py`**, при необходимости регион/статус/**`audit_dataset_null_statusname.py`**/**`audit_dataset_edu_program_levels.py`**/AEO), чтобы **`examples/dataset_*_audit.json`** и счётчики **`nonempty_not_digits_only_after_clean`** / **`*borrowable*`** отражали текущий снимок. Выборку «филиал / пустой INN в supplement» пересобирайте **`extract_branch_supplement_aeo_inn_gap_jsonl.py`**, затем **`audit_branch_supplement_aeo_inn_gap.py`** (см. **`.gitignore`** для крупного **`examples/branch_supplement_aeo_inn_gap.jsonl`**).

---

## Справочники и прочее

| Скрипт | Назначение |
|--------|------------|
| **`extract_unique_educational_programs.py`** | Уникальные **`EducationalProgram`** (дедуп без **`Id`**), фильтры по **`UGSName`**, сортировка; вход — JSONL из **`convert.py`** (с теми же умолчаниями компактности и отсечений, что и в таблице выше). |

---

## Зависимости

Скрипты рассчитаны на запуск из корня репозитория с тем же **Python**, что и проект (`python tools/...` или `python3`). Дополнительные пакеты сверх **`requirements.txt`** для большинства утилит **не** требуются ( **`lxml`** — для генерации подписей из XML).
