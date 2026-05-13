"""Тест генерации словаря подписей из эталонной схемы."""

from pathlib import Path

from tools.generate_field_labels import build_labels

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "specs" / "xml" / "data-20160908-structure-20160713.xml"


def test_build_labels_certificate_and_supplement_id_differ() -> None:
    data = build_labels(SCHEMA)
    assert data["by_schema_path"]["Certificate/Id"] == "Идентификатор свидетельства"
    assert (
        data["by_schema_path"]["Certificate/Supplements/Supplement/Id"]
        == "Идентификатор приложения"
    )
    assert "Id" in data["tags_with_multiple_paths"]
    paths = data["tags_with_multiple_paths"]["Id"]
    assert "Certificate/Id" in paths
    assert "Certificate/Supplements/Supplement/Id" in paths


def test_build_labels_nested_program() -> None:
    data = build_labels(SCHEMA)
    key = (
        "Certificate/Supplements/Supplement/EducationalPrograms/"
        "EducationalProgram/ProgrammName"
    )
    assert data["by_schema_path"][key] == "Наименование ОП"
