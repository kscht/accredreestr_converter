"""tools/generate_sql_er_diagram.py"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generate_sql_er_diagram_writes_all_tables(tmp_path: Path) -> None:
    mapping_path = ROOT / "specs" / "sql" / "mapping.json"
    out = tmp_path / "er.md"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "generate_sql_er_diagram.py"),
            "--mapping",
            str(mapping_path),
            "-o",
            str(out),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "```mermaid" in text
    assert "erDiagram" in text
    data = json.loads(mapping_path.read_text(encoding="utf-8"))
    for t in data["tables"]:
        assert t["name"] in text
        for c in t["columns"]:
            assert c["name"] in text
