"""Смоук-тесты: specs/prisma/mapping.json и tools/generate_prisma_schema.py."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_MAP = ROOT / "specs" / "sql" / "mapping.json"
PRISMA_MAP = ROOT / "specs" / "prisma" / "mapping.json"
GEN_SCRIPT = ROOT / "tools" / "generate_prisma_schema.py"


def _load_gen_module():
    spec = importlib.util.spec_from_file_location("generate_prisma_schema", GEN_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prisma_mapping_json_loads() -> None:
    data = json.loads(PRISMA_MAP.read_text(encoding="utf-8"))
    assert data.get("format_version") == 1
    assert "model_names" in data
    assert data["model_names"]["certificates"] == "Certificate"


def test_build_prisma_schema_contains_models() -> None:
    gen = _load_gen_module()
    sql_m = gen._load_json(SQL_MAP)
    prisma_m = gen._load_json(PRISMA_MAP)
    text = gen.build_schema(sql_m, prisma_m)
    assert "model Certificate" in text
    assert '@@map("certificates")' in text
    assert "model Supplement" in text
    assert '@relation("AeoViaCertificate"' in text
    assert '@relation("AeoViaSupplement"' in text
    assert '@@id([certificate_id])' in text


@pytest.mark.skipif(shutil.which("npx") is None, reason="Нужен npx для prisma validate")
def test_prisma_schema_validates_with_dummy_url(tmp_path: Path) -> None:
    out = tmp_path / "schema.prisma"
    subprocess.run(
        [sys.executable, str(GEN_SCRIPT), "-o", str(out)],
        cwd=str(ROOT),
        check=True,
    )
    env = {**os.environ, "DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/d"}
    r = subprocess.run(
        ["npx", "--yes", "prisma@6.7.0", "validate", f"--schema={out}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert r.returncode == 0, r.stderr + r.stdout
