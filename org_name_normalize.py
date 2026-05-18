"""Вспомогательная нормализация наименований организаций (**вне** ``convert.py``).

Используется при подготовке черновика словаря (``tools/draft_org_name_dictionary_openrouter.py``),
сравнении черновиков и офлайн-анализе. **Конвертер** для ``EduOrg*`` / ``FullName`` / ``ShortName``
применяет только общую очистку ``clean_text`` (см. ``docs/convert.md``).

Канон **display v1** (регистр сохраняется), структура юр. наименования:

**ОПФ** + ``"собственное наименование"`` + **дополнения** (филиал, структурное подразделение и т.п.).

Шаги:

1. Типографские кавычки → ASCII ``"``
2. Пробелы внутри пар ``"…"``
3. Двойные обёртки ``""…""`` → одна пара кавычек
4. Разбор: префикс ОПФ (сокращение или полная форма), имя в кавычках, хвост-дополнение
5. Пустые ``""`` убрать
6. Тире ``–``/``—`` → ``-``
7. ``№5`` → ``№ 5``
8. Схлопывание пробелов
9. **ОПФ**: если строка совпадает с известной полной формой/сокращением (без учёта регистра) —
   подстановка канона из справочника; иначе **первая буква** фрагмента ОПФ — заглавная
10. **Внутри кавычек и похожие фрагменты**: если виден **КАПС из 2+ слов** или **смесь** —
    есть **длинное** слово целиком в ВЕРХНЕМ регистре при других не-КАПС словах (напр. «ЮЖНЫЙ Федеральный …») —
    служебные слова строчные, длинные капс-слова как в обычном тексте (см. ``_humanize_org_fragment_adaptive``);
    иначе только **первая буква** фрагмента (не портим «Средняя … школа» из смешанного регистра).
11. **Инициалы + фамилия**: «М. В.» → «М.В.»; «М.В.Ломоносова» → «М.В. Ломоносова»; блок «М.В.» не
    ломает детектор КАПС; «М.В. ЛОМОНОСОВА» приводится к «М.В. Ломоносова».

**fingerprint v1** = lower(display без символов ``"``) — варианты с кавычками и без сливаются.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

ORGANIZATION_NAME_TAGS = frozenset(
    {
        "EduOrgFullName",
        "EduOrgShortName",
        "FullName",
        "ShortName",
    }
)

_UNICODE_QUOTE_MAP = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2018": "'",
        "\u2019": "'",
    }
)

_DOUBLE_ASCII_QUOTE_WRAP = re.compile(r'""([^"]*?)""')
_EMPTY_ASCII_QUOTES_RUN = re.compile(r'""+')
_NO_SPACING = re.compile(r"№\s*(\d)")
# Явная нумерация у знака номера (после нормализации пробелов у «№»).
_N_SIGN_NUMBER_RUN = re.compile(r"№+\s*\d+")
_WS_COLLAPSE = re.compile(r"\s+")
_EN_EM_DASH = re.compile(r"[\u2013\u2014]")
_QUOTED_SEGMENT_RE = re.compile(r'^(?P<opf>.*?)\s*"(?P<name>[^"]*)"\s*(?P<tail>.*)$', re.DOTALL)
_TAIL_START_RE = re.compile(
    r"(?i)\s+(?:"
    r"филиал\b|"
    r"структурн\w*\s+подразделен\w*|"
    r"представительств\w*|"
    r"обособленн\w+\s+подразделен\w*"
    r")"
)

# Сокращения ОПФ (длинные первыми).
_OPF_ABBREVS: tuple[str, ...] = (
    "ФГБНИУ",
    "ФГБОУ ВО",
    "ФГАОУ ВО",
    "ФГКОУ ВО",
    "ФГБОУ",
    "ФГАОУ",
    "ФГКОУ",
    "ГБПОУ",
    "ГБОУ",
    "ГАОУ",
    "ГКОУ",
    "ГПОУ",
    "ГОУ",
    "МБОУ",
    "МОБУ",
    "МКОУ",
    "МАОУ",
    "МОУ",
    "ЧОУ",
    "НОУ",
    "ОГБОУ",
    "ОГАУ",
    "ОУ",
    "АНОО",
    "МАУ",
)

# Полные наименования ОПФ. Совпадение — **самый длинный** подходящий префикс
# (см. ``_match_opf_full_prefix``): иначе «… учреждение» отрезает «высшего образования»,
# и капс ФГБОУ не сводится к канону.
_OPF_FULL_PREFIXES: tuple[str, ...] = (
    "Муниципальное казённое общеобразовательное учреждение",
    "Муниципальное бюджетное общеобразовательное учреждение",
    "Муниципальное автономное общеобразовательное учреждение",
    "Муниципальное общеобразовательное учреждение",
    "Государственное бюджетное общеобразовательное учреждение",
    "Государственное автономное общеобразовательное учреждение",
    "Государственное общеобразовательное учреждение",
    # Федеральные и иные — длинные формулировки важнее коротких (алгоритм выбирает по длине).
    "Федеральное государственное казенное военное образовательное учреждение высшего образования",
    "Федеральное государственное бюджетное военное образовательное учреждение высшего образования",
    "Федеральное государственное бюджетное образовательное учреждение высшего образования",
    "Федеральное государственное автономное образовательное учреждение высшего образования",
    "Федеральное государственное казенное образовательное учреждение высшего образования",
    "Федеральное государственное казённое образовательное учреждение высшего образования",
    "Федеральное казенное образовательное учреждение высшего образования",
    "Федеральное государственное бюджетное профессиональное образовательное учреждение",
    "Федеральное государственное бюджетное научное учреждение",
    "Федеральное государственное бюджетное учреждение науки",
    "Федеральное государственное бюджетное учреждение профессиональная образовательная организация",
    "Федеральное государственное казенное общеобразовательное учреждение",
    "Федеральное государственное казённое общеобразовательное учреждение",
    "Федеральное государственное бюджетное образовательное учреждение",
    "Федеральное государственное автономное образовательное учреждение",
    "Федеральное государственное бюджетное учреждение",
    "Федеральное государственное образовательное учреждение",
    "Федеральное казенное профессиональное образовательное учреждение",
    "Федеральное казенное общеобразовательное учреждение",
    "Федеральное бюджетное учреждение науки",
    "Федеральное государственное унитарное предприятие",
    "Частное общеобразовательное учреждение",
    "Негосударственное образовательное учреждение",
    "Автономная некоммерческая образовательная организация высшего образования",
    "Автономная некоммерческая организация",
)

# Служебные слова (предлоги, союзы, частицы) — строчные, кроме первого слова фрагмента (тогда «При»).
RU_TITLE_LOWERCASE_WORDS: frozenset[str] = frozenset(
    {
        "и",
        "да",
        "нет",
        "или",
        "ли",
        "же",
        "бы",
        "как",
        "ни",
        "а",
        "но",
        "в",
        "во",
        "на",
        "с",
        "со",
        "к",
        "ко",
        "у",
        "о",
        "об",
        "от",
        "до",
        "по",
        "при",
        "про",
        "из",
        "за",
        "без",
        "для",
        "над",
        "под",
        "перед",
        "через",
        "между",
        "им",
        "им.",
        "имени",
        "вв",
    }
)


# Не трогать КАПС-слова не длиннее этого (СОШ, МГУ, НИУ, КЕМГУ …).
_MAX_ALL_CAPS_STAYS_UPPER: int = 5

_INITIALS_LATIN_OR_CYR = re.compile(
    r"^(?:[А-ЯЁA-Z]\.){1,}[А-ЯЁA-Z]?\.?$",
)
_ROMAN_ORDINAL = re.compile(r"^[IVXLCDM]{1,8}$", re.IGNORECASE)

# После пары инициалов «М.В.» вставить пробел перед фамилией/словом (кириллица), не трогая «А.С.П.».
_INSERT_SPACE_AFTER_TWO_INITIALS = re.compile(
    r"([А-ЯЁA-Z]\.[А-ЯЁA-Z]\.)(?=(?:[А-ЯЁA-Z][а-яё]{2,}|[А-ЯЁA-Z]{4,}))",
)


def _normalize_initials_and_surname_spacing(s: str) -> str:
    """«М. В.» → «М.В.»; «М.В.Ломоносова» / «М.В.ЛОМОНОСОВА» → «М.В. Ломоносова»."""
    s = collapse_whitespace(s)
    if not s:
        return s
    s = re.sub(r"([А-ЯЁA-Za-z])\s*\.\s*([А-ЯЁA-Za-z])\s*\.", r"\1.\2.", s)
    s = _INSERT_SPACE_AFTER_TWO_INITIALS.sub(r"\1 ", s)
    return collapse_whitespace(s)


def _alpha_core_edges(token: str) -> tuple[str, str, str]:
    """Префикс без букв, ядро с буквами, суффикс (пунктуация справа)."""
    n = len(token)
    i = 0
    while i < n and not token[i].isalpha():
        i += 1
    j = n
    while j > i and not token[j - 1].isalpha():
        j -= 1
    return token[:i], token[i:j], token[j:]


def _token_looks_like_initialism(p: str) -> bool:
    """«М.В.», «А.С.» — не буквенное «слово» для порога КАПС (ядро без точек даёт isalpha False)."""
    t = p.strip()
    return bool(
        re.fullmatch(r"(?:[А-ЯЁA-Z]\.){2,}\s*", t) or re.fullmatch(r"(?:[А-ЯЁA-Za-z]\.){2,}\s*", t)
    )


def _fragment_letter_cores(s: str) -> tuple[list[str], int] | None:
    """Буквенные ядра слов и число токенов-инициализаций; ``None``, если фрагмент неразборчив (не только буквы)."""
    parts = collapse_whitespace(s).split()
    cores: list[str] = []
    n_init = 0
    for p in parts:
        if _token_looks_like_initialism(p):
            n_init += 1
            continue
        _, core, _ = _alpha_core_edges(p)
        if not core or any(ch.isdigit() for ch in core):
            continue
        if not core.isalpha():
            return None
        cores.append(core)
    return cores, n_init


def _fragment_screaming_caps_kind(s: str) -> Literal["none", "all", "mixed"]:
    """``all`` — типичная капс-простыня; ``mixed`` — часть слов уже не КАПС, но есть длинное КАПС-слово (напр. «ЮЖНЫЙ Федеральный …»)."""
    parsed = _fragment_letter_cores(s)
    if parsed is None:
        return "none"
    cores, n_init = parsed
    if len(cores) >= 2 and all(c.isupper() for c in cores):
        return "all"
    if len(cores) >= 2 and not all(c.isupper() for c in cores):
        if any(len(c) >= _MAX_ALL_CAPS_STAYS_UPPER and c.isupper() for c in cores):
            return "mixed"
    if (
        len(cores) == 1
        and n_init >= 1
        and cores[0].isupper()
        and len(cores[0]) > _MAX_ALL_CAPS_STAYS_UPPER
    ):
        return "all"
    return "none"


def _humanize_org_fragment_adaptive(s: str) -> str:
    """КАПС-простыню — в читаемый заголовок; иначе только первая буква фрагмента."""
    s = _normalize_initials_and_surname_spacing(s)
    if not s:
        return s
    kind = _fragment_screaming_caps_kind(s)
    if kind == "all":
        return humanize_russian_org_fragment_title_case(s, short_caps_stay_upper=True)
    if kind == "mixed":
        return humanize_russian_org_fragment_title_case(s, short_caps_stay_upper=False)
    return capitalize_first_alpha(s)


def _humanize_plain_word_ru(
    token: str, *, is_first_in_fragment: bool, short_caps_stay_upper: bool
) -> str:
    if _token_looks_like_initialism(token):
        return token
    prefix, core, suffix = _alpha_core_edges(token)
    if not core:
        return token
    if any(ch.isdigit() for ch in token):
        return token
    if _INITIALS_LATIN_OR_CYR.fullmatch(core):
        return token
    if _ROMAN_ORDINAL.fullmatch(core):
        return token
    cf = core.casefold()
    if cf in RU_TITLE_LOWERCASE_WORDS:
        if is_first_in_fragment:
            new_core = core[0].upper() + core[1:].lower()
        else:
            new_core = core.lower()
    elif core.isalpha() and core.isupper():
        if short_caps_stay_upper and len(core) <= _MAX_ALL_CAPS_STAYS_UPPER:
            new_core = core
        else:
            new_core = core[0].upper() + core[1:].lower()
    else:
        new_core = capitalize_first_alpha(core)
    return prefix + new_core + suffix


def _humanize_word_with_hyphens(
    token: str, *, is_first_in_fragment: bool, short_caps_stay_upper: bool
) -> str:
    if "-" not in token:
        return _humanize_plain_word_ru(
            token, is_first_in_fragment=is_first_in_fragment, short_caps_stay_upper=short_caps_stay_upper
        )
    parts = token.split("-")
    out: list[str] = []
    for i, p in enumerate(parts):
        out.append(
            _humanize_plain_word_ru(
                p,
                is_first_in_fragment=is_first_in_fragment and i == 0,
                short_caps_stay_upper=short_caps_stay_upper,
            )
        )
    return "-".join(out)


def humanize_russian_org_fragment_title_case(
    s: str, *, short_caps_stay_upper: bool = True
) -> str:
    """Внутри кавычек / хвоста: служебные слова строчные (кроме начала), КАПС длинных слов — обычный вид.

    При ``short_caps_stay_upper=True`` (капс-простыня) короткие КАПС-аббревиатуры (≤ ``_MAX_ALL_CAPS_STAYS_UPPER``)
    не трогаем. При ``False`` (смесь с «Федеральный …») и их приводим к виду «Южный».
    """
    s = _normalize_initials_and_surname_spacing(s)
    if not s:
        return s
    parts = re.split(r"(\s+)", s)
    out: list[str] = []
    word_i = 0
    for p in parts:
        if not p or p.isspace():
            out.append(p)
            continue
        out.append(
            _humanize_word_with_hyphens(
                p,
                is_first_in_fragment=(word_i == 0),
                short_caps_stay_upper=short_caps_stay_upper,
            )
        )
        word_i += 1
    return "".join(out)


# Краткое наименование без ОПФ (СОШ № N, лицей …) — целиком в кавычки.
_NAME_ONLY_HINT_RE = re.compile(
    r"(?i)(?:^|\s)(?:"
    r"сош|средн\w+\s+общеобразовательн\w+\s+школ\w*|"
    r"школ\w*|лице\w*|гимнази\w*|колледж\w*|"
    r"техникум\w*|училищ\w*|детск\w+\s+сад\w*|"
    r"апк|по\b"
    r")"
)


def collapse_whitespace(s: str) -> str:
    return _WS_COLLAPSE.sub(" ", s.strip())


def capitalize_first_alpha(s: str) -> str:
    """Первая буква строки (кириллица/латиница) — заглавная, если была строчной."""
    for i, ch in enumerate(s):
        if ch.isalpha():
            if ch.islower():
                return s[:i] + ch.upper() + s[i + 1 :]
            return s
    return s


def normalize_opf_fragment_display(opf: str) -> str:
    """Известная ОПФ → канон из словаря; иначе заглавная первая буква фрагмента."""
    o = opf.strip()
    if not o:
        return ""
    ab = _match_opf_abbrev_prefix(o)
    if ab is not None and not ab[1]:
        return ab[0]
    fu = _match_opf_full_prefix(o)
    if fu is not None and not fu[1]:
        return fu[0]
    if fu is not None and fu[1]:
        return fu[0] + " " + _humanize_org_fragment_adaptive(fu[1])
    if ab is not None and ab[1]:
        return ab[0] + " " + _humanize_org_fragment_adaptive(ab[1])
    return capitalize_first_alpha(o)


def normalize_quoted_org_name_fragment(name: str) -> str:
    """Собственное наименование: КАПС-режим → читаемые слова; иначе только первая буква фрагмента."""
    n = collapse_whitespace(name)
    return _humanize_org_fragment_adaptive(n) if n else n


def normalize_unicode_quotes_to_ascii(s: str) -> str:
    return s.translate(_UNICODE_QUOTE_MAP)


def trim_spaces_inside_ascii_quotes(s: str) -> str:
    def _trim_inner(match: re.Match[str]) -> str:
        return '"' + match.group(1).strip() + '"'

    return re.sub(r'"([^"]*)"', _trim_inner, s)


def strip_double_ascii_quote_wrappers(s: str) -> str:
    """``""Имя""`` → ``Имя`` (итеративно)."""
    prev = None
    out = s
    while prev != out:
        prev = out
        out = _DOUBLE_ASCII_QUOTE_WRAP.sub(r"\1", out)
    return out


def collapse_empty_ascii_quote_runs(s: str) -> str:
    return _EMPTY_ASCII_QUOTES_RUN.sub("", s)


def normalize_number_sign_spacing(s: str, *, space_after: bool = True) -> str:
    if space_after:
        return _NO_SPACING.sub(r"№ \1", s)
    return _NO_SPACING.sub(r"№\1", s)


def mask_organization_name_enumeration_numbers_v1(s: str) -> str:
    """Заменить «№» + число на шаблон ``№ ⟨N⟩`` (для дедупа, LLM, словарей).

    Не меняет вывод ``convert.py`` по умолчанию: разные «СОШ № 5» и «СОШ № 6» должны
    оставаться разными в JSONL. Только явные нумерации у знака ``№`` (в т.ч. ``№№ 3``).

    Произвольные цифры (год, «40-летия», ОГРН в тексте) **не** трогаются.
    """
    if not isinstance(s, str) or not s.strip():
        return s
    out = collapse_whitespace(s)
    prev = None
    while prev != out:
        prev = out
        out = _N_SIGN_NUMBER_RUN.sub("№ ⟨N⟩", out)
    return collapse_whitespace(out)


def normalize_dashes_to_hyphen(s: str) -> str:
    return _EN_EM_DASH.sub("-", s)


def _fingerprint_semantic_text(display: str) -> str:
    return collapse_whitespace(display.replace('"', ""))


def _split_name_and_tail(rest: str) -> tuple[str, str]:
    rest = rest.strip()
    if not rest:
        return "", ""
    m = _TAIL_START_RE.search(rest)
    if m:
        return rest[: m.start()].strip(), rest[m.start() :].strip()
    return rest, ""


def _compose_opf_quoted_tail(opf: str, name: str, tail: str) -> str:
    opf_n = normalize_opf_fragment_display(opf) if opf.strip() else ""
    name_n = normalize_quoted_org_name_fragment(name)
    tail_st = tail.strip()
    tail_n = _humanize_org_fragment_adaptive(tail_st) if tail_st else ""
    if not name_n:
        return collapse_whitespace(" ".join(p for p in (opf_n, tail_n) if p))
    core = f'{opf_n} "{name_n}"' if opf_n else f'"{name_n}"'
    if tail_n:
        return collapse_whitespace(f"{core} {tail_n}")
    return core


def _match_opf_abbrev_prefix(s: str) -> tuple[str, str] | None:
    best: tuple[str, str] | None = None
    best_len = -1
    for opf in _OPF_ABBREVS:
        if len(s) < len(opf):
            continue
        if s[: len(opf)].upper() != opf.upper():
            continue
        if len(s) > len(opf) and not s[len(opf)].isspace():
            continue
        if len(opf) > best_len:
            best_len = len(opf)
            best = (opf, s[len(opf) :].lstrip())
    return best


def _match_opf_full_prefix(s: str) -> tuple[str, str] | None:
    low = s.casefold()
    best: tuple[str, str] | None = None
    best_len = -1
    for prefix in _OPF_FULL_PREFIXES:
        plen = len(prefix)
        if len(s) < plen:
            continue
        if low[:plen] != prefix.casefold():
            continue
        if len(s) > plen and not s[plen].isspace():
            continue
        if plen > best_len:
            best_len = plen
            best = (prefix, s[plen:].lstrip())
    return best


def format_organization_name_opf_quoted(s: str) -> str:
    """Приводит строку к виду ОПФ + ``\"имя\"`` + дополнения (если удаётся разобрать)."""
    s = collapse_whitespace(s)
    if not s:
        return s

    m = _QUOTED_SEGMENT_RE.match(s)
    if m:
        opf = m.group("opf").strip()
        name = collapse_whitespace(m.group("name"))
        tail = m.group("tail").strip()
        if name:
            return _compose_opf_quoted_tail(opf, name, tail)

    matched = _match_opf_abbrev_prefix(s)
    if matched is not None:
        opf, rest = matched
        name, tail = _split_name_and_tail(rest)
        return _compose_opf_quoted_tail(opf, name, tail)

    matched = _match_opf_full_prefix(s)
    if matched is not None:
        opf, rest = matched
        name, tail = _split_name_and_tail(rest)
        return _compose_opf_quoted_tail(opf, name, tail)

    if _NAME_ONLY_HINT_RE.search(s) and '"' not in s:
        raw_name = collapse_whitespace(s)
        name_n = normalize_quoted_org_name_fragment(raw_name)
        return _compose_opf_quoted_tail("", name_n, "")

    return _humanize_org_fragment_adaptive(s)


