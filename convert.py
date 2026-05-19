"""Потоковая конвертация XML реестра аккредитации в JSON Lines (UTF-8).

По умолчанию: без строк со «срезанными» статусами на корне ``Certificate`` (см. ``CERTIFICATE_ROOT_STATUSES_OMITTED_FROM_JSONL``), без псевдорегиона «за пределами РФ», компактный JSON
(без ключей с null и пустых коллекций после нормализации). Элементы ``Supplements[]`` с ``StatusName`` из
``SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL`` при том же режиме отсечения **удаляются** из массива до записи строки.
ИНН/КПП/ОГРН — только цифры после очистки или ключ не пишется; счётчик ``non_digit_ids`` в отчёте ``--report``.

Если у ``ActualEducationOrganization`` на корне и в ``Supplements[]`` совпадают UID
(``Id`` и при двусторонней заполненности ``HeadEduOrgId``), пустые **INN**/**OGRN** в карточке
приложения дополняются из корневой AEO или из **EduOrgINN** / **EduOrgOGRN** на сертификате;
затем пустые поля у **корневой** AEO — из приложения с тем же UID или с тех же EduOrg-полей.

Если у supplement-карточки **другой** ``Id`` (не совпадает с корневой AEO), пустые **INN**/**OGRN**
в ней всё равно дополняются теми же донорами (**корневая AEO**, иначе **EduOrgINN** / **EduOrgOGRN** на сертификате)
— типичные филиалы/площадки без слова «филиал» в наименовании.

Если на корне **Certificate** нет валидных **EduOrgINN** / **EduOrgOGRN**, они дополняются **снизу**:
сначала из **supplement** ``ActualEducationOrganization`` с тем же UID, что корневая AEO, иначе из **корневой** AEO.

После автоматических дозаполнений ИНН: по справочнику ``specs/certificate_inn_overrides_by_ogrn.json``
(ОГРН→ИНН, только цифры) можно записать отсутствующие **EduOrgINN** и/или **INN** корневой
``ActualEducationOrganization``, если ОГРН записи есть в таблице (редкие случаи, когда в XML есть ОГРН,
а ИНН нигде не указан). Если заданы **и** ``EduOrgOGRN``, **и** ``ActualEducationOrganization.OGRN``,
они должны совпадать, иначе правило не применяется.

Если в ``Supplements[]`` у ``ActualEducationOrganization`` **нет** валидных ИНН и ОГРН как цифр (пустая
«оболочка», часто только ``RegionName``), после остальных правил (при включённом дозаполнении AEO) поля
**INN** / **OGRN** / **KPP** копируются с корневой AEO или с **EduOrg*** на сертификате (те же доноры, что для филиалов).

Отключение автодополнения AEO/сертификата: ``--no-fill-aeo-coherent-inn-ogrn`` или API ``fill_aeo_coherent_inn_ogrn=False``.
Отключение справочника ОГРН→ИНН: ``--no-certificate-inn-overrides-by-ogrn`` или API ``certificate_inn_overrides_by_ogrn=False``.

Если у элемента ``EducationalPrograms[]`` нет непустого ``EduLevelName``, а ``ProgrammName`` после нормализации
совпадает с одной из школьных ступеней из ``PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME`` (как в выгрузке ИС ГА:
напр. «Среднее общее образование» при ``ProgrammCode`` «--»), в JSONL подставляется ``EduLevelName`` с тем же текстом.
Отключение: ``--no-fill-edulevel-from-programm-name`` или API ``fill_edulevel_from_programm_name=False``.

После записи JSONL по умолчанию выполняется **второй проход** по каждому выходному файлу: глобально по всему файлу
строится соответствие ``ProgrammCode`` (нормализованный ``XX.YY.ZZ``) → непустой ``EduLevelName`` (по частоте среди
доноров; при равенстве частот — лексикографически), затем пустые ``EduLevelName`` у программ с тем же кодом
заполняются из этого словаря. Отключение: ``--no-fill-edulevel-from-programm-code-neighbors`` или API
``fill_edulevel_from_programm_code_neighbors=False``.

Для непустого ``EduLevelName`` (в т.ч. после подстановки из ``ProgrammName``) **до записи** строки в JSONL
применяется маппинг ``specs/edu_level_names_fz273_map.json`` (явные свёртки
в ``entries``, implicit identity для строк из ``canonical_edu_level_names_fz273`` без записи в ``entries``; при
``target_edu_level_name``: ``null`` ключ ``EduLevelName`` у программы удаляется). Отключение:
``--no-normalize-edu-level-names-fz273`` или API ``normalize_edu_level_names_fz273=False``; свой JSON —
``--edu-level-names-fz273-map-json PATH``.

Отдельные ``Certificate.Id`` из ``CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST`` в JSONL **не попадают** (жёсткий блоклист в коде).

Если в ``Supplements[].EducationalPrograms[]`` (до нормализации ``EduLevelName`` по ФЗ-273)
остаётся позиция без валидного ``ProgrammCode`` (нормализованный ``XX.YY.ZZ``),
без непустого ``ProgrammName`` и без непустого ``EduLevelName`` (типичный «пустой» узел с одним ``Id`` в XML),
такая позиция **удаляется** из массива до записи строки (счётчик в отчёте ``--report``:
``stripped_degenerate_educational_programs``).

Поля наименований организации (``EduOrgFullName``, ``EduOrgShortName``, ``FullName``, ``ShortName`` и т.п.)
**не** проходят типографскую нормализацию display v1: только ``clean_text`` и ``ensure_json_safe``.
Черновик словаря отображаемых имён — отдельный контур (``org_name_normalize.py``, OpenRouter); см. ``docs/tools.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Sequence

from lxml import etree

# --- Константы типов и коллекций (согласованы со структурой эталонного XML) ---

BOOL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "IsFederal",
        "IsBranch",
        "IsForBranch",
        "IsAccredited",
        "IsCanceled",
        "IsSuspended",
    }
)
DATE_FIELDS: Final[frozenset[str]] = frozenset(
    {"IssueDate", "EndDate", "DecisionDate"}
)
ID_NUMBER_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "INN",
        "KPP",
        "OGRN",
        "EduOrgINN",
        "EduOrgKPP",
        "EduOrgOGRN",
        "IndividualEntrepreneurINN",
        "IndividualEntrepreneurEGRIP",
    }
)
COLLECTION_WRAPPERS: Final[dict[str, str]] = {
    "Supplements": "Supplement",
    "Decisions": "Decision",
    "EducationalPrograms": "EducationalProgram",
}
EMPTY_MARKERS: Final[frozenset[str]] = frozenset(
    {"", "-", "—", "–", "н/д", "нд", "нет данных", "null", "none"}
)

# Для пустых массивов, если в XML нет обёртки
COLLECTION_DEFAULTS: Final[dict[str, tuple[str, ...]]] = {
    "Certificate": ("Supplements", "Decisions"),
    "Supplement": ("EducationalPrograms",),
}

# Записи Certificate с корневым StatusName из этого множества при omit_inactive не попадают в JSONL.
CERTIFICATE_ROOT_STATUSES_OMITTED_FROM_JSONL: Final[frozenset[str]] = frozenset(
    {
        "Недействующее",
        "Прекращено",
        "Лишен аккредитации",
    }
)

# Элементы Supplements[] с таким StatusName удаляются из массива (при omit_inactive) до записи строки.
SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL: Final[frozenset[str]] = frozenset(
    {
        "Недействующее",
        "Прекращено",
        "Лишен аккредитации",
    }
)

# Обратная совместимость имён: раньше отсекался только «Недействующее» на корне.
CERTIFICATE_STATUS_OMITTED_FROM_JSONL: Final[str] = "Недействующее"

# Псевдорегион для ОО за пределами РФ; по умолчанию такие сертификаты не пишутся в JSONL (см. omit_outside_rf_region).
CERTIFICATE_REGION_NAME_OUTSIDE_RF: Final[str] = (
    "образовательные учреждения, находящиеся за пределами Российской Федерации"
)

# Совпадение ProgrammName с этой строкой при пустом EduLevelName → подставить EduLevelName (см. fill_* ниже).
# Те же канонические подписи, что в ``tools/audit_dataset_edu_program_levels.SCHOOL_LEVEL_NAMES``.
PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME: Final[frozenset[str]] = frozenset(
    {
        "Начальное общее образование",
        "Основное общее образование",
        "Среднее общее образование",
        "Дошкольное образование",
        "Общее образование",
        "Среднее (полное) общее образование",
        "Не определен",
    }
)

_PROGRAMM_CODE_TRIPLET_KEY: Final[re.Pattern[str]] = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")

# Не писать в JSONL указанные ``Certificate.Id`` (сравнение UUID без учёта регистра).
# МБОУ «Логовская ОШ» Велижского района (рег. № 1982): запись исключена из выгрузки по запросу.
CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST: Final[frozenset[str]] = frozenset(
    {"c68f57a6-e846-f050-fba2-011a5f71ab8c"}
)
_CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST_LOWER: Final[frozenset[str]] = frozenset(
    x.lower() for x in CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST
)

# Имя эталонного XML структуры (лежит в specs/xml/)
DEFAULT_SCHEMA_FILENAME: Final[str] = "data-20160908-structure-20160713.xml"

# Ручной справочник ИНН по ОГРН для исключений на уровне Certificate (лежит в specs/)
DEFAULT_CERTIFICATE_INN_OVERRIDES_BY_OGRN_FILENAME: Final[str] = (
    "certificate_inn_overrides_by_ogrn.json"
)

# Маппинг EduLevelName → целевая классификация по ФЗ-273 (specs/)
DEFAULT_EDU_LEVEL_NAMES_FZ273_MAP_FILENAME: Final[str] = "edu_level_names_fz273_map.json"

_BOOL_TRUE: Final[frozenset[str]] = frozenset(
    {"1", "true", "да", "y", "yes"}
)
_BOOL_FALSE: Final[frozenset[str]] = frozenset(
    {"0", "false", "нет", "n", "no"}
)

_EXOTIC_SPACE = re.compile(r"[\u00A0\u202F\u2007\u200B\uFEFF]")
# C0/C1 кроме \t \n \r
_CTRL_REMOVE_STR = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_CTRL_REMOVE_JSON = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS_COLLAPSE = re.compile(r"\s+")
# Z и ±HH:MM(:SS)? — безопасны для календарных дат без времени
_TZ_SUFFIX_COLON = re.compile(
    r"(?:Z|[+\-]\d{2}:\d{2}(?::\d{2})?)$",
    re.IGNORECASE,
)
# ±HHMM или ±HH — только если есть компонент времени (есть «:»), иначе ломает 15-04-2019 / 2019-04-15
_TZ_SUFFIX_NUMERIC = re.compile(r"[+\-](?:\d{4}|\d{2})$", re.IGNORECASE)
_TIME_FRACTIONAL = re.compile(r"(\d{2}:\d{2}(?::\d{2})?)\.\d+")
# Коды «XX.XX.XX» (ProgrammCode, UGSCode): в старых выгрузках шесть цифр подряд, напр. «090000»
_TRIPLET_CODE_DOTTED = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")

# --- Константы для build_graph_projection -------------------------------------

# Уровни высшего образования по ФЗ-273 (для вывода учредителя)
_GRAPH_HIGHER_EDU_LEVELS: Final[frozenset[str]] = frozenset(
    {
        "Высшее образование - бакалавриат",
        "Высшее образование - специалитет",
        "Высшее образование - магистратура",
        "Высшее образование - подготовка кадров высшей квалификации",
    }
)

# Аббревиатурные префиксы в ShortName (МБОУ, ФГБОУ ВО и т.п.) — срезаются перед проверкой длины
_GRAPH_ABBREV_PREFIX = re.compile(
    r"^("
    r"ФГБОУ|ФГАОУ|ФГКОУ|ФГБНУ|ФГАНУ|ФГБУК|ФГАУК"
    r"|ГБОУ|ГАОУ|ГКОУ|ГБНУ|ГАПОУ|ГБПОУ|ГКПОУ"
    r"|МБОУ|МАОУ|МОУ|МКОУ|МБДОУ|МАДОУ|МКДОУ"
    r"|АНО|ЧОУ|НОУ|ЧУ"
    r")\s+(ВО|СПО|ДПО|ВПО|ПО|ООП|ДО)?\s*",
    re.IGNORECASE,
)

# Полные бюрократические обёртки в FullName/ShortName («ФГБОУ ВО», «Муниципальное бюджетное ОУ» и т.п.)
_GRAPH_WRAPPER = re.compile(
    r"^(?:"
    r"(?:федеральное|государственное|муниципальное|частное|автономная некоммерческая|некоммерческое)"
    r"\s+(?:государственное\s+)?"
    r"(?:бюджетное|автономное|казённое|казенное|частное)\s+"
    r"(?:профессиональное\s+|общеобразовательное\s+|дошкольное\s+)?"
    r"(?:образовательное\s+)?"
    r"(?:учреждение|организация)"
    r"(?:\s+\S+\s+(?:области|края|республики|округа|района|города|муниципального\s+\S+))?"
    r")\s*",
    re.IGNORECASE,
)

_GRAPH_QUOTED = re.compile(r"«([^«»]+)»")  # innermost: no nested « or » in content


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def default_schema_path() -> Path:
    """Путь к эталонному XML со структурой полей."""
    return _project_root() / "specs" / "xml" / DEFAULT_SCHEMA_FILENAME


def default_certificate_inn_overrides_by_ogrn_path() -> Path:
    """Путь к JSON соответствия ОГРН→ИНН для дозаполнения на корне Certificate."""
    return _project_root() / "specs" / DEFAULT_CERTIFICATE_INN_OVERRIDES_BY_OGRN_FILENAME


def default_edu_level_names_fz273_map_path() -> Path:
    """Путь к JSON маппинга ``EduLevelName`` по ФЗ-273 (``specs/edu_level_names_fz273_map.json``)."""
    return _project_root() / "specs" / DEFAULT_EDU_LEVEL_NAMES_FZ273_MAP_FILENAME


def _certificate_id_omitted_by_jsonl_blocklist(record: dict[str, Any]) -> bool:
    """True, если ``Certificate.Id`` входит в ``CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST``."""
    cid = record.get("Id")
    if not isinstance(cid, str):
        return False
    return cid.strip().lower() in _CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST_LOWER


def load_schema_tag_names(schema_path: Path) -> set[str]:
    """Загружает множество допустимых имён тегов (localname) из эталонного XML."""
    with schema_path.open("rb") as fh:
        tree = etree.parse(fh)
    return {etree.QName(e.tag).localname for e in tree.iter() if isinstance(e.tag, str)}


def clean_text(s: str | None) -> str | None:
    """Нормализует пробелы и удаляет проблемные символы из строки.

    Для всех скалярных полей, включая наименования организаций; типографика имён (ОПФ, кавычки,
    КАПС) в конвертере **не** применяется — см. ``org_name_normalize`` и ``docs/tools.md``.

    Args:
        s: Исходная строка или None.

    Returns:
        Очищенная строка или None, если значение считается пустым.
    """
    if s is None:
        return None
    s = _EXOTIC_SPACE.sub(" ", s)
    s = _CTRL_REMOVE_STR.sub("", s)
    s = _WS_COLLAPSE.sub(" ", s).strip()
    if s.lower() in EMPTY_MARKERS:
        return None
    return s


def ensure_json_safe(obj: Any) -> Any:
    """Рекурсивно удаляет недопустимые для JSON управляющие символы из строк."""
    if isinstance(obj, str):
        return _CTRL_REMOVE_JSON.sub("", obj)
    if isinstance(obj, list):
        return [ensure_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: ensure_json_safe(v) for k, v in obj.items()}
    return obj


def omit_empty_json_values(obj: Any) -> Any:
    """Убирает ключи с None, пустыми строками и пустыми {} / [] после рекурсии.

    Пустые объекты внутри списков (например элемент только с null-полями) удаляются из списка.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            nv = omit_empty_json_values(v)
            if isinstance(nv, dict) and len(nv) == 0:
                continue
            if isinstance(nv, list) and len(nv) == 0:
                continue
            out[k] = nv
        return out
    if isinstance(obj, list):
        items: list[Any] = []
        for x in obj:
            nx = omit_empty_json_values(x)
            if isinstance(nx, dict) and len(nx) == 0:
                continue
            if isinstance(nx, list) and len(nx) == 0:
                continue
            items.append(nx)
        return items
    return obj


