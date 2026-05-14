"""tools/generate_test_jsonl_samples.py и reservoir_sample_lines."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_sample_jsonl_module():
    path = ROOT / "tools" / "sample_jsonl_lines.py"
    spec = importlib.util.spec_from_file_location("sample_jsonl_lines", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reservoir_sample_lines_count_and_determinism(tmp_path: Path) -> None:
    sjl = _load_sample_jsonl_module()
    inp = tmp_path / "in.jsonl"
    inp.write_text("\n".join(f'{{"i":{k}}}' for k in range(30)) + "\n", encoding="utf-8")
    a = sjl.reservoir_sample_lines(inp, 5, seed=123)
    b = sjl.reservoir_sample_lines(inp, 5, seed=123)
    assert len(a) == 5
    assert a == b
    c = sjl.reservoir_sample_lines(inp, 5, seed=999)
    assert len(c) == 5


def test_reservoir_too_few_lines(tmp_path: Path) -> None:
    sjl = _load_sample_jsonl_module()
    inp = tmp_path / "tiny.jsonl"
    inp.write_text('{"a":1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="только 1"):
        sjl.reservoir_sample_lines(inp, 5, seed=1)


def test_generate_test_jsonl_samples_cli(tmp_path: Path) -> None:
    inp = tmp_path / "src.jsonl"
    inp.write_text("\n".join(f'{{"n":{i}}}' for i in range(50)) + "\n", encoding="utf-8")
    outd = tmp_path / "out_samples"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "generate_test_jsonl_samples.py"),
            str(inp),
            "-o",
            str(outd),
            "--sizes",
            "3,7",
            "--seed-base",
            "1000",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert (outd / "sample_3.jsonl").read_text(encoding="utf-8").count("\n") == 3
    assert (outd / "sample_7.jsonl").read_text(encoding="utf-8").count("\n") == 7


def test_generate_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_test_jsonl_samples.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "--sizes" in r.stdout
    assert "--seed-base" in r.stdout
