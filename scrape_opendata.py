"""Поиск актуальных URL XML-версий набора данных со страницы открытых данных ИС ГА.

На странице https://isga.obrnadzor.gov.ru/accredreestr/opendata/ (Vue-SPA) строка
«Гиперссылки (URL) на версии набора данных» отображается как iframe. Его ``src``
указывает на HTML-страницу со списком ссылок на ``*.xml``. Скрипт воспроизводит
то же: находит URL iframe в бандле ``app.*.js``, затем парсит список ссылок.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Final
from urllib.parse import unquote, urljoin, urlparse

import requests
from lxml import html

DEFAULT_INDEX_URL: Final[str] = "https://isga.obrnadzor.gov.ru/accredreestr/opendata/"
DEFAULT_PERECHEN_FALLBACK: Final[str] = (
    "https://isga.obrnadzor.gov.ru/api/spa/accredreestr/perechen"
)
BROWSER_UA: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Дата снимка в имени файла выгрузки: data-YYYYMMDD-structure-…xml
_DATA_XML_DATE_RE: Final[re.Pattern[str]] = re.compile(r"data-(\d{8})-", re.IGNORECASE)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "ru-RU,ru;q=0.9"})
    return s


def discover_perechen_url(session: requests.Session, index_url: str) -> str:
    """Находит абсолютный URL HTML со списком версий (как у iframe на странице opendata)."""
    r = session.get(index_url, timeout=60)
    r.raise_for_status()
    m = re.search(r'<script\s+src="(/js/app\.[^"]+\.js)"', r.text)
    if not m:
        logging.warning(
            "Не найден /js/app.*.js на главной opendata — используем запасной URL perechen"
        )
        return DEFAULT_PERECHEN_FALLBACK
    app_js_path = m.group(1)
    app_js_url = urljoin(index_url, app_js_path)
    aj = session.get(app_js_url, timeout=60)
    aj.raise_for_status()
    # Как в бандле Vue: {..., title:"Гиперссылки (URL) на версии набора данных",type:"iframe",src:"/api/..."}
    m2 = re.search(r'src:"(/api/spa/accredreestr/perechen)"', aj.text)
    if not m2:
        m2 = re.search(r'"(/api/spa/accredreestr/perechen)"', aj.text)
    if not m2:
        logging.warning(
            "В app.js не найден путь /api/spa/accredreestr/perechen — используем запасной URL"
        )
        return DEFAULT_PERECHEN_FALLBACK
    return urljoin(index_url, m2.group(1))


def parse_perechen_xml_urls(perechen_html: str | bytes, base_url: str) -> list[str]:
    """Извлекает прямые ссылки на XML из HTML-страницы «Версии набора данных»."""
    root = html.fromstring(perechen_html)
    seen: set[str] = set()
    out: list[str] = []
    for href in root.xpath("//a/@href"):
        if not isinstance(href, str):
            continue
        u = href.strip()
        low = u.lower()
        if not (low.endswith(".xml") or ".xml?" in low):
            continue
        abs_url = urljoin(base_url + "/", u)
        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)
    return out


def extract_data_xml_snapshot_date(url: str) -> str | None:
    """Извлекает YYYYMMDD из имени файла (фрагмент ``data-YYYYMMDD-``) или None."""
    path = unquote(urlparse(url).path)
    name = Path(path).name
    m = _DATA_XML_DATE_RE.search(name)
    return m.group(1) if m else None


def filter_latest_data_version_urls(
    urls: list[str],
) -> tuple[list[str], str | None]:
    """Оставляет только URL с максимальной датой снимка ``data-YYYYMMDD``.

    Если ни в одном имени нет распознаваемой даты, возвращает исходный список
    и ``None`` (вызывающий код может залогировать предупреждение).
    """
    dated: list[tuple[str, str]] = []
    for u in urls:
        d = extract_data_xml_snapshot_date(u)
        if d:
            dated.append((u, d))
    if not dated:
        return list(urls), None
    best = max(d[1] for d in dated)
    chosen = [u for u, d in dated if d == best]
    return chosen, best


def fetch_xml_version_urls(
    session: requests.Session | None = None,
    *,
    index_url: str = DEFAULT_INDEX_URL,
    perechen_url: str | None = None,
) -> tuple[list[str], str]:
    """Возвращает (список URL на XML, фактический URL perechen)."""
    sess = session or _session()
    resolved = perechen_url or discover_perechen_url(sess, index_url)
    pr = sess.get(resolved, timeout=60)
    pr.raise_for_status()
    urls = parse_perechen_xml_urls(pr.text, resolved)
    return urls, resolved


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Находит ссылки на XML версий набора данных "
            "(iframe «Гиперссылки (URL) на версии набора данных» на странице opendata)."
        ),
    )
    p.add_argument(
        "--index-url",
        default=DEFAULT_INDEX_URL,
        help="URL страницы opendata (SPA shell)",
    )
    p.add_argument(
        "--perechen-url",
        default=None,
        help="Прямой URL списка версий (если не задан — определяется из бандла)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Печатать результат в stdout как JSON",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Записать URL по одному на строку в файл",
    )
    p.add_argument(
        "--all-versions",
        action="store_true",
        help="Не отфильтровывать: все найденные XML (по умолчанию — только снимок с max data-YYYYMMDD)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI: печать URL или запись в файл."""
    args = _parse_args(argv)
    _configure_logging()
    try:
        urls, perechen = fetch_xml_version_urls(
            perechen_url=args.perechen_url,
            index_url=args.index_url,
        )
    except requests.RequestException as exc:
        logging.error("Ошибка сети: %s", exc)
        return 1
    logging.info("Источник списка: %s", perechen)
    logging.info("Найдено ссылок на XML: %s", len(urls))
    if not args.all_versions:
        urls, snap = filter_latest_data_version_urls(urls)
        if snap is not None:
            logging.info(
                "Только последний снимок по дате в имени (data-%s-): %s файл(ов)",
                snap,
                len(urls),
            )
        else:
            logging.warning(
                "В именах ссылок нет data-YYYYMMDD — выводим все %s URL",
                len(urls),
            )
    if args.json:
        print(json.dumps({"perechen_url": perechen, "xml_urls": urls}, ensure_ascii=False, indent=2))
    else:
        for u in urls:
            print(u)
    if args.output is not None:
        args.output.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
        logging.info("Записано в %s", args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