def cast_bool(raw: str | None, field_name: str, stats: ConversionStats) -> bool | None:
    """Приводит строку к bool; при неоднозначности — None и предупреждение."""
    if raw is None:
        return None
    key = raw.strip().lower()
    if key in _BOOL_TRUE:
        return True
    if key in _BOOL_FALSE:
        return False
    logging.warning("Не удалось распознать булево поле %s: %r", field_name, raw)
    stats.bad_booleans += 1
    return None


def _strip_timezone(s: str) -> str:
    """Удаляет суффикс таймзоны с конца строки даты/времени."""
    s = _TZ_SUFFIX_COLON.sub("", s).strip()
    if ":" in s:
        s = _TZ_SUFFIX_NUMERIC.sub("", s).rstrip()
    return s


def parse_date(raw: str | None, field_name: str, stats: ConversionStats) -> str | None:
    """Парсит дату в формат YYYY-MM-DD или возвращает очищенную строку.

    Поддерживаются смещения: ``Z``, ``±HH:MM``, ``±HHMM``, ``±HH`` (последние три —
    только при наличии времени, т.е. символа ``:`` в строке).
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    s = _TIME_FRACTIONAL.sub(r"\1", s)
    s = _strip_timezone(s)
    s = s.strip()
    formats = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
    )
    for fmt in formats:
        try:
            dt = time.strptime(s, fmt)
            return time.strftime("%Y-%m-%d", dt)
        except ValueError:
            continue
    logging.warning("Не удалось распознать дату в поле %s: %r", field_name, raw)
    stats.bad_dates += 1
    return s


def cast_id_number(
    raw: str | None, field_name: str, stats: ConversionStats
) -> str | None:
    """Удаляет пробелы и дефисы; возвращает строку только если остались одни цифры, иначе None.

    Непригодные для PK значения (буквы, запятая, «1,02E+12» и т.п.) не попадают в JSON
    как строка: ``None`` → при ``omit_null_keys`` ключ не пишется; в отчёте — ``non_digit_ids``.
    Диагностика — ``logging.debug`` (не засоряет INFO/WARN при больших выгрузках).
    """
    if raw is None:
        return None
    cleaned = re.sub(r"[\s\-]", "", raw)
    if not cleaned:
        return None
    if not cleaned.isdigit():
        logging.debug(
            "Поле %s после очистки не только цифры, в JSON будет null/ключ убран: %r",
            field_name,
            cleaned,
        )
        stats.non_digit_ids += 1
        return None
    return cleaned


def _element_text(el: etree._Element) -> str:
    """Собирает текстовое содержимое элемента, подменяя невалидные UTF-8-символы."""
    try:
        return "".join(el.itertext())
    except UnicodeDecodeError:
        raw = etree.tostring(el, encoding="utf-8", method="text")
        return raw.decode("utf-8", errors="replace")


def normalize_triplet_code(cleaned: str) -> str:
    """Компактные шесть цифр → «XX.XX.XX» (ProgrammCode, UGSCode в старых выгрузках); уже с точками не меняем."""
    if _TRIPLET_CODE_DOTTED.fullmatch(cleaned):
        return cleaned
    compact = re.sub(r"[\s\-]", "", cleaned)
    if len(compact) == 6 and compact.isdigit():
        return f"{compact[0:2]}.{compact[2:4]}.{compact[4:6]}"
    return cleaned


def normalize_programm_code(cleaned: str) -> str:
    """То же, что ``normalize_triplet_code`` (историческое имя для тестов и вызовов)."""
    return normalize_triplet_code(cleaned)


def normalize_scalar(
    tag: str, text: str | None, stats: ConversionStats
) -> str | bool | None:
    """Нормализует скалярное поле с учётом типа."""
    cleaned = clean_text(text)
    if cleaned is None:
        return None
    # Артефакт выгрузки: плейсхолдер вместо пустой квалификации
    if tag == "Qualification" and cleaned == "0":
        return None
    if tag in ("ProgrammCode", "UGSCode"):
        return normalize_triplet_code(cleaned)
    if tag in BOOL_FIELDS:
        return cast_bool(cleaned, tag, stats)
    if tag in DATE_FIELDS:
        return parse_date(cleaned, tag, stats)
    if tag in ID_NUMBER_FIELDS:
        return cast_id_number(cleaned, tag, stats)
    return cleaned


def _localname(el: etree._Element) -> str:
    return etree.QName(el.tag).localname


def _warn_unknown_tag(tag: str, path: str, stats: ConversionStats) -> None:
    if tag in stats.warned_unknown_tags:
        return
    stats.warned_unknown_tags.add(tag)
    logging.warning("Неизвестный тег (нет в эталонной схеме): %s путь=%s", tag, path)
    stats.unknown_tags.append(tag)


def elem_to_dict(
    el: etree._Element,
    stats: ConversionStats,
    schema_tags: set[str],
    path_prefix: str,
) -> dict[str, Any]:
    """Преобразует XML-элемент в словарь Python для последующей сериализации в JSON."""
    container = _localname(el)
    out: dict[str, Any] = {}

    for child in el:
        tag = _localname(child)
        child_path = f"{path_prefix}/{tag}"
        if tag not in schema_tags:
            _warn_unknown_tag(tag, child_path, stats)

        if tag in COLLECTION_WRAPPERS:
            item_tag = COLLECTION_WRAPPERS[tag]
            items: list[dict[str, Any]] = []
            for item in child:
                if _localname(item) != item_tag:
                    logging.warning(
                        "Неожиданный дочерний элемент %s внутри %s",
                        _localname(item),
                        tag,
                    )
                    continue
                items.append(
                    elem_to_dict(
                        item,
                        stats,
                        schema_tags,
                        f"{child_path}/{item_tag}",
                    )
                )
            out[tag] = items
        elif tag == "ActualEducationOrganization":
            out[tag] = elem_to_dict(
                child,
                stats,
                schema_tags,
                child_path,
            )
        else:
            sub_elems = list(child)
            if sub_elems:
                out[tag] = elem_to_dict(
                    child,
                    stats,
                    schema_tags,
                    child_path,
                )
            else:
                val = normalize_scalar(tag, _element_text(child), stats)
                out[tag] = val

    if container in COLLECTION_DEFAULTS:
        for key in COLLECTION_DEFAULTS[container]:
            out.setdefault(key, [])

    return out


_ID_WS_HYPHEN = re.compile(r"[\s\-]")


def _set_derived(obj: dict[str, Any], key: str, value: Any) -> None:
    """Записывает вычисленное значение в obj["_derived"][key]."""
    obj.setdefault("_derived", {})[key] = value


def _get_effective(obj: dict[str, Any], key: str) -> Any:
    """Возвращает значение из _derived[key] при наличии, иначе obj[key].

    Позволяет fill-функциям корректно читать значения, заполненные предыдущими
    шагами пайплайна, не смешивая их с оригинальными XML-полями.
    """
    d = obj.get("_derived")
    if isinstance(d, dict) and key in d:
        return d[key]
    return obj.get(key)


def _scalar_digits_only_string(v: Any) -> str | None:
    """Непустая строка только из цифр после удаления пробелов и дефисов (как после cast_id_number)."""
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    cleaned = _ID_WS_HYPHEN.sub("", str(v).strip())
    if cleaned and cleaned.isdigit():
        return cleaned
    return None


def _aeo_uid_token(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s.lower() if s else None


def _aeo_supplement_uid_matches_root(root_aeo: Any, sup_aeo: Any) -> bool:
    """Совпадение организации по Id и HeadEduOrgId — как в ``tools/audit_dataset_identity_fields``."""
    if not isinstance(root_aeo, dict) or not isinstance(sup_aeo, dict):
        return False
    rid = _aeo_uid_token(root_aeo.get("Id"))
    sid = _aeo_uid_token(sup_aeo.get("Id"))
    if rid is None or sid is None or rid != sid:
        return False
    rh = _aeo_uid_token(root_aeo.get("HeadEduOrgId"))
    sh = _aeo_uid_token(sup_aeo.get("HeadEduOrgId"))
    if rh and sh:
        return rh == sh
    return True


def _aeo_supplement_uid_differs_from_root(root_aeo: Any, sup_aeo: Any) -> bool:
    """Оба ``Id`` заданы и различаются (реестровый «филиал по Id»)."""
    if not isinstance(root_aeo, dict) or not isinstance(sup_aeo, dict):
        return False
    rid = _aeo_uid_token(root_aeo.get("Id"))
    sid = _aeo_uid_token(sup_aeo.get("Id"))
    return bool(rid and sid and rid != sid)


def _aeo_field_missing_for_fill(aeo: Any, field_name: str) -> bool:
    if not isinstance(aeo, dict):
        return True
    v = _get_effective(aeo, field_name)
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _donor_inn_for_supplement(root_aeo: Any, row: dict[str, Any]) -> str | None:
    if isinstance(root_aeo, dict):
        d = _scalar_digits_only_string(_get_effective(root_aeo, "INN"))
        if d:
            return d
    return _scalar_digits_only_string(_get_effective(row, "EduOrgINN"))


def _donor_ogrn_for_supplement(root_aeo: Any, row: dict[str, Any]) -> str | None:
    if isinstance(root_aeo, dict):
        d = _scalar_digits_only_string(_get_effective(root_aeo, "OGRN"))
        if d:
            return d
    return _scalar_digits_only_string(_get_effective(row, "EduOrgOGRN"))


def _donor_kpp_for_supplement(root_aeo: Any, row: dict[str, Any]) -> str | None:
    if isinstance(root_aeo, dict):
        d = _scalar_digits_only_string(_get_effective(root_aeo, "KPP"))
        if d:
            return d
    return _scalar_digits_only_string(_get_effective(row, "EduOrgKPP"))


def _first_supplement_digit_same_uid(
    row: dict[str, Any], root_aeo: Any, field: str
) -> str | None:
    for sup in row.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        saeo = sup.get("ActualEducationOrganization")
        if not isinstance(saeo, dict):
            continue
        if not _aeo_supplement_uid_matches_root(root_aeo, saeo):
            continue
        d = _scalar_digits_only_string(_get_effective(saeo, field))
        if d:
            return d
    return None


def fill_aeo_inn_ogrn_from_coherent_certificate_sources(
    record: dict[str, Any], stats: ConversionStats
) -> None:
    """Дополняет INN/OGRN в корневой и supplement ``ActualEducationOrganization``.

    Сначала — supplement при **совпадении** UID с корнем; затем supplement при **разном** ``Id`` у AEO
    (донор: корневая AEO, иначе EduOrg* на сертификате); затем — корневая AEO (донор: первая
    подходящая supplement-карточка с тем же UID, иначе EduOrg*).
    """
    root_aeo = record.get("ActualEducationOrganization")
    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        saeo = sup.get("ActualEducationOrganization")
        if not isinstance(saeo, dict):
            continue
        if not _aeo_supplement_uid_matches_root(root_aeo, saeo):
            continue
        if _aeo_field_missing_for_fill(saeo, "INN"):
            d = _donor_inn_for_supplement(root_aeo, record)
            if d:
                _set_derived(saeo, "INN", d)
                stats.aeo_coherent_fill_supplement_inn += 1
        if _aeo_field_missing_for_fill(saeo, "OGRN"):
            d = _donor_ogrn_for_supplement(root_aeo, record)
            if d:
                _set_derived(saeo, "OGRN", d)
                stats.aeo_coherent_fill_supplement_ogrn += 1

    if isinstance(root_aeo, dict):
        for sup in record.get("Supplements") or []:
            if not isinstance(sup, dict):
                continue
            saeo = sup.get("ActualEducationOrganization")
            if not isinstance(saeo, dict):
                continue
            if not _aeo_supplement_uid_differs_from_root(root_aeo, saeo):
                continue
            if _aeo_field_missing_for_fill(saeo, "INN"):
                d = _donor_inn_for_supplement(root_aeo, record)
                if d:
                    _set_derived(saeo, "INN", d)
                    stats.aeo_branch_id_mismatch_fill_supplement_inn += 1
            if _aeo_field_missing_for_fill(saeo, "OGRN"):
                d = _donor_ogrn_for_supplement(root_aeo, record)
                if d:
                    _set_derived(saeo, "OGRN", d)
                    stats.aeo_branch_id_mismatch_fill_supplement_ogrn += 1

    if not isinstance(root_aeo, dict):
        return
    if _aeo_field_missing_for_fill(root_aeo, "INN"):
        d = _first_supplement_digit_same_uid(record, root_aeo, "INN") or _scalar_digits_only_string(
            record.get("EduOrgINN")
        )
        if d:
            _set_derived(root_aeo, "INN", d)
            stats.aeo_coherent_fill_root_inn += 1
    if _aeo_field_missing_for_fill(root_aeo, "OGRN"):
        d = _first_supplement_digit_same_uid(record, root_aeo, "OGRN") or _scalar_digits_only_string(
            record.get("EduOrgOGRN")
        )
        if d:
            _set_derived(root_aeo, "OGRN", d)
            stats.aeo_coherent_fill_root_ogrn += 1


def fill_certificate_eduorg_inn_ogrn_from_near_aeo(
    record: dict[str, Any], stats: ConversionStats
) -> None:
    """Дополняет **EduOrgINN** / **EduOrgOGRN** на корне Certificate, если там нет валидных цифр.

    Источник: сначала supplement ``ActualEducationOrganization`` с тем же UID, что корневая AEO
    (как ``_first_supplement_digit_same_uid``), иначе корневая AEO. Не перезаписывает уже валидные
    значения на сертификате.
    """
    root_aeo = record.get("ActualEducationOrganization")
    if not isinstance(root_aeo, dict):
        return

    if _scalar_digits_only_string(_get_effective(record, "EduOrgINN")) is None:
        d = _first_supplement_digit_same_uid(record, root_aeo, "INN")
        if d:
            _set_derived(record, "EduOrgINN", d)
            stats.cert_eduorg_inn_backfill_from_supplement_same_uid_aeo += 1
        else:
            d2 = _scalar_digits_only_string(_get_effective(root_aeo, "INN"))
            if d2:
                _set_derived(record, "EduOrgINN", d2)
                stats.cert_eduorg_inn_backfill_from_root_aeo += 1

    if _scalar_digits_only_string(_get_effective(record, "EduOrgOGRN")) is None:
        d = _first_supplement_digit_same_uid(record, root_aeo, "OGRN")
        if d:
            _set_derived(record, "EduOrgOGRN", d)
            stats.cert_eduorg_ogrn_backfill_from_supplement_same_uid_aeo += 1
        else:
            d2 = _scalar_digits_only_string(_get_effective(root_aeo, "OGRN"))
            if d2:
                _set_derived(record, "EduOrgOGRN", d2)
                stats.cert_eduorg_ogrn_backfill_from_root_aeo += 1


def _load_certificate_inn_overrides_by_ogrn(path: Path) -> dict[str, str]:
    """Загружает словарь ОГРН→ИНН; в JSON игнорируются ключи, начинающиеся с ``_``."""
    if not path.is_file():
        logging.debug("Файл справочника ИНН по ОГРН не найден, пропуск: %s", path)
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logging.warning("Не удалось прочитать справочник ИНН по ОГРН %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        logging.warning("Справочник ИНН по ОГРН должен быть JSON-объектом: %s", path)
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        ok = _scalar_digits_only_string(k)
        iv = _scalar_digits_only_string(v)
        if ok and iv:
            out[ok] = iv
    return out


def _ogrn_for_certificate_inn_override(record: dict[str, Any]) -> str | None:
    cert_o = _scalar_digits_only_string(_get_effective(record, "EduOrgOGRN"))
    root_aeo = record.get("ActualEducationOrganization")
    root_o = (
        _scalar_digits_only_string(_get_effective(root_aeo, "OGRN"))
        if isinstance(root_aeo, dict)
        else None
    )
    if cert_o and root_o and cert_o != root_o:
        return None
    if cert_o:
        return cert_o
    if root_o:
        return root_o
    return None


def apply_certificate_inn_from_manual_ogrn_map(
    record: dict[str, Any],
    inn_by_ogrn: dict[str, str],
    stats: ConversionStats,
) -> None:
    """Дополняет **EduOrgINN** и/или INN корневой AEO по ручному соответствию ОГРН→ИНН.

    Не перезаписывает уже заданные цифровые ИНН. Если в записи указаны оба ОГРН
    (на сертификате и на корневой AEO), они должны совпадать.
    """
    if not inn_by_ogrn:
        return
    ogrn = _ogrn_for_certificate_inn_override(record)
    if not ogrn:
        return
    inn = inn_by_ogrn.get(ogrn)
    if not inn:
        return
    root_aeo = record.get("ActualEducationOrganization")

    wrote_any = False
    if _scalar_digits_only_string(_get_effective(record, "EduOrgINN")) is None:
        _set_derived(record, "EduOrgINN", inn)
        stats.cert_inn_manual_override_by_ogrn_eduorg_inn += 1
        wrote_any = True
    if isinstance(root_aeo, dict) and _scalar_digits_only_string(_get_effective(root_aeo, "INN")) is None:
        _set_derived(root_aeo, "INN", inn)
        stats.cert_inn_manual_override_by_ogrn_root_aeo_inn += 1
        wrote_any = True
    if wrote_any:
        stats.cert_inn_manual_override_by_ogrn_records += 1


def fill_degenerate_supplement_aeo_identity_from_certificate_donors(
    record: dict[str, Any], stats: ConversionStats
) -> None:
    """Дополняет **INN** / **OGRN** / **KPP** в supplement ``ActualEducationOrganization``, если оба
    идентификатора ИНН и ОГРН в карточке отсутствуют как непустые «только цифры» (пустая оболочка).

    Доноры — как ``_donor_*_for_supplement``: корневая AEO, иначе поля **EduOrg*** на сертификате.
    Выполняется после ``fill_certificate_eduorg_inn_ogrn_from_near_aeo`` и ручного ОГРН→ИНН, чтобы
    донор уже мог быть на корне. Не перезаписывает уже валидные цифровые значения.
    Вызывается только при ``fill_aeo_coherent_inn_ogrn=True`` (как остальное дозаполнение AEO).
    """
    root_aeo = record.get("ActualEducationOrganization")
    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        saeo = sup.get("ActualEducationOrganization")
        if not isinstance(saeo, dict):
            continue
        if _scalar_digits_only_string(_get_effective(saeo, "INN")) is not None:
            continue
        if _scalar_digits_only_string(_get_effective(saeo, "OGRN")) is not None:
            continue
        inn_d = _donor_inn_for_supplement(root_aeo, record)
        ogrn_d = _donor_ogrn_for_supplement(root_aeo, record)
        kpp_d = _donor_kpp_for_supplement(root_aeo, record)
        if not inn_d and not ogrn_d and not kpp_d:
            continue
        touched = False
        if inn_d:
            _set_derived(saeo, "INN", inn_d)
            stats.supplement_aeo_degenerate_shell_fill_inn += 1
            touched = True
        if ogrn_d:
            _set_derived(saeo, "OGRN", ogrn_d)
            stats.supplement_aeo_degenerate_shell_fill_ogrn += 1
            touched = True
        if kpp_d and _aeo_field_missing_for_fill(saeo, "KPP"):
            _set_derived(saeo, "KPP", kpp_d)
            stats.supplement_aeo_degenerate_shell_fill_kpp += 1
            touched = True
        if touched:
            stats.supplement_aeo_degenerate_shell_records += 1


def _educational_program_edulevel_missing(pr: dict[str, Any]) -> bool:
    """True, если у программы нет непустого EduLevelName (проверяет _derived и оригинал)."""
    v = _get_effective(pr, "EduLevelName")
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    return not str(v).strip()


def _educational_program_programm_name_empty(pr: dict[str, Any]) -> bool:
    """True, если нет непустого ProgrammName (после нормализации парсера)."""
    if "ProgrammName" not in pr:
        return True
    v = pr["ProgrammName"]
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    return not str(v).strip()


def _educational_program_is_degenerate_stub(pr: dict[str, Any]) -> bool:
    """Программа без кода, имени и уровня (часто в XML только ``Id``)."""
    if not isinstance(pr, dict):
        return False
    return (
        programm_code_lookup_key(pr.get("ProgrammCode")) is None
        and _educational_program_programm_name_empty(pr)
        and _educational_program_edulevel_missing(pr)
    )


def strip_degenerate_educational_program_stubs(
    record: dict[str, Any], stats: ConversionStats
) -> int:
    """Удаляет из ``Supplements[].EducationalPrograms[]`` дегенеративные «заглушки» (только ``Id`` и т.п.).

    Мутирует ``record``; возвращает число удалённых позиций.
    """
    removed = 0
    cert_id = record.get("Id")
    for si, sup in enumerate(record.get("Supplements") or []):
        if not isinstance(sup, dict):
            continue
        progs = sup.get("EducationalPrograms")
        if not isinstance(progs, list) or not progs:
            continue
        kept: list[Any] = []
        n_removed_here = 0
        for pi, pr in enumerate(progs):
            if isinstance(pr, dict) and _educational_program_is_degenerate_stub(pr):
                removed += 1
                n_removed_here += 1
                stats.stripped_degenerate_educational_programs += 1
                logging.debug(
                    "Удалена дегенеративная EducationalProgram: certificate_id=%r "
                    "supplement_index=%s program_index=%s program_keys=%r",
                    cert_id,
                    si,
                    pi,
                    sorted(pr.keys()),
                )
                continue
            kept.append(pr)
        if n_removed_here:
            if kept:
                sup["EducationalPrograms"] = kept
            else:
                sup.pop("EducationalPrograms", None)
    return removed


def fill_edulevel_name_from_programm_name_when_implied(
    record: dict[str, Any], stats: ConversionStats
) -> None:
    """Дополняет пустой ``EduLevelName``, если ``ProgrammName`` — известная школьная ступень реестра.

    Не перезаписывает уже непустой уровень. Мутирует ``record`` (элементы ``EducationalPrograms[]``).
    """
    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        for pr in sup.get("EducationalPrograms") or []:
            if not isinstance(pr, dict):
                continue
            if not _educational_program_edulevel_missing(pr):
                continue
            pn = pr.get("ProgrammName")
            if not isinstance(pn, str):
                continue
            t = pn.strip()
            if t in PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME:
                _set_derived(pr, "EduLevelName", t)
                stats.edulevel_from_programm_name_supplement_programs += 1


def programm_code_lookup_key(programm_code: Any) -> str | None:
    """Нормализованный ``XX.YY.ZZ`` для ключа доноров второго прохода или ``None``."""
    if not isinstance(programm_code, str):
        return None
    raw = programm_code.strip()
    if not raw:
        return None
    triplet = normalize_triplet_code(raw)
    if not _PROGRAMM_CODE_TRIPLET_KEY.fullmatch(triplet):
        return None
    return triplet


def _iter_supplement_educational_programs(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Плоский список объектов программ (словари) в ``Supplements[].EducationalPrograms[]``."""
    out: list[dict[str, Any]] = []
    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        for pr in sup.get("EducationalPrograms") or []:
            if isinstance(pr, dict):
                out.append(pr)
    return out