def normalize_organization_display_name_v1(s: str) -> str:
    if not isinstance(s, str):
        return s
    raw = s.strip()
    if not raw:
        return s
    out = raw
    out = normalize_unicode_quotes_to_ascii(out)
    out = trim_spaces_inside_ascii_quotes(out)
    out = strip_double_ascii_quote_wrappers(out)
    out = collapse_empty_ascii_quote_runs(out)
    out = normalize_dashes_to_hyphen(out)
    out = normalize_number_sign_spacing(out, space_after=True)
    out = collapse_whitespace(out)
    out = format_organization_name_opf_quoted(out)
    return out if out else raw


def organization_name_fingerprint_v1(s: str) -> str:
    return _fingerprint_semantic_text(normalize_organization_display_name_v1(s)).casefold()


def name_changed_by_v1(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    return normalize_organization_display_name_v1(s) != collapse_whitespace(s)


@dataclass
class OrganizationNameNormalizeStats:
    fields_normalized: int = 0
    by_field: dict[str, int] = field(default_factory=dict)

    def record(self, field_key: str) -> None:
        self.fields_normalized += 1
        self.by_field[field_key] = int(self.by_field.get(field_key, 0)) + 1

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "fields_normalized": self.fields_normalized,
            "by_field": dict(sorted(self.by_field.items())),
        }


