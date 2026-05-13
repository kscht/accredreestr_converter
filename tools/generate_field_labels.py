"""Строит словарь русских подписей полей из эталонного XML структуры (текст внутри тегов).

В файле ``specs/xml/data-*-structure-*.xml`` имена тегов — латиница, а человекочитаемое описание
лежит в текстовом содержимом листовых элементов. Пути совпадают с логикой ``convert.py``
(префикс ``Certificate/...``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = REPO_ROOT / "specs" / "xml" / "data-20160908-structure-20160713.xml"
DEFAULT_OUT = REPO_ROOT / "specs" / "field_labels.json"


def _localname(el: etree._Element) -> str:
    return etree.QName(el.tag).localname


def _element_children(el: etree._Element) -> list[etree._Element]:
    return [c for c in el if isinstance(c.tag, str)]


def _collect_leaf_labels(el: etree._Element, parts: list[str], out: dict[str, str]) -> None:
    tag = _localname(el)
    parts = [*parts, tag]
    kids = _element_children(el)
    if not kids:
        txt = (el.text or "").strip()
        if txt:
            out["/".join(parts)] = txt
        return
    for ch in kids:
        _collect_leaf_labels(ch, parts, out)


def build_labels(schema_path: Path) -> dict[str, Any]:
    with schema_path.open("rb") as fh:
        tree = etree.parse(fh)
    root = tree.getroot()
    cert: etree._Element | None = None
    for el in root.iter():
        if isinstance(el.tag, str) and _localname(el) == "Certificate":
            cert = el
            break
    if cert is None:
        raise ValueError(f"В {schema_path} не найден элемент Certificate")

    by_path: dict[str, str] = {}
    _collect_leaf_labels(cert, [], by_path)

    by_last: dict[str, list[str]] = defaultdict(list)
    for path in by_path:
        by_last[path.split("/")[-1]].append(path)
    ambiguous = {k: sorted(v) for k, v in by_last.items() if len(v) > 1}

    try:
        gen_from = str(schema_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        gen_from = schema_path.name

    return {
        "generated_from": gen_from,
        "by_schema_path": dict(sorted(by_path.items())),
        "tags_with_multiple_paths": dict(sorted(ambiguous.items())),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Сгенерировать field_labels.json из XML структуры набора данных.",
    )
    p.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help="Путь к XML структуры (по умолчанию specs/xml/data-20160908-structure-20160713.xml)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help="Куда записать JSON (по умолчанию specs/field_labels.json)",
    )
    args = p.parse_args(argv)
    if not args.schema.is_file():
        print(f"Файл схемы не найден: {args.schema}", file=sys.stderr)
        return 1
    data = build_labels(args.schema.resolve())
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Записано {len(data['by_schema_path'])} путей -> {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
