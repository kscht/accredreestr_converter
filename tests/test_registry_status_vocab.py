"""tools/registry_status_vocab.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_registry_status_vocab_minimal(tmp_path: Path) -> None:
    src = tmp_path / "certs.jsonl"
    src.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "Id": "a",
                        "StatusName": "Действующее",
                        "Supplements": [{"StatusName": "Недействующее"}],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "Id": "b",
                        "StatusName": "Переоформлено",
                        "Supplements": [{"StatusName": "Действующее"}],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    outp = tmp_path / "vocab.json"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "registry_status_vocab.py"),
            str(src),
            "-o",
            str(outp),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["certificate_lines_total"] == 2
    assert "Недействующее" in data["histograms"]["supplement_StatusName"]
    assert data["examples_first_occurrence"]["certificate_StatusName"]["Переоформлено"]["certificate_id"] == "b"


def test_registry_status_vocab_help() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "registry_status_vocab.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "StatusName" in r.stdout