def _normalize_field(obj: dict[str, Any], key: str, field_key: str, stats: OrganizationNameNormalizeStats) -> None:
    if key not in obj:
        return
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        return
    new_val = normalize_organization_display_name_v1(val)
    if new_val != val:
        obj[key] = new_val
        stats.record(field_key)


def normalize_organization_names_in_record(
    record: dict[str, Any],
    stats: OrganizationNameNormalizeStats | None = None,
) -> None:
    """Нормализует шесть полей имён на одном сертификате (in-place)."""
    st = stats if stats is not None else OrganizationNameNormalizeStats()
    for key in ("EduOrgFullName", "EduOrgShortName"):
        _normalize_field(record, key, f"Certificate.{key}", st)
    root_aeo = record.get("ActualEducationOrganization")
    if isinstance(root_aeo, dict):
        for key in ("FullName", "ShortName"):
            _normalize_field(root_aeo, key, f"root_ActualEducationOrganization.{key}", st)
    for sup in record.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        sa = sup.get("ActualEducationOrganization")
        if not isinstance(sa, dict):
            continue
        for key in ("FullName", "ShortName"):
            _normalize_field(
                sa,
                key,
                f"supplement_ActualEducationOrganization.{key}",
                st,
            )


def iter_organization_name_fields(row: dict[str, Any]) -> Any:
    for key in ("EduOrgFullName", "EduOrgShortName"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            yield f"Certificate.{key}", v
    ra = row.get("ActualEducationOrganization")
    if isinstance(ra, dict):
        for key in ("FullName", "ShortName"):
            v = ra.get(key)
            if isinstance(v, str) and v.strip():
                yield f"root_ActualEducationOrganization.{key}", v
    for sup in row.get("Supplements") or []:
        if not isinstance(sup, dict):
            continue
        sa = sup.get("ActualEducationOrganization")
        if not isinstance(sa, dict):
            continue
        for key in ("FullName", "ShortName"):
            v = sa.get(key)
            if isinstance(v, str) and v.strip():
                yield f"supplement_ActualEducationOrganization.{key}", v
