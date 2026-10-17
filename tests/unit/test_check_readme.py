"""scripts/check_readme.py rejects a README that would mislead a judge."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_readme.py"

REQUIRED = """
# Demo

## Problem & why a graph
## Architecture diagram
## Graph data model
## Cypher & algorithms
## Interfaces
## Tracks entered
## Evaluation
## Security model
## Limitations
## AI disclosure
## License

See [issues](docs/KNOWN_ISSUES.md).
"""


def _load():
    spec = importlib.util.spec_from_file_location("check_readme", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_repo_readme_passes():
    module = _load()
    assert module.main(["--root", str(ROOT)]) == 0


def test_missing_heading_fails(tmp_path: Path):
    module = _load()
    readme = tmp_path / "README.md"
    readme.write_text(REQUIRED.replace("## License\n", ""), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "KNOWN_ISSUES.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "docs" / "NUMBERS.md").write_text(
        "<!-- NUMBERS:BEGIN -->\n<!-- NUMBERS:END -->\n", encoding="utf-8"
    )
    assert module.main(["--root", str(tmp_path)]) == 1
    assert "License" in " ".join(module.missing_headings(readme.read_text(encoding="utf-8")))


def test_dead_docs_link_fails(tmp_path: Path):
    module = _load()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "NUMBERS.md").write_text(
        "<!-- NUMBERS:BEGIN -->\n<!-- NUMBERS:END -->\n", encoding="utf-8"
    )
    text = REQUIRED.replace("docs/KNOWN_ISSUES.md", "docs/missing.md")
    (tmp_path / "README.md").write_text(text, encoding="utf-8")
    assert module.main(["--root", str(tmp_path)]) == 1


def test_fenced_heading_does_not_count(tmp_path: Path):
    module = _load()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "NUMBERS.md").write_text(
        "<!-- NUMBERS:BEGIN -->\n<!-- NUMBERS:END -->\n", encoding="utf-8"
    )
    text = REQUIRED.replace("## License\n", "```\n## License\n```\n")
    (tmp_path / "docs" / "KNOWN_ISSUES.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(text, encoding="utf-8")
    assert "License" in module.missing_headings(text)


def test_unlisted_number_fails(tmp_path: Path):
    module = _load()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "KNOWN_ISSUES.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "docs" / "NUMBERS.md").write_text(
        "<!-- NUMBERS:BEGIN -->\n<!-- NUMBERS:END -->\n", encoding="utf-8"
    )
    text = REQUIRED + "\nThe made-up latency is 999.5 ms.\n"
    (tmp_path / "README.md").write_text(text, encoding="utf-8")
    assert module.main(["--root", str(tmp_path)]) == 1