def _collect_edulevel_histogram_by_programm_code_pass1(path: Path) -> dict[str, Counter[str]]:
    """Первый проход по JSONL: для каждого ``ProgrammCode`` — частоты непустых ``EduLevelName``."""
    tall: dict[str, Counter[str]] = defaultdict(Counter)
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line_num, line in enumerate(fh, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                row = json.loads(s)
            except json.JSONDecodeError:
                logging.warning(
                    "EduLevelName по ProgrammCode (2-й проход), pass1: пропуск строки %s в %s",
                    line_num,
                    path,
                )
                continue
            if not isinstance(row, dict):
                continue
            for pr in _iter_supplement_educational_programs(row):
                code = programm_code_lookup_key(pr.get("ProgrammCode"))
                if code is None or _educational_program_edulevel_missing(pr):
                    continue
                v = _get_effective(pr, "EduLevelName")
                if isinstance(v, str) and v.strip():
                    tall[code][v.strip()] += 1
                elif v is not None and not isinstance(v, str):
                    tall[code][str(v).strip()] += 1
    return tall


def _pick_majority_edulevel(counter: Counter[str]) -> str | None:
    """Уровень с максимальной частотой; при равенстве — лексикографически минимальная строка."""
    if not counter:
        return None
    best = max(counter.values())
    return min(k for k, c in counter.items() if c == best)


def backfill_edulevel_name_from_programm_code_neighbors_jsonl(
    path: Path,
    *,
    omit_null_keys: bool = True,
    stats: ConversionStats | None = None,
) -> int:
    """Второй проход по готовому JSONL: глобально ``ProgrammCode`` → ``EduLevelName`` у пустых программ.

    Два чтения файла: (1) гистограмма непустых уровней по нормализованному коду; (2) подстановка
    выбранного уровня и атомарная перезапись файла через временный файл рядом с исходным.
    """
    path = path.resolve()
    if not path.is_file():
        logging.warning("EduLevelName по ProgrammCode (2-й проход): нет файла %s", path)
        return 0
    tall = _collect_edulevel_histogram_by_programm_code_pass1(path)
    code_to_level: dict[str, str] = {}
    for code, ctr in tall.items():
        picked = _pick_majority_edulevel(ctr)
        if picked is not None:
            code_to_level[code] = picked
    tmp_path = path.with_name(path.name + ".neighbor_tmp")
    filled = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as inp, tmp_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as out:
            for line_num, line in enumerate(inp, start=1):
                if not line.strip():
                    continue
                raw_line = line if line.endswith("\n") else line + "\n"
                s = line.strip()
                try:
                    row = json.loads(s)
                except json.JSONDecodeError:
                    logging.warning(
                        "EduLevelName по ProgrammCode (2-й проход), pass2: строка %s не JSON, "
                        "записана как есть (%s)",
                        line_num,
                        path,
                    )
                    out.write(raw_line)
                    continue
                if not isinstance(row, dict):
                    continue
                for pr in _iter_supplement_educational_programs(row):
                    if not _educational_program_edulevel_missing(pr):
                        continue
                    code = programm_code_lookup_key(pr.get("ProgrammCode"))
                    if code is None or code not in code_to_level:
                        continue
                    _set_derived(pr, "EduLevelName", code_to_level[code])
                    filled += 1
                # Пересчитать _graph с учётом обновлённых EduLevelName
                row["_graph"] = build_graph_projection(row)
                safe = ensure_json_safe(row)
                if omit_null_keys:
                    safe = omit_empty_json_values(safe)
                out.write(json.dumps(safe, ensure_ascii=False) + "\n")
        os.replace(tmp_path, path)
    except BaseException:  # noqa: BLE001
        if tmp_path.is_file():
            tmp_path.unlink(missing_ok=True)
        raise
    if stats is not None:
        stats.edulevel_neighbor_backfill_global_pass_programs += filled
    return filled


@dataclass(frozen=True, slots=True)
class EduLevelNamesFZ273Resolution:
    """Загруженный ``specs/edu_level_names_fz273_map.json`` для нормализации ``EduLevelName``."""

    explicit_target_by_source: dict[str, str | None]
    canonical_names: frozenset[str]


def load_edu_level_names_fz273_resolution(path: Path) -> EduLevelNamesFZ273Resolution | None:
    """Читает маппинг ФЗ-273; при ошибке или отсутствии файла возвращает ``None`` (нормализация отключена)."""
    if not path.is_file():
        logging.warning(
            "Файл маппинга EduLevelName (ФЗ-273) не найден, нормализация отключена: %s",
            path,
        )
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logging.warning("Не удалось прочитать маппинг EduLevelName (ФЗ-273) %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logging.warning("Маппинг EduLevelName (ФЗ-273) должен быть JSON-объектом: %s", path)
        return None
    canon = data.get("canonical_edu_level_names_fz273")
    if not isinstance(canon, list) or not all(isinstance(x, str) for x in canon):
        logging.warning("canonical_edu_level_names_fz273 должен быть массивом строк: %s", path)
        return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        logging.warning("entries должен быть массивом: %s", path)
        return None
    explicit: dict[str, str | None] = {}
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        src = e.get("source_registry_level_name")
        if not isinstance(src, str) or not src.strip():
            logging.warning("entries[%s]: пропуск без source_registry_level_name (%s)", i, path)
            continue
        if src in explicit:
            logging.warning("entries: дубликат source %r в %s", src, path)
            continue
        tgt = e.get("target_edu_level_name")
        if tgt is None:
            explicit[src] = None
        elif isinstance(tgt, str):
            explicit[src] = tgt.strip() or None
        else:
            logging.warning("entries[%s]: target_edu_level_name не строка и не null (%s)", i, path)
            continue
    return EduLevelNamesFZ273Resolution(
        explicit_target_by_source=explicit,
        canonical_names=frozenset(canon),
    )


def normalize_edu_level_names_via_fz273_map(
    record: dict[str, Any],
    res: EduLevelNamesFZ273Resolution,
    stats: ConversionStats,
) -> None:
    """Нормализует ``EduLevelName`` в ``Supplements[].EducationalPrograms[]`` по маппингу ФЗ-273.

    Явная запись в ``entries`` перекрывает implicit identity. ``target_edu_level_name``: ``null`` —
    ключ ``EduLevelName`` удаляется. Неизвестная непустая строка (нет в ``entries`` и не в каноне)
    сохраняется без изменения; счётчик ``edulevel_fz273_unknown_level_programs``.
    """
    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        for pr in sup.get("EducationalPrograms") or []:
            if not isinstance(pr, dict):
                continue
            v = _get_effective(pr, "EduLevelName")
            if v is None:
                continue
            raw = v.strip() if isinstance(v, str) else str(v).strip()
            if not raw:
                continue
            if raw in res.explicit_target_by_source:
                tgt = res.explicit_target_by_source[raw]
                if tgt is None:
                    # FZ-273 говорит убрать — очищаем и оригинал, и _derived
                    pr.pop("EduLevelName", None)
                    derived = pr.get("_derived")
                    if isinstance(derived, dict):
                        derived.pop("EduLevelName", None)
                    stats.edulevel_fz273_cleared_programs += 1
                elif tgt != raw:
                    _set_derived(pr, "EduLevelName", tgt)
                    stats.edulevel_fz273_renamed_programs += 1
                continue
            if raw in res.canonical_names:
                continue
            stats.edulevel_fz273_unknown_level_programs += 1


def strip_supplements_by_excluded_status(record: dict[str, Any]) -> int:
    """Удаляет из ``Supplements[]`` элементы, у которых ``StatusName`` в ``SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL``.

    Мутирует ``record``; возвращает число удалённых элементов.
    """
    sups = record.get("Supplements")
    if not isinstance(sups, list) or not sups:
        return 0
    kept: list[Any] = []
    removed = 0
    for sup in sups:
        if isinstance(sup, dict):
            st = sup.get("StatusName")
            if isinstance(st, str) and st.strip() in SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL:
                removed += 1
                continue
        kept.append(sup)
    if removed:
        record["Supplements"] = kept
    return removed


def has_valid_eduorg_ogrn(record: dict[str, Any]) -> bool:
    """True, если на корне Certificate есть непустой EduOrgOGRN из цифр после очистки.

    Согласовано с ``tools/audit_dataset_identity_fields.py`` (блок ``per_certificate.EduOrgOGRN``): пробелы и дефисы убираются,
    остаток непустой и состоит только из цифр. Проверяет _derived и оригинал.
    """
    v = _get_effective(record, "EduOrgOGRN")
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    cleaned = re.sub(r"[\s\-]", "", s)
    return bool(cleaned) and cleaned.isdigit()


@dataclass
class ConversionStats:
    """Накопление статистики конвертации."""

    per_file: dict[str, dict[str, int]] = field(default_factory=dict)
    bad_dates: int = 0
    bad_booleans: int = 0
    non_digit_ids: int = 0
    broken_records: int = 0
    unknown_tags: list[str] = field(default_factory=list)
    warned_unknown_tags: set[str] = field(default_factory=set)
    aeo_coherent_fill_supplement_inn: int = 0
    aeo_coherent_fill_supplement_ogrn: int = 0
    aeo_branch_id_mismatch_fill_supplement_inn: int = 0
    aeo_branch_id_mismatch_fill_supplement_ogrn: int = 0
    aeo_coherent_fill_root_inn: int = 0
    aeo_coherent_fill_root_ogrn: int = 0
    cert_eduorg_inn_backfill_from_supplement_same_uid_aeo: int = 0
    cert_eduorg_inn_backfill_from_root_aeo: int = 0
    cert_eduorg_ogrn_backfill_from_supplement_same_uid_aeo: int = 0
    cert_eduorg_ogrn_backfill_from_root_aeo: int = 0
    cert_inn_manual_override_by_ogrn_records: int = 0
    cert_inn_manual_override_by_ogrn_eduorg_inn: int = 0
    cert_inn_manual_override_by_ogrn_root_aeo_inn: int = 0
    supplement_aeo_degenerate_shell_records: int = 0
    supplement_aeo_degenerate_shell_fill_inn: int = 0
    supplement_aeo_degenerate_shell_fill_ogrn: int = 0
    supplement_aeo_degenerate_shell_fill_kpp: int = 0
    edulevel_from_programm_name_supplement_programs: int = 0
    stripped_degenerate_educational_programs: int = 0
    edulevel_neighbor_backfill_global_pass_programs: int = 0
    edulevel_fz273_renamed_programs: int = 0
    edulevel_fz273_cleared_programs: int = 0
    edulevel_fz273_unknown_level_programs: int = 0

    def to_report_dict(
        self,
        inputs: Sequence[str],
        elapsed: float,
    ) -> dict[str, Any]:
        """Формирует словарь для JSON-отчёта."""
        total_processed = sum(v["processed"] for v in self.per_file.values())
        total_skipped = sum(v["skipped"] for v in self.per_file.values())
        total_omitted_inactive = sum(
            int(v.get("omitted_inactive", 0)) for v in self.per_file.values()
        )
        total_omitted_outside_rf = sum(
            int(v.get("omitted_outside_rf_region", 0)) for v in self.per_file.values()
        )
        total_omitted_invalid_eduorg_ogrn = sum(
            int(v.get("omitted_invalid_eduorg_ogrn", 0)) for v in self.per_file.values()
        )
        total_stripped_supplements = sum(
            int(v.get("stripped_supplements_by_status", 0)) for v in self.per_file.values()
        )
        total_omitted_personal_blocklist = sum(
            int(v.get("omitted_certificate_personal_blocklist", 0)) for v in self.per_file.values()
        )
        return {
            "inputs": list(inputs),
            "per_file": dict(self.per_file),
            "total": {
                "processed": total_processed,
                "skipped": total_skipped,
                "omitted_inactive": total_omitted_inactive,
                "omitted_outside_rf_region": total_omitted_outside_rf,
                "omitted_invalid_eduorg_ogrn": total_omitted_invalid_eduorg_ogrn,
                "stripped_supplements_by_status": total_stripped_supplements,
                "omitted_certificate_personal_blocklist": total_omitted_personal_blocklist,
                "warnings": {
                    "bad_dates": self.bad_dates,
                    "bad_booleans": self.bad_booleans,
                    "non_digit_ids": self.non_digit_ids,
                    "broken_records": self.broken_records,
                    "unknown_tags": list(self.unknown_tags),
                },
                "aeo_coherent_inn_ogrn_fills": {
                    "supplement_ActualEducationOrganization_INN": self.aeo_coherent_fill_supplement_inn,
                    "supplement_ActualEducationOrganization_OGRN": self.aeo_coherent_fill_supplement_ogrn,
                    "supplement_ActualEducationOrganization_INN_branch_Id_not_root": (
                        self.aeo_branch_id_mismatch_fill_supplement_inn
                    ),
                    "supplement_ActualEducationOrganization_OGRN_branch_Id_not_root": (
                        self.aeo_branch_id_mismatch_fill_supplement_ogrn
                    ),
                    "root_ActualEducationOrganization_INN": self.aeo_coherent_fill_root_inn,
                    "root_ActualEducationOrganization_OGRN": self.aeo_coherent_fill_root_ogrn,
                },
                "certificate_EduOrg_inn_ogrn_backfill_from_near_aeo": {
                    "EduOrgINN_from_supplement_same_uid_AEO": (
                        self.cert_eduorg_inn_backfill_from_supplement_same_uid_aeo
                    ),
                    "EduOrgINN_from_root_AEO": self.cert_eduorg_inn_backfill_from_root_aeo,
                    "EduOrgOGRN_from_supplement_same_uid_AEO": (
                        self.cert_eduorg_ogrn_backfill_from_supplement_same_uid_aeo
                    ),
                    "EduOrgOGRN_from_root_AEO": self.cert_eduorg_ogrn_backfill_from_root_aeo,
                },
                "certificate_INN_manual_override_by_OGRN_map": {
                    "records_touched": self.cert_inn_manual_override_by_ogrn_records,
                    "EduOrgINN": self.cert_inn_manual_override_by_ogrn_eduorg_inn,
                    "root_ActualEducationOrganization_INN": (
                        self.cert_inn_manual_override_by_ogrn_root_aeo_inn
                    ),
                },
                "supplement_ActualEducationOrganization_degenerate_identity_shell_fill": {
                    "supplement_aeo_cards_touched": self.supplement_aeo_degenerate_shell_records,
                    "INN": self.supplement_aeo_degenerate_shell_fill_inn,
                    "OGRN": self.supplement_aeo_degenerate_shell_fill_ogrn,
                    "KPP": self.supplement_aeo_degenerate_shell_fill_kpp,
                },
                "educational_program_EduLevelName_from_ProgrammName_when_empty": (
                    self.edulevel_from_programm_name_supplement_programs
                ),
                "stripped_degenerate_educational_programs": (
                    self.stripped_degenerate_educational_programs
                ),
                "educational_program_EduLevelName_neighbor_backfill_from_ProgrammCode_global_pass": (
                    self.edulevel_neighbor_backfill_global_pass_programs
                ),
                "educational_program_EduLevelName_fz273_map": {
                    "renamed_to_canonical_target": self.edulevel_fz273_renamed_programs,
                    "cleared_null_target": self.edulevel_fz273_cleared_programs,
                    "unknown_registry_level_programs": self.edulevel_fz273_unknown_level_programs,
                },
                "elapsed_seconds": round(elapsed, 3),
            },
        }


def _init_file_stats(stats: ConversionStats, basename: str) -> None:
    if basename not in stats.per_file:
        stats.per_file[basename] = {
            "processed": 0,
            "skipped": 0,
            "omitted_inactive": 0,
            "omitted_outside_rf_region": 0,
            "omitted_invalid_eduorg_ogrn": 0,
            "stripped_supplements_by_status": 0,
            "omitted_certificate_personal_blocklist": 0,
        }


def annotate_derived_fields(record: dict[str, Any]) -> None:
    """Добавляет ключ ``_derived`` на корень сертификата и каждый Supplement.

    Вычисленные поля хранятся отдельно от оригинальных данных XML,
    чтобы потребитель всегда мог отличить исходное значение от вывода.

    Текущие поля:

    Supplement._derived.IsBranchSupplement : bool
        True, если приложение относится к филиалу или иному структурному
        подразделению, отличному от головной организации на сертификате.
        Сигналы (хватает любого одного):
        - ``Supplement.IsForBranch == True`` — явный флаг из XML;
        - ``Supplement.ActualEducationOrganization.Id`` не совпадает с
          ``Certificate.ActualEducationOrganization.Id`` — карточка ОО
          в приложении отличается от карточки ОО сертификата.

    Certificate._derived.HasBranchSupplements : bool
        True, если хотя бы одно приложение имеет IsBranchSupplement == True.
    """
    root_aeo_id: str | None = None
    root_aeo = record.get("ActualEducationOrganization")
    if isinstance(root_aeo, dict):
        root_aeo_id = root_aeo.get("Id")

    has_branch = False
    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        is_branch = bool(sup.get("IsForBranch"))
        if not is_branch and root_aeo_id is not None:
            sup_aeo = sup.get("ActualEducationOrganization")
            if isinstance(sup_aeo, dict):
                is_branch = sup_aeo.get("Id") != root_aeo_id
        sup.setdefault("_derived", {})["IsBranchSupplement"] = is_branch
        if is_branch:
            has_branch = True

    record.setdefault("_derived", {})["HasBranchSupplements"] = has_branch


# ---- Функции построения _graph -----------------------------------------------


def make_display_name(full_name: str | None, short_name: str | None) -> str | None:
    """Короткое отображаемое имя организации для узла графа.

    Стратегия (первый успешный вариант ≤ 60/80 символов):

    1. ShortName: снять аббревиатурный префикс (МБОУ, ФГБОУ ВО…),
       затем извлечь последний фрагмент «…» или использовать результат напрямую.
    2. FullName: последний фрагмент из «…».
    3. FullName: срезать бюрократическую обёртку.
    4. Фолбэк: первые 60 символов FullName.
    """
    if short_name:
        s = _GRAPH_ABBREV_PREFIX.sub("", short_name.strip()).strip()
        q = _GRAPH_QUOTED.findall(s)
        s_clean = q[-1].strip() if q else s.strip("«»").strip()
        if s_clean and len(s_clean) <= 60:
            return s_clean

    if not full_name:
        return (short_name or "").strip()[:60] or None

    fn = full_name.strip()

    matches = _GRAPH_QUOTED.findall(fn)
    if matches:
        candidate = matches[-1].strip()
        if 3 <= len(candidate) <= 80:
            return candidate

    clean = _GRAPH_WRAPPER.sub("", fn).strip().strip("«»").strip()
    if clean and clean != fn:
        return clean[:80]

    return fn[:60]


def _derive_founder(
    is_federal: bool | None,
    form_name: str | None,
    region_name: str | None,
    edu_levels: set[str],
) -> dict[str, str]:
    """Вывести учредителя из полей датасета (прямого поля в XML нет).

    Возвращает ``{"key": ..., "label": ...}``.
    ``key`` используется как синтетический идентификатор узла-учредителя в графе.

    Правила:
    - ``IsFederal=True`` + уровни ВО → Минобрнауки.
    - ``IsFederal=True`` без ВО → Минпросвещения.
    - ``FormName`` ∋ «муниципальное» → муниципальный учредитель региона.
    - ``FormName`` ∋ «государственное» + не федеральное → субъект РФ.
    - Частные формы → единый узел «private».
    """
    form = (form_name or "").lower()
    region = region_name or "неизвестный регион"

    if is_federal:
        if edu_levels & _GRAPH_HIGHER_EDU_LEVELS:
            return {"key": "federal:nauka", "label": "Минобрнауки России"}
        return {"key": "federal:prosv", "label": "Минпросвещения России"}

    if "муниципальное" in form:
        return {"key": f"municipal:{region}", "label": f"Муниципальный, {region}"}
    if "государственное" in form:
        return {"key": f"regional:{region}", "label": f"Субъект РФ, {region}"}
    if any(x in form for x in ("частное", "автономная некоммерческая", "некоммерческое партнёрство")):
        return {"key": "private", "label": "Частный учредитель"}

    return {"key": "unknown", "label": "Учредитель неизвестен"}


def _graph_collect_programs(
    supplement: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    """Собрать уникальные edu_levels и programs (с кодами) из одного supplement."""
    edu_levels: list[str] = []
    programs: list[dict[str, str]] = []
    seen_level: set[str] = set()
    seen_code_level: set[tuple[str, str]] = set()

    for prog in supplement.get("EducationalPrograms") or []:
        if not isinstance(prog, dict):
            continue
        level = _get_effective(prog, "EduLevelName") or ""
        if level and level not in seen_level:
            seen_level.add(level)
            edu_levels.append(level)

        code = prog.get("ProgrammCode")
        if not code or not _PROGRAMM_CODE_TRIPLET_KEY.match(code):
            continue
        key = (code, level)
        if key in seen_code_level:
            continue
        seen_code_level.add(key)

        # UGSCode из поля или выведен из первых двух цифр ProgrammCode
        ugs = prog.get("UGSCode")
        if not ugs or not _PROGRAMM_CODE_TRIPLET_KEY.match(ugs):
            parts = code.split(".")
            ugs = f"{parts[0]}.00.00" if len(parts) == 3 else None

        entry: dict[str, str] = {"code": code}
        if ugs:
            entry["ugs_code"] = ugs
        if level:
            entry["edu_level"] = level
        programs.append(entry)

    return edu_levels, programs


def build_graph_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Материализовать проекцию ``_graph`` для построения графа.

    Вызывать после ``annotate_derived_fields`` — когда все ``_derived`` поля выставлены.
    При использовании второго прохода (backfill EduLevelName по соседям) нужно вызвать
    повторно после обновления ``_derived.EduLevelName`` в программах.

    Структура результата::

        {
          "org": {"ogrn", "inn", "display_name", "founder_key", "founder_label"},
          "region": str,
          "edu_levels": [str, ...],          # уникальные уровни основной org
          "programs": [{"code", "ugs_code", "edu_level"}, ...],
          "branches": [                       # supplements с IsBranchSupplement=true,
            {"ogrn", "inn", "display_name",  #   сгруппированные по effective OGRN
             "edu_levels", "programs"}, ...]
        }

    Пустые списки и None-значения не включаются.
    """
    aeo = record.get("ActualEducationOrganization") or {}

    ogrn = _get_effective(record, "EduOrgOGRN")
    inn = _get_effective(record, "EduOrgINN")
    full_name = aeo.get("FullName") or record.get("EduOrgFullName")
    short_name = aeo.get("ShortName") or record.get("EduOrgShortName")
    display_name = make_display_name(full_name, short_name)
    region = record.get("RegionName")

    head_levels: list[str] = []
    head_programs: list[dict[str, str]] = []
    seen_level: set[str] = set()
    seen_code_level: set[tuple[str, str]] = set()
    branch_map: dict[Any, dict[str, Any]] = {}

    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        is_branch = bool((sup.get("_derived") or {}).get("IsBranchSupplement"))
        sup_levels, sup_programs = _graph_collect_programs(sup)

        if not is_branch:
            for lvl in sup_levels:
                if lvl not in seen_level:
                    seen_level.add(lvl)
                    head_levels.append(lvl)
            for p in sup_programs:
                k = (p["code"], p.get("edu_level", ""))
                if k not in seen_code_level:
                    seen_code_level.add(k)
                    head_programs.append(p)
        else:
            sup_aeo = sup.get("ActualEducationOrganization") or {}
            b_ogrn = _get_effective(sup_aeo, "OGRN")
            b_key = b_ogrn or sup_aeo.get("Id") or id(sup)
            if b_key not in branch_map:
                branch_map[b_key] = {
                    "ogrn": b_ogrn,
                    "inn": _get_effective(sup_aeo, "INN"),
                    "display_name": make_display_name(
                        sup_aeo.get("FullName"), sup_aeo.get("ShortName")
                    ),
                    "_seen_level": set(),
                    "_seen_code_level": set(),
                    "edu_levels": [],
                    "programs": [],
                }
            b = branch_map[b_key]
            for lvl in sup_levels:
                if lvl not in b["_seen_level"]:
                    b["_seen_level"].add(lvl)
                    b["edu_levels"].append(lvl)
            for p in sup_programs:
                k = (p["code"], p.get("edu_level", ""))
                if k not in b["_seen_code_level"]:
                    b["_seen_code_level"].add(k)
                    b["programs"].append(p)

    founder = _derive_founder(
        is_federal=record.get("IsFederal"),
        form_name=aeo.get("FormName"),
        region_name=region,
        edu_levels=set(head_levels),
    )

    org: dict[str, Any] = {}
    if ogrn:
        org["ogrn"] = ogrn
    if inn:
        org["inn"] = inn
    if display_name:
        org["display_name"] = display_name
    org["founder_key"] = founder["key"]
    org["founder_label"] = founder["label"]

    proj: dict[str, Any] = {}
    if org:
        proj["org"] = org
    if region:
        proj["region"] = region
    if head_levels:
        proj["edu_levels"] = head_levels
    if head_programs:
        proj["programs"] = head_programs

    if branch_map:
        branches = []
        for b in branch_map.values():
            b_clean = {k: v for k, v in b.items() if not k.startswith("_") and v is not None and v != []}
            if b_clean:
                branches.append(b_clean)
        if branches:
            proj["branches"] = branches

    return proj


def convert_one(
    input_path: Path,
    out_fh,
    *,
    stats: ConversionStats,
    schema_tags: set[str],
    schema_path: Path,
    progress_every: int,
    limit: int | None,
    strict: bool,
    omit_inactive: bool = True,
    omit_outside_rf_region: bool = True,
    omit_invalid_eduorg_ogrn: bool = False,
    source_basename: str | None = None,
    omit_null_keys: bool = True,
    fill_aeo_coherent_inn_ogrn: bool = True,
    fill_edulevel_from_programm_name: bool = True,
    manual_inn_by_ogrn: dict[str, str] | None = None,
    edu_level_fz273: EduLevelNamesFZ273Resolution | None = None,
) -> None:
    """Конвертирует один XML-файл, дописывая строки JSON в открытый файловый объект."""
    _ = schema_path  # зарезервировано для расширений / совместимости API
    base = source_basename or input_path.name
    _init_file_stats(stats, base)
    processed = 0
    skipped = 0
    inn_map = manual_inn_by_ogrn or {}

    with input_path.open("rb") as fh:
        context = etree.iterparse(
            fh,
            events=("end",),
            tag="Certificate",
            huge_tree=True,
            recover=True,
        )

        for _event, elem in context:
            try:
                if limit is not None and processed >= limit:
                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]
                    break

                record = elem_to_dict(
                    elem,
                    stats,
                    schema_tags,
                    "Certificate",
                )
                if omit_inactive:
                    n_stripped = strip_supplements_by_excluded_status(record)
                    if n_stripped:
                        stats.per_file[base]["stripped_supplements_by_status"] = int(
                            stats.per_file[base].get("stripped_supplements_by_status", 0)
                        ) + int(n_stripped)
                if fill_aeo_coherent_inn_ogrn:
                    fill_aeo_inn_ogrn_from_coherent_certificate_sources(record, stats)
                    fill_certificate_eduorg_inn_ogrn_from_near_aeo(record, stats)
                if inn_map:
                    apply_certificate_inn_from_manual_ogrn_map(record, inn_map, stats)
                if fill_aeo_coherent_inn_ogrn:
                    fill_degenerate_supplement_aeo_identity_from_certificate_donors(record, stats)
                if fill_edulevel_from_programm_name:
                    fill_edulevel_name_from_programm_name_when_implied(record, stats)
                # Удаляем «заглушки» до нормализации EduLevelName по ФЗ-273:
                # если маппинг позже удалит ключ (target=null), саму программу не считаем дегенеративной.
                strip_degenerate_educational_program_stubs(record, stats)
                if edu_level_fz273 is not None:
                    normalize_edu_level_names_via_fz273_map(record, edu_level_fz273, stats)
                annotate_derived_fields(record)
                if omit_inactive and (
                    record.get("StatusName") in CERTIFICATE_ROOT_STATUSES_OMITTED_FROM_JSONL
                ):
                    stats.per_file[base]["omitted_inactive"] += 1
                elif omit_outside_rf_region and (
                    record.get("RegionName") == CERTIFICATE_REGION_NAME_OUTSIDE_RF
                ):
                    stats.per_file[base]["omitted_outside_rf_region"] += 1
                elif omit_invalid_eduorg_ogrn and not has_valid_eduorg_ogrn(record):
                    stats.per_file[base]["omitted_invalid_eduorg_ogrn"] += 1
                elif _certificate_id_omitted_by_jsonl_blocklist(record):
                    stats.per_file[base]["omitted_certificate_personal_blocklist"] += 1
                else:
                    record["_graph"] = build_graph_projection(record)
                    safe = ensure_json_safe(record)
                    if omit_null_keys:
                        safe = omit_empty_json_values(safe)
                    line = json.dumps(safe, ensure_ascii=False) + "\n"
                    out_fh.write(line)
                    processed += 1
                    stats.per_file[base]["processed"] = processed
                    if progress_every and processed % progress_every == 0:
                        logging.info("Обработано записей из %s: %s", base, processed)
            except Exception as exc:  # noqa: BLE001 — устойчивость к битым записям
                skipped += 1
                stats.broken_records += 1
                stats.per_file[base]["skipped"] = skipped
                logging.warning(
                    "Пропуск записи #%s из %s: %s",
                    processed + skipped,
                    base,
                    exc,
                )
                if strict:
                    raise
            finally:
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]

    stats.per_file[base]["processed"] = processed
    stats.per_file[base]["skipped"] = skipped


def convert_many(
    inputs: Sequence[Path],
    output: Path | None,
    *,
    merged: bool,
    out_dir: Path,
    progress_every: int,
    limit: int | None,
    strict: bool,
    schema_path: Path,
    omit_inactive: bool = True,
    omit_outside_rf_region: bool = True,
    omit_invalid_eduorg_ogrn: bool = False,
    omit_null_keys: bool = True,
    fill_aeo_coherent_inn_ogrn: bool = True,
    fill_edulevel_from_programm_name: bool = True,
    fill_edulevel_from_programm_code_neighbors: bool = True,
    certificate_inn_overrides_by_ogrn: bool = True,
    certificate_inn_overrides_by_ogrn_json: Path | None = None,
    normalize_edu_level_names_fz273: bool = True,
    edu_level_names_fz273_map_json: Path | None = None,
) -> ConversionStats:
    """Конвертирует один или несколько входных XML.

    Args:
        inputs: Входные файлы.
        output: Путь к одному .jsonl при ``merged=True`` (обязателен).
        merged: True — все входы в один ``output``. False — по одному
            ``stem.jsonl`` в ``out_dir`` на вход (нужно не меньше двух файлов).
        out_dir: Каталог для раздельных выходов при ``merged=False``.
        omit_inactive: Если True, не записывать в JSONL сертификаты, у которых на корне
            ``StatusName`` входит в ``CERTIFICATE_ROOT_STATUSES_OMITTED_FROM_JSONL``
            (в т.ч. «Недействующее», «Прекращено», «Лишен аккредитации»); из ``Supplements[]`` при этом
            удаляются элементы с ``StatusName`` из ``SUPPLEMENT_STATUSES_STRIPPED_FROM_JSONL``.
            По умолчанию **True**; полный снимок как в XML (все статусы на корне и все приложения) —
            передайте ``omit_inactive=False`` или в CLI флаг ``--include-inactive``.
        omit_outside_rf_region: Если True, не записывать сертификаты, у которых на корне
            ``RegionName`` совпадает с ``CERTIFICATE_REGION_NAME_OUTSIDE_RF``.
            По умолчанию **True**; полный снимок по региону как в XML —
            передайте ``omit_outside_rf_region=False`` или в CLI ``--include-outside-rf-region``.
        omit_invalid_eduorg_ogrn: Если True, не записывать сертификаты без валидного
            корневого ``EduOrgOGRN`` (непустая строка из цифр после удаления пробелов
            и дефисов). По умолчанию **False** — полный снимок как в XML.
        omit_null_keys: Если True, перед записью строки убрать null, пустые строки
            и пустые вложенные dict/list (см. ``omit_empty_json_values``).
            По умолчанию **True**; все ключи как у парсера —
            ``omit_null_keys=False`` или ``--include-null-keys``.
        fill_aeo_coherent_inn_ogrn: Если True, после парсера XML дополнять пустые **INN**/**OGRN**
            в ``ActualEducationOrganization`` (корень и приложения) при совпадении UID донорами
            с корневой AEO, с supplement-карточек с тем же UID и с **EduOrgINN** / **EduOrgOGRN**.
            По умолчанию **True**; отключить — ``fill_aeo_coherent_inn_ogrn=False`` или CLI
            ``--no-fill-aeo-coherent-inn-ogrn``.
        fill_edulevel_from_programm_name: Если True, при пустом **EduLevelName** у программы
            подставлять его из **ProgrammName**, когда последний совпадает с одной из школьных
            ступеней ``PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME``. По умолчанию **True**;
            отключить — ``fill_edulevel_from_programm_name=False`` или CLI
            ``--no-fill-edulevel-from-programm-name``.
        fill_edulevel_from_programm_code_neighbors: Если True, после записи каждого выходного JSONL
            выполнить второй проход по файлу: глобально по ``ProgrammCode`` подставить ``EduLevelName`` из
            других программ того же файла (мода по частоте). По умолчанию **True**; отключить —
            ``fill_edulevel_from_programm_code_neighbors=False`` или CLI
            ``--no-fill-edulevel-from-programm-code-neighbors``.
        normalize_edu_level_names_fz273: Если True, после этого нормализовать непустой **EduLevelName**
            по ``specs/edu_level_names_fz273_map.json`` (или путь из ``edu_level_names_fz273_map_json``).
            По умолчанию **True**; отключить — ``normalize_edu_level_names_fz273=False`` или CLI
            ``--no-normalize-edu-level-names-fz273``.
        edu_level_names_fz273_map_json: Явный путь к JSON маппинга; при ``None`` — ``specs/edu_level_names_fz273_map.json``.
        certificate_inn_overrides_by_ogrn: Если True, после автоматических дозаполнений ИНН
            применять JSON ``specs/certificate_inn_overrides_by_ogrn.json`` (или путь из
            ``certificate_inn_overrides_by_ogrn_json``): ОГРН→ИНН для пустых **EduOrgINN** / INN корневой AEO.
        certificate_inn_overrides_by_ogrn_json: Явный путь к JSON; при ``None`` используется файл в ``specs/``.
    """
    if not inputs:
        raise ValueError("Нет входных файлов")
    schema_tags = load_schema_tag_names(schema_path)
    stats = ConversionStats()

    manual_inn_by_ogrn: dict[str, str] = {}
    if certificate_inn_overrides_by_ogrn:
        ogrn_json_path = (
            certificate_inn_overrides_by_ogrn_json
            or default_certificate_inn_overrides_by_ogrn_path()
        ).resolve()
        manual_inn_by_ogrn = _load_certificate_inn_overrides_by_ogrn(ogrn_json_path)
        if manual_inn_by_ogrn:
            logging.info(
                "Справочник ИНН по ОГРН: %s записей (%s)",
                len(manual_inn_by_ogrn),
                ogrn_json_path,
            )

    edu_level_fz273: EduLevelNamesFZ273Resolution | None = None
    if normalize_edu_level_names_fz273:
        fz273_path = (
            edu_level_names_fz273_map_json or default_edu_level_names_fz273_map_path()
        ).resolve()
        edu_level_fz273 = load_edu_level_names_fz273_resolution(fz273_path)
        if edu_level_fz273 is not None:
            logging.info(
                "Маппинг EduLevelName (ФЗ-273): %s явных source, %s имён в каноне (%s)",
                len(edu_level_fz273.explicit_target_by_source),
                len(edu_level_fz273.canonical_names),
                fz273_path,
            )

    if not merged:
        if len(inputs) < 2:
            raise ValueError("Для раздельных выходов укажите не меньше двух входных файлов")
        out_dir.mkdir(parents=True, exist_ok=True)
        for inp in inputs:
            stem = inp.stem
            out_path = out_dir / f"{stem}.jsonl"
            with out_path.open("w", encoding="utf-8", newline="\n") as fh:
                convert_one(
                    inp,
                    fh,
                    stats=stats,
                    schema_tags=schema_tags,
                    schema_path=schema_path,
                    progress_every=progress_every,
                    limit=limit,
                    strict=strict,
                    omit_inactive=omit_inactive,
                    omit_outside_rf_region=omit_outside_rf_region,
                    omit_invalid_eduorg_ogrn=omit_invalid_eduorg_ogrn,
                    omit_null_keys=omit_null_keys,
                    fill_aeo_coherent_inn_ogrn=fill_aeo_coherent_inn_ogrn,
                    fill_edulevel_from_programm_name=fill_edulevel_from_programm_name,
                    manual_inn_by_ogrn=manual_inn_by_ogrn,
                    edu_level_fz273=edu_level_fz273,
                )
    else:
        if output is None:
            raise ValueError("Нужен путь -o/--output для объединённого выхода")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="\n") as fh:
            for inp in inputs:
                convert_one(
                    inp,
                    fh,
                    stats=stats,
                    schema_tags=schema_tags,
                    schema_path=schema_path,
                    progress_every=progress_every,
                    limit=limit,
                    strict=strict,
                    omit_inactive=omit_inactive,
                    omit_outside_rf_region=omit_outside_rf_region,
                    omit_invalid_eduorg_ogrn=omit_invalid_eduorg_ogrn,
                    omit_null_keys=omit_null_keys,
                    fill_aeo_coherent_inn_ogrn=fill_aeo_coherent_inn_ogrn,
                    fill_edulevel_from_programm_name=fill_edulevel_from_programm_name,
                    manual_inn_by_ogrn=manual_inn_by_ogrn,
                    edu_level_fz273=edu_level_fz273,
                )

    if fill_edulevel_from_programm_code_neighbors:
        outpaths: list[Path] = []
        if merged:
            if output is None:
                raise ValueError("Внутренняя ошибка: merged без output")
            outpaths = [output.resolve()]
        else:
            outpaths = [(out_dir / f"{inp.stem}.jsonl").resolve() for inp in inputs]
        for op in outpaths:
            n = backfill_edulevel_name_from_programm_code_neighbors_jsonl(
                op,
                omit_null_keys=omit_null_keys,
                stats=stats,
            )
            logging.info(
                "EduLevelName по ProgrammCode (глобальный 2-й проход): исправлено программ: %s (%s)",
                n,
                op,
            )

    return stats


def _configure_logging(log_file: Path | None) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Потоковая конвертация XML реестра аккредитации в JSON Lines.",
    )
    p.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Один или несколько входных XML-файлов",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Выходной .jsonl при --merged или при одном входе (иначе out/<имя_входа>.jsonl)",
    )
    p.add_argument(
        "--merged",
        action="store_true",
        help="Слить все входные XML в один .jsonl (требуется -o/--output)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("out"),
        help="Каталог для раздельных .jsonl при нескольких входах без --merged (по умолчанию out/)",
    )
    p.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Путь к эталонному XML со структурой полей (по умолчанию файл в корне проекта)",
    )
    p.add_argument(
        "--progress-every",
        type=int,
        default=10_000,
        metavar="N",
        help="Логировать прогресс каждые N записей (0 — отключить)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Максимум записей на каждый входной файл",
    )
    p.add_argument("--log-file", type=Path, default=None, help="Дополнительный лог-файл")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Прервать выполнение при ошибке обработки записи",
    )
    p.add_argument(
        "--omit-inactive",
        action="store_true",
        help=(
            "Не записывать в JSONL сертификаты с корневым StatusName из набора "
            "«Недействующее», «Прекращено», «Лишен аккредитации» и удалять из Supplements[] "
            "приложения с StatusName из «Недействующее», «Прекращено», «Лишен аккредитации» "
            "(это поведение по умолчанию; флаг можно не указывать)"
        ),
    )
    p.add_argument(
        "--omit-outside-rf-region",
        action="store_true",
        help=(
            "Не записывать сертификаты с RegionName «образовательные учреждения, "
            "находящиеся за пределами Российской Федерации» на корне "
            "(это поведение по умолчанию; флаг можно не указывать)"
        ),
    )
    p.add_argument(
        "--omit-invalid-eduorg-ogrn",
        action="store_true",
        help=(
            "Не записывать сертификаты без валидного корневого EduOrgOGRN: пусто, "
            "нет ключа или после удаления пробелов/дефисов не только цифры "
            "(как в ``tools/audit_dataset_identity_fields.py`` для ``EduOrgOGRN``; по умолчанию такие строки включаются)"
        ),
    )
    p.add_argument(
        "--include-inactive",
        action="store_true",
        help=(
            "Полный снимок по статусу как в XML: на корне Certificate — любой StatusName; "
            "в Supplements[] — все элементы без удаления по StatusName приложения"
        ),
    )
    p.add_argument(
        "--include-outside-rf-region",
        action="store_true",
        help=(
            "Включать в JSONL и сертификаты с псевдорегионом «за пределами РФ» на корневом "
            "RegionName — полный снимок по региону, как в XML"
        ),
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Путь к JSON-файлу со сводной статистикой",
    )
    p.add_argument(
        "--omit-null-keys",
        action="store_true",
        help=(
            "Не писать в JSON ключи со значением null, пустой строкой и пустыми "
            "вложенными объектами/массивами после очистки (это поведение по умолчанию; "
            "флаг можно не указывать)"
        ),
    )
    p.add_argument(
        "--include-null-keys",
        action="store_true",
        help=(
            "Писать в JSON ключи со значением null и пустые массивы/объекты после нормализации "
            "(полный снимок полей, как сразу после парсера XML)"
        ),
    )
    p.add_argument(
        "--no-fill-aeo-coherent-inn-ogrn",
        action="store_true",
        help=(
            "Не дополнять INN/OGRN в ActualEducationOrganization при совпадении UID "
            "и ветке «филиал по Id»; не поднимать EduOrgINN/EduOrgOGRN на Certificate "
            "из supplement/корневой AEO "
            "(по умолчанию дополнение из корневой AEO, EduOrgINN/EduOrgOGRN и supplement-карточек включено)"
        ),
    )
    p.add_argument(
        "--no-fill-edulevel-from-programm-name",
        action="store_true",
        help=(
            "Не подставлять EduLevelName из ProgrammName для школьных ступеней "
            "(см. PROGRAMM_NAMES_THAT_IMPLY_EQUAL_EDU_LEVEL_NAME в convert.py), "
            "если в XML у программы уровень пустой"
        ),
    )
    p.add_argument(
        "--no-fill-edulevel-from-programm-code-neighbors",
        action="store_true",
        help=(
            "Не выполнять второй проход по выходному JSONL: глобальная подстановка пустого EduLevelName "
            "из других строк файла с тем же ProgrammCode (нормализованный XX.YY.ZZ)"
        ),
    )
    p.add_argument(
        "--no-normalize-edu-level-names-fz273",
        action="store_true",
        help=(
            "Не нормализовать непустой EduLevelName в EducationalPrograms по JSON "
            "specs/edu_level_names_fz273_map.json (цели по ФЗ-273)"
        ),
    )
    p.add_argument(
        "--edu-level-names-fz273-map-json",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Путь к JSON маппинга EduLevelName по ФЗ-273; по умолчанию "
            "specs/edu_level_names_fz273_map.json в каталоге проекта"
        ),
    )
    p.add_argument(
        "--certificate-inn-overrides-by-ogrn-json",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "JSON-объект «ОГРН (строка из цифр) → ИНН» для дозаполнения пустых EduOrgINN и INN "
            "корневой ActualEducationOrganization после автоматических правил; по умолчанию — "
            "specs/certificate_inn_overrides_by_ogrn.json в каталоге проекта (если файл существует)"
        ),
    )
    p.add_argument(
        "--no-certificate-inn-overrides-by-ogrn",
        action="store_true",
        help="Не применять ручной справочник ИНН по ОГРН (см. --certificate-inn-overrides-by-ogrn-json)",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = _parse_args(argv)
    _configure_logging(args.log_file)

    schema_path = args.schema or default_schema_path()
    if not schema_path.is_file():
        logging.error("Не найден эталонный XML схемы: %s", schema_path)
        return 2

    inputs = [p.resolve() for p in args.inputs]
    for p in inputs:
        if not p.is_file():
            logging.error("Входной файл не найден: %s", p)
            return 2

    out_dir = args.out_dir.resolve()
    multi = len(inputs) > 1

    if args.merged and not multi:
        logging.error("Флаг --merged используется только при нескольких входных файлах")
        return 2
    if multi and args.merged and args.output is None:
        logging.error("При --merged и нескольких входах укажите -o/--output")
        return 2
    if multi and not args.merged and args.output is not None:
        logging.error(
            "При нескольких входах без --merged путь -o не используется; "
            "выходы — out-dir/<имя>.jsonl. Для слияния в один файл укажите --merged и -o"
        )
        return 2

    if multi and not args.merged:
        out_path: Path | None = None
        merged = False
    elif multi and args.merged:
        out_path = args.output.resolve() if args.output else None
        merged = True
    else:
        out_path = (args.output or (out_dir / f"{inputs[0].stem}.jsonl")).resolve()
        merged = True

    if args.omit_inactive and args.include_inactive:
        logging.error("Нельзя одновременно указывать --omit-inactive и --include-inactive")
        return 2
    if args.omit_outside_rf_region and args.include_outside_rf_region:
        logging.error(
            "Нельзя одновременно указывать --omit-outside-rf-region и --include-outside-rf-region"
        )
        return 2
    if args.omit_null_keys and args.include_null_keys:
        logging.error("Нельзя одновременно указывать --omit-null-keys и --include-null-keys")
        return 2

    omit_inactive = not bool(args.include_inactive)
    omit_outside_rf_region = not bool(args.include_outside_rf_region)
    omit_null_keys = not bool(args.include_null_keys)

    cert_inn_ov_json = args.certificate_inn_overrides_by_ogrn_json
    if cert_inn_ov_json is not None:
        cert_inn_ov_json = cert_inn_ov_json.resolve()

    fz273_json = args.edu_level_names_fz273_map_json
    if fz273_json is not None:
        fz273_json = fz273_json.resolve()

    t0 = time.perf_counter()
    try:
        stats = convert_many(
            inputs,
            out_path,
            merged=merged,
            out_dir=out_dir,
            progress_every=args.progress_every,
            limit=args.limit,
            strict=args.strict,
            schema_path=schema_path.resolve(),
            omit_inactive=omit_inactive,
            omit_outside_rf_region=omit_outside_rf_region,
            omit_invalid_eduorg_ogrn=bool(args.omit_invalid_eduorg_ogrn),
            omit_null_keys=omit_null_keys,
            fill_aeo_coherent_inn_ogrn=not bool(args.no_fill_aeo_coherent_inn_ogrn),
            fill_edulevel_from_programm_name=not bool(args.no_fill_edulevel_from_programm_name),
            fill_edulevel_from_programm_code_neighbors=not bool(
                args.no_fill_edulevel_from_programm_code_neighbors
            ),
            certificate_inn_overrides_by_ogrn=not bool(args.no_certificate_inn_overrides_by_ogrn),
            certificate_inn_overrides_by_ogrn_json=cert_inn_ov_json,
            normalize_edu_level_names_fz273=not bool(args.no_normalize_edu_level_names_fz273),
            edu_level_names_fz273_map_json=fz273_json,
        )
    except ValueError as ve:
        logging.error("%s", ve)
        return 2
    except Exception as exc:  # noqa: BLE001
        logging.error("Конвертация прервана: %s", exc)
        return 1

    elapsed = time.perf_counter() - t0
    rep = stats.to_report_dict([str(p) for p in inputs], elapsed)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    sys.stderr.write(
        json.dumps(rep, ensure_ascii=False, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
