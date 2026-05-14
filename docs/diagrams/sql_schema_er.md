# Реляционная схема (SQL mapping)

Файл **генерируется** из [`../../specs/sql/mapping.json`](../../specs/sql/mapping.json) скриптом `tools/generate_sql_er_diagram.py` (все колонки и связи по `foreign_keys`, как в DDL/`sql_convert`). На GitHub блок **`mermaid`** отображается штатно.

```bash
python tools/generate_sql_er_diagram.py
```

## Таблицы и связи

```mermaid
erDiagram
  certificates ||--o{ supplements : "Supplements[]"
  certificates ||--o{ decisions : "Decisions[]"
  supplements ||--o{ educational_programs : "EducationalPrograms[]"
  certificates ||--o{ actual_education_organizations : "ActualEducationOrganization (корень)"
  supplements ||--o{ actual_education_organizations : "ActualEducationOrganization (в приложении)"

  certificates {
    text certificate_id PK
    boolean is_federal
    text status_name
    text type_name
    text region_name
    text region_code
    text federal_district_name
    text federal_district_short_name
    text reg_number
    text serial_number
    text form_number
    date issue_date
    date end_date
    text control_organ
    text post_address
    text edu_org_full_name
    text edu_org_short_name
    text edu_org_inn
    text edu_org_kpp
    text edu_org_ogrn
    text individual_entrepreneur_last_name
    text individual_entrepreneur_first_name
    text individual_entrepreneur_middle_name
    text individual_entrepreneur_address
    text individual_entrepreneur_egrip
    text individual_entrepreneur_inn
  }

  supplements {
    text certificate_id PK, FK
    text supplement_id PK
    text status_name
    text status_code
    text number
    text serial_number
    text form_number
    date issue_date
    boolean is_for_branch
    text note
    text edu_org_full_name
    text edu_org_short_name
    text edu_org_address
    text edu_org_kpp
  }

  decisions {
    text certificate_id PK, FK
    text decision_id PK
    text decision_type_name
    text order_document_number
    text order_document_kind
    date decision_date
  }

  educational_programs {
    text certificate_id PK, FK
    text supplement_id PK, FK
    int program_slot PK
    text program_id
    text type_name
    text edu_level_name
    text programm_name
    text programm_code
    text ugs_name
    text ugs_code
    text edu_normative_period
    text qualification
    boolean is_accredited
    boolean is_canceled
    boolean is_suspended
  }

  actual_education_organizations {
    text certificate_id PK, FK
    text ae_scope PK
    text supplement_id PK, FK
    text aeo_id PK
    text full_name
    text short_name
    text head_edu_org_id
    boolean is_branch
    text post_address
    text phone
    text fax
    text email
    text web_site
    text ogrn
    text inn
    text kpp
    text head_post
    text head_name
    text form_name
    text kind_name
    text type_name
    text region_name
    text federal_district_short_name
    text federal_district_name
  }
```

## Заметки (политика данных, не видны на ER)

- **`decisions`**: элементы `Decisions[]` с пустым `Id` в JSONL **не вставляются**; сертификат в `certificates` остаётся.
- **`educational_programs`**: в PK входит **`program_slot`** (индекс в массиве), т.к. **`program_id`** из реестра может повторяться.
- **`actual_education_organizations`**: поле **`ae_scope`** (`certificate` | `supplement`); FK на `supplements` относится к строкам с областью приложения (см. [`sql_convert.md`](../sql_convert.md)).
