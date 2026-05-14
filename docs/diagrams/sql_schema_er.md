# Реляционная схема (SQL mapping)

Актуально относительно [`specs/sql/mapping.json`](../../specs/sql/mapping.json). На GitHub блоки **`mermaid`** в Markdown отображаются штатно.

## Таблицы и связи

```mermaid
erDiagram
  certificates ||--o{ supplements : "Supplements"
  certificates ||--o{ decisions : "Decisions"
  certificates ||--o{ actual_education_organizations : "AEO корень"
  supplements ||--o{ educational_programs : "EducationalPrograms"
  supplements ||--o{ actual_education_organizations : "AEO в приложении"

  certificates {
    text source_file PK
    text certificate_id PK
    text status_name
    text reg_number
    text edu_org_inn
    date issue_date
  }

  supplements {
    text source_file PK
    text certificate_id PK
    text supplement_id PK
    text number
    date issue_date
    boolean is_for_branch
  }

  decisions {
    text source_file PK
    text certificate_id PK
    text decision_id PK
    text decision_type_name
    date decision_date
  }

  educational_programs {
    text source_file PK
    text certificate_id PK
    text supplement_id PK
    int program_slot PK
    text program_id
    text programm_name
    text programm_code
    text ugs_code
    text qualification
  }

  actual_education_organizations {
    text source_file PK
    text certificate_id PK
    text ae_scope PK
    text supplement_id PK
    text aeo_id PK
    text inn
    text ogrn
    boolean is_branch
  }
```

## Заметки

- Составные первичные ключи: в диаграмме перечислены только поля, входящие в PK; полный список колонок — в `mapping.json` и в [`sql_convert.md`](../sql_convert.md).
- **`decisions`**: строки с пустым `Id` в JSON не импортируются (нет PK документа); сертификат остаётся в `certificates`.
- **`educational_programs`**: в PK входит **`program_slot`** (индекс в массиве), потому что **`program_id`** из реестра может повторяться.
- **`actual_education_organizations`**: поле **`ae_scope`** (`certificate` | `supplement`) разделяет корневую ОО и ОО внутри приложения; FK на `supplements` действует для строк с `ae_scope = supplement` (см. импортёр и `sql_convert.md`).
