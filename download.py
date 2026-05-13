"""Скачивание XML-выгрузок реестра аккредитации (опционально)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import requests

import scrape_opendata

DEFAULT_URLS_FILE = Path("download_urls.txt")
DEFAULT_OUTPUT_DIR = Path("data")
CHUNK_SIZE = 1024 * 1024  # 1 MiB

URLS_TEMPLATE = """# По одному URL на строку. Строки, начинающиеся с #, игнорируются.
# Откройте страницу https://isga.obrnadzor.gov.ru/accredreestr/opendata/,
# скопируйте прямые ссылки на XML и вставьте ниже (или используйте download.py --discover).
#
# https://example.invalid/data-20260101-structure-20160713.xml
"""


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def _ensure_urls_file(path: Path) -> list[str]:
    if not path.is_file():
        path.write_text(URLS_TEMPLATE, encoding="utf-8")
        logging.info(
            "Создан шаблон %s — заполните URL и перезапустите команду.",
            path.resolve(),
        )
        return []
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def _unique_filename(target_dir: Path, url: str) -> Path:
    from urllib.parse import urlparse

    name = Path(urlparse(url).path).name or "download.xml"
    candidate = target_dir / name
    if not candidate.exists():
        return candidate
    stem, suf = candidate.stem, candidate.suffix
    n = 2
    while True:
        alt = target_dir / f"{stem}_{n}{suf}"
        if not alt.exists():
            return alt
        n += 1


def _download_one(
    url: str,
    dest: Path,
    *,
    resume: bool,
    session: requests.Session,
) -> None:
    headers: dict[str, str] = {}
    bytes_done = 0
    mode = "wb"
    if resume and dest.exists():
        bytes_done = dest.stat().st_size
        if bytes_done > 0:
            headers["Range"] = f"bytes={bytes_done}-"
            mode = "ab"

    try:
        resp = session.get(url, stream=True, headers=headers, timeout=120)
        if resume and bytes_done > 0 and resp.status_code == 416:
            logging.info("Докачка не нужна (416), файл уже полный: %s", dest.name)
            return
        if resume and bytes_done > 0 and resp.status_code == 200:
            # Сервер не поддержал Range — перекачать с нуля
            logging.info("Сервер не поддержал Range, полная перезагрузка: %s", dest.name)
            bytes_done = 0
            mode = "wb"
            resp.close()
            resp = session.get(url, stream=True, timeout=120)

        resp.raise_for_status()

        total = resp.headers.get("Content-Length")
        total_int = int(total) if total and total.isdigit() else None
        if total_int is not None:
            logging.info("Скачивание %s (ожидаемо ~%.1f MB)", dest.name, total_int / (1024 * 1024))

        written = bytes_done
        with dest.open(mode) as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                fh.write(chunk)
                written += len(chunk)
                if written and written % (50 * CHUNK_SIZE) < CHUNK_SIZE:
                    logging.info("downloaded %s/%s MB", written // (1024 * 1024), "???")

        mb = written / (1024 * 1024)
        logging.info("downloaded %.1f MB — готово: %s", mb, dest.resolve())
    except requests.RequestException as exc:
        logging.error("Ошибка HTTP при скачивании %s: %s", url, exc)
        if dest.exists():
            dest.unlink()
        raise


def download_urls(
    urls: list[str],
    output_dir: Path,
    *,
    resume: bool = True,
) -> None:
    """Скачивает список URL в каталог output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": scrape_opendata.BROWSER_UA})
    for url in urls:
        dest = _unique_filename(output_dir, url)
        logging.info("URL: %s -> %s", url, dest.name)
        _download_one(url, dest, resume=resume, session=session)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Скачивание XML-файлов реестра (потоково, чанками по 1 МБ).",
    )
    p.add_argument(
        "urls",
        nargs="*",
        help="Прямые URL (если не указаны — читается download_urls.txt)",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Каталог для сохранения (по умолчанию data/)",
    )
    p.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_URLS_FILE,
        help="Файл со списком URL (по умолчанию download_urls.txt)",
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="Не использовать заголовок Range для докачки",
    )
    p.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Найти XML-URL автоматически (как iframe «Гиперссылки (URL) на версии набора данных»)"
        ),
    )
    p.add_argument(
        "--all-versions",
        action="store_true",
        help=(
            "При --discover: скачать все найденные XML. "
            "По умолчанию — только файлы с максимальной датой в имени (data-YYYYMMDD-)"
        ),
    )
    p.add_argument(
        "--save-urls",
        type=Path,
        default=None,
        help="При --discover: записать URL в файл (по умолчанию те же, что пойдут в загрузку)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    _configure_logging()
    args = _parse_args(argv)

    if args.discover and args.urls:
        logging.error("Нельзя одновременно указывать --discover и URL в командной строке")
        return 2

    if args.all_versions and not args.discover:
        logging.error("Флаг --all-versions имеет смысл только вместе с --discover")
        return 2

    if args.discover:
        try:
            urls, perechen = scrape_opendata.fetch_xml_version_urls()
        except requests.RequestException as exc:
            logging.error("Не удалось получить список версий: %s", exc)
            return 1
        logging.info("Список версий: %s", perechen)
        if not urls:
            logging.error("Список XML-URL пуст")
            return 1
        if not args.all_versions:
            urls, snap = scrape_opendata.filter_latest_data_version_urls(urls)
            if snap is not None:
                logging.info(
                    "Выбран последний снимок по дате в имени (data-%s-): %s файл(ов)",
                    snap,
                    len(urls),
                )
            else:
                logging.warning(
                    "В именах ссылок нет data-YYYYMMDD — скачиваем все %s URL",
                    len(urls),
                )
        if args.save_urls is not None:
            args.save_urls.write_text("\n".join(urls) + "\n", encoding="utf-8")
            logging.info("URL записаны в %s", args.save_urls.resolve())
    elif args.urls:
        urls = list(args.urls)
    else:
        urls = _ensure_urls_file(args.config)
        if not urls:
            return 0

    try:
        download_urls(urls, args.output_dir.resolve(), resume=not args.no_resume)
    except requests.RequestException:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
