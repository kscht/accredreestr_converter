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

Отдельные ``Certificate.Id`` из ``CERTIFICATE_IDS_OMITTED_FROM_JSONL_BLOCKLIST`` в JSONL **не попадают** (жёсткий блоклист в коде).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
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


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def default_schema_path() -> Path:
    """Путь к эталонному XML со структурой полей."""
    return _project_root() / "specs" / "xml" / DEFAULT_SCHEMA_FILENAME


def default_certificate_inn_overrides_by_ogrn_path() -> Path:
    """Путь к JSON соответствия ОГРН→ИНН для дозаполнения на корне Certificate."""
    return _project_root() / "specs" / DEFAULT_CERTIFICATE_INN_OVERRIDES_BY_OGRN_FILENAME


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
    if not isinstance(aeo, dict) or field_name not in aeo:
        return True
    v = aeo.get(field_name)
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _donor_inn_for_supplement(root_aeo: Any, row: dict[str, Any]) -> str | None:
    if isinstance(root_aeo, dict):
        d = _scalar_digits_only_string(root_aeo.get("INN"))
        if d:
            return d
    return _scalar_digits_only_string(row.get("EduOrgINN"))


def _donor_ogrn_for_supplement(root_aeo: Any, row: dict[str, Any]) -> str | None:
    if isinstance(root_aeo, dict):
        d = _scalar_digits_only_string(root_aeo.get("OGRN"))
        if d:
            return d
    return _scalar_digits_only_string(row.get("EduOrgOGRN"))


def _donor_kpp_for_supplement(root_aeo: Any, row: dict[str, Any]) -> str | None:
    if isinstance(root_aeo, dict):
        d = _scalar_digits_only_string(root_aeo.get("KPP"))
        if d:
            return d
    return _scalar_digits_only_string(row.get("EduOrgKPP"))


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
        d = _scalar_digits_only_string(saeo.get(field))
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
                saeo["INN"] = d
                stats.aeo_coherent_fill_supplement_inn += 1
        if _aeo_field_missing_for_fill(saeo, "OGRN"):
            d = _donor_ogrn_for_supplement(root_aeo, record)
            if d:
                saeo["OGRN"] = d
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
                    saeo["INN"] = d
                    stats.aeo_branch_id_mismatch_fill_supplement_inn += 1
            if _aeo_field_missing_for_fill(saeo, "OGRN"):
                d = _donor_ogrn_for_supplement(root_aeo, record)
                if d:
                    saeo["OGRN"] = d
                    stats.aeo_branch_id_mismatch_fill_supplement_ogrn += 1

    if not isinstance(root_aeo, dict):
        return
    if _aeo_field_missing_for_fill(root_aeo, "INN"):
        d = _first_supplement_digit_same_uid(record, root_aeo, "INN") or _scalar_digits_only_string(
            record.get("EduOrgINN")
        )
        if d:
            root_aeo["INN"] = d
            stats.aeo_coherent_fill_root_inn += 1
    if _aeo_field_missing_for_fill(root_aeo, "OGRN"):
        d = _first_supplement_digit_same_uid(record, root_aeo, "OGRN") or _scalar_digits_only_string(
            record.get("EduOrgOGRN")
        )
        if d:
            root_aeo["OGRN"] = d
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

    if _scalar_digits_only_string(record.get("EduOrgINN")) is None:
        d = _first_supplement_digit_same_uid(record, root_aeo, "INN")
        if d:
            record["EduOrgINN"] = d
            stats.cert_eduorg_inn_backfill_from_supplement_same_uid_aeo += 1
        else:
            d2 = _scalar_digits_only_string(root_aeo.get("INN"))
            if d2:
                record["EduOrgINN"] = d2
                stats.cert_eduorg_inn_backfill_from_root_aeo += 1

    if _scalar_digits_only_string(record.get("EduOrgOGRN")) is None:
        d = _first_supplement_digit_same_uid(record, root_aeo, "OGRN")
        if d:
            record["EduOrgOGRN"] = d
            stats.cert_eduorg_ogrn_backfill_from_supplement_same_uid_aeo += 1
        else:
            d2 = _scalar_digits_only_string(root_aeo.get("OGRN"))
            if d2:
                record["EduOrgOGRN"] = d2
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
    cert_o = _scalar_digits_only_string(record.get("EduOrgOGRN"))
    root_aeo = record.get("ActualEducationOrganization")
    root_o = (
        _scalar_digits_only_string(root_aeo.get("OGRN"))
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
    if _scalar_digits_only_string(record.get("EduOrgINN")) is None:
        record["EduOrgINN"] = inn
        stats.cert_inn_manual_override_by_ogrn_eduorg_inn += 1
        wrote_any = True
    if isinstance(root_aeo, dict) and _scalar_digits_only_string(root_aeo.get("INN")) is None:
        root_aeo["INN"] = inn
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
        if _scalar_digits_only_string(saeo.get("INN")) is not None:
            continue
        if _scalar_digits_only_string(saeo.get("OGRN")) is not None:
            continue
        inn_d = _donor_inn_for_supplement(root_aeo, record)
        ogrn_d = _donor_ogrn_for_supplement(root_aeo, record)
        kpp_d = _donor_kpp_for_supplement(root_aeo, record)
        if not inn_d and not ogrn_d and not kpp_d:
            continue
        touched = False
        if inn_d:
            saeo["INN"] = inn_d
            stats.supplement_aeo_degenerate_shell_fill_inn += 1
            touched = True
        if ogrn_d:
            saeo["OGRN"] = ogrn_d
            stats.supplement_aeo_degenerate_shell_fill_ogrn += 1
            touched = True
        if kpp_d and _aeo_field_missing_for_fill(saeo, "KPP"):
            saeo["KPP"] = kpp_d
            stats.supplement_aeo_degenerate_shell_fill_kpp += 1
            touched = True
        if touched:
            stats.supplement_aeo_degenerate_shell_records += 1


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
    остаток непустой и состоит только из цифр.
    """
    v = record.get("EduOrgOGRN")
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
    manual_inn_by_ogrn: dict[str, str] | None = None,
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
    certificate_inn_overrides_by_ogrn: bool = True,
    certificate_inn_overrides_by_ogrn_json: Path | None = None,
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
                    manual_inn_by_ogrn=manual_inn_by_ogrn,
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
                    manual_inn_by_ogrn=manual_inn_by_ogrn,
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
            certificate_inn_overrides_by_ogrn=not bool(args.no_certificate_inn_overrides_by_ogrn),
            certificate_inn_overrides_by_ogrn_json=cert_inn_ov_json,
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
