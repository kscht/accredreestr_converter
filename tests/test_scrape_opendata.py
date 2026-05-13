"""Тесты парсера списка версий opendata."""

from scrape_opendata import (
    extract_data_xml_snapshot_date,
    filter_latest_data_version_urls,
    parse_perechen_xml_urls,
)


def test_parse_perechen_extracts_xml_hrefs() -> None:
    html = """<!doctype html><html><body><ul>
    <li><a href="https://example.org/a.xml">a</a></li>
    <li><a href="b.xml">b</a></li>
    </ul></body></html>"""
    base = "https://isga.obrnadzor.gov.ru/api/spa/accredreestr/perechen"
    urls = parse_perechen_xml_urls(html, base)
    assert urls[0] == "https://example.org/a.xml"
    assert urls[1] == "https://isga.obrnadzor.gov.ru/api/spa/accredreestr/perechen/b.xml"


def test_extract_data_xml_snapshot_date() -> None:
    assert (
        extract_data_xml_snapshot_date(
            "https://host/path/data-20260403-structure-20160713.xml?x=1"
        )
        == "20260403"
    )
    assert extract_data_xml_snapshot_date("https://h/x/Data-20260205-structure.xml") == "20260205"
    assert extract_data_xml_snapshot_date("https://h/other.xml") is None


def test_filter_latest_data_version_urls() -> None:
    urls = [
        "https://x/a/data-20260205-structure-20160713.xml",
        "https://x/b/data-20260403-structure-20160713.xml",
        "https://x/c/data-20260206-structure-20160713.xml",
    ]
    out, d = filter_latest_data_version_urls(urls)
    assert d == "20260403"
    assert out == ["https://x/b/data-20260403-structure-20160713.xml"]


def test_filter_latest_same_date_keeps_all() -> None:
    urls = [
        "https://x/old/data-20260101-a.xml",
        "https://x/new/data-20260201-first.xml",
        "https://x/new/data-20260201-second.xml",
    ]
    out, d = filter_latest_data_version_urls(urls)
    assert d == "20260201"
    assert len(out) == 2


def test_filter_latest_no_date_fallback() -> None:
    urls = ["https://x/a.xml", "https://x/b.xml"]
    out, d = filter_latest_data_version_urls(urls)
    assert d is None
    assert out == urls
