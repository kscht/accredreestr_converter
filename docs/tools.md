# Скрипты каталога `tools/`

Обзор утилит в **`tools/`** и связь с **`convert.py`**. Входом для аналитики и выборок обычно служит **JSONL** из конвертера.

## Связь с `convert.py` (кратко)

По умолчанию CLI/API пишет **компактный** JSONL:

- без сертификатов со **`StatusName` «Недействующее»** на корне;
- без строк с псевдорегионом **«за пределами РФ»** на корневом **`RegionName`**;
- без ключей со значением **`null`**, пустой строкой и пустыми **`{}`** / **`[]`** после нормализации (**`omit_null_keys`**).

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
| **`audit_dataset_identity_fields.py`** | ИНН/ОГРН на корне и в **`ActualEducationOrganization`** (корень и **`Supplements[]`**): пустые, «только цифры» после очистки, срезы **`would_drop_if_require_*`**. **Не** читает XML; смотрит только то, что уже в JSONL. | `examples/dataset_identity_fields_audit.json` |
| **`audit_dataset_status.py`** | Гистограммы корневых **`StatusName`**, **`TypeName`** | `examples/dataset_status_audit.json` |
| **`audit_dataset_region.py`** | Гистограмма **`RegionName`**, счётчик псевдорегиона «за пределами РФ» **в данном файле** (после конвертации по умолчанию таких строк в JSONL нет — см. **`omitted_outside_rf_region`** в отчёте `convert.py`) | `examples/dataset_region_audit.json` |
| **`analyze_aeo_cert_vs_supplement.py`** | Сравнение **`Id`** у **`ActualEducationOrganization`** на корне и в приложениях; срезы «интересных» строк | `examples/jsonl_samples_aeo_mismatch/sample_*.jsonl` |
| **`scan_jsonl_placeholder_scalars.py`** | Подсчёт скалярных плейсхолдеров по путям в JSON | см. `--help` |

После смены логики нормализации идентификаторов в **`convert.py`** пересоберите JSONL и заново запустите **`audit_dataset_identity_fields.py`**, чтобы счётчики **`nonempty_not_digits_only_after_clean`** отражали только то, что реально осталось строкой в файле.

---

## Справочники и прочее

| Скрипт | Назначение |
|--------|------------|
| **`extract_unique_educational_programs.py`** | Уникальные **`EducationalProgram`** (дедуп без **`Id`**), фильтры по **`UGSName`**, сортировка; вход — JSONL из **`convert.py`** (с теми же умолчаниями компактности и отсечений, что и в таблице выше). |

---

## Зависимости

Скрипты рассчитаны на запуск из корня репозитория с тем же **Python**, что и проект (`python tools/...` или `python3`). Дополнительные пакеты сверх **`requirements.txt`** для большинства утилит **не** требуются ( **`lxml`** — для генерации подписей из XML).
