"""Потоковая конвертация XML реестра аккредитации в JSON Lines."""

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

# Имя эталонного XML структуры (лежит в specs/xml/)
DEFAULT_SCHEMA_FILENAME: Final[str] = "data-20160908-structure-20160713.xml"

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


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def default_schema_path() -> Path:
    """Путь к эталонному XML со структурой полей."""
    return _project_root() / "specs" / "xml" / DEFAULT_SCHEMA_FILENAME


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
    """Удаляет пробелы и дефисы из идентификатора; проверяет, что остались только цифры."""
    if raw is None:
        return None
    cleaned = re.sub(r"[\s\-]", "", raw)
    if not cleaned:
        return None
    if not cleaned.isdigit():
        logging.warning(
            "Поле %s после очистки содержит не только цифры: %r",
            field_name,
            cleaned,
        )
        stats.non_digit_ids += 1
    return cleaned


def _element_text(el: etree._Element) -> str:
    """Собирает текстовое содержимое элемента, подменяя невалидные UTF-8-символы."""
    try:
        return "".join(el.itertext())
    except UnicodeDecodeError:
        raw = etree.tostring(el, encoding="utf-8", method="text")
        return raw.decode("utf-8", errors="replace")


def normalize_scalar(
    tag: str, text: str | None, stats: ConversionStats
) -> str | bool | None:
    """Нормализует скалярное поле с учётом типа."""
    cleaned = clean_text(text)
    if cleaned is None:
        return None
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

    def to_report_dict(
        self,
        inputs: Sequence[str],
        elapsed: float,
    ) -> dict[str, Any]:
        """Формирует словарь для JSON-отчёта."""
        total_processed = sum(v["processed"] for v in self.per_file.values())
        total_skipped = sum(v["skipped"] for v in self.per_file.values())
        return {
            "inputs": list(inputs),
            "per_file": dict(self.per_file),
            "total": {
                "processed": total_processed,
                "skipped": total_skipped,
                "warnings": {
                    "bad_dates": self.bad_dates,
                    "bad_booleans": self.bad_booleans,
                    "non_digit_ids": self.non_digit_ids,
                    "broken_records": self.broken_records,
                    "unknown_tags": list(self.unknown_tags),
                },
                "elapsed_seconds": round(elapsed, 3),
            },
        }


def _init_file_stats(stats: ConversionStats, basename: str) -> None:
    if basename not in stats.per_file:
        stats.per_file[basename] = {"processed": 0, "skipped": 0}


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
    source_basename: str | None = None,
) -> None:
    """Конвертирует один XML-файл, дописывая строки JSON в открытый файловый объект."""
    _ = schema_path  # зарезервировано для расширений / совместимости API
    base = source_basename or input_path.name
    _init_file_stats(stats, base)
    processed = 0
    skipped = 0

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
                record["_source_file"] = base
                safe = ensure_json_safe(record)
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
) -> ConversionStats:
    """Конвертирует один или несколько входных XML.

    Args:
        inputs: Входные файлы.
        output: Путь к одному .jsonl при ``merged=True`` (обязателен).
        merged: True — все входы в один ``output``. False — по одному
            ``stem.jsonl`` в ``out_dir`` на вход (нужно не меньше двух файлов).
        out_dir: Каталог для раздельных выходов при ``merged=False``.
    """
    if not inputs:
        raise ValueError("Нет входных файлов")
    schema_tags = load_schema_tag_names(schema_path)
    stats = ConversionStats()

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
        "--report",
        type=Path,
        default=None,
        help="Путь к JSON-файлу со сводной статистикой",
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
