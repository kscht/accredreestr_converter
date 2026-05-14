"""tools/analyze_aeo_cert_vs_supplement.py: сводка и детерминированные sample_*.jsonl."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def test_analyze_aeo_writes_samples_deterministic_order(tmp_path: Path) -> None:
    """Порядок в датасете = порядок появления расхождений во входе; не случайная выборка."""
    same = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    diff = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    rows = [
        {"Id": "c1", "ActualEducationOrganization": {"Id": same}, "Supplements": []},
        {
            "Id": "c2",
            "ActualEducationOrganization": {"Id": same},
            "Supplements": [{"Id": "s1", "ActualEducationOrganization": {"Id": same}}],
        },
        {
            "Id": "c3",
            "ActualEducationOrganization": {"Id": same},
            "Supplements": [{"Id": "s1", "ActualEducationOrganization": {"Id": diff}}],
        },
        {
            "Id": "c4",
            "Supplements": [
                {"Id": "a", "ActualEducationOrganization": {"Id": diff}},
                {"Id": "b", "ActualEducationOrganization": {"Id": same}},
            ],
        },
    ]
    inp = tmp_path / "in.jsonl"
    inp.write_text("\n".join(_line(r) for r in rows) + "\n", encoding="utf-8")
    outd = tmp_path / "aeo_out"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "analyze_aeo_cert_vs_supplement.py"),
            str(inp),
            "-o",
            str(outd),
            "--sizes",
            "1,2,10",
            "--no-samples",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout

    r2 = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "analyze_aeo_cert_vs_supplement.py"),
            str(inp),
            "-o",
            str(outd),
            "--sizes",
            "1,2,10",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    assert "c3" in r2.stdout or "c4" in r2.stdout or "Собрано строк" in r2.stdout

    s1 = (outd / "sample_1.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(s1) == 1
    assert json.loads(s1[0])["Id"] == "c3"

    s2_lines = (outd / "sample_2.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(s2_lines) == 2
    assert json.loads(s2_lines[0])["Id"] == "c3"
    assert json.loads(s2_lines[1])["Id"] == "c4"

    s10 = (outd / "sample_10.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(s10) == 2


def test_analyze_aeo_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "analyze_aeo_cert_vs_supplement.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "--no-samples" in r.stdout
    assert "--print-examples" in r.stdout
