"""The Market Handbook page is built from docs/METRICS and TASKS.md (ADR-104)."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "handbook", Path("tools/render_metrics_handbook.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_handbook_carries_every_page_and_no_raw_markdown() -> None:
    tool = _tool()
    page = tool.build()
    data = json.loads(re.search(r"const DATA = (\{.*?\});\n", page, re.DOTALL).group(1))  # type: ignore[union-attr]
    on_disk = {p.stem for p in Path("docs/METRICS").glob("*/*.md")}
    assert {p["id"] for p in data["pages"]} == on_disk
    vix = next(p for p in data["pages"] if p["id"] == "india-vix")
    assert "<strong>In one line:</strong>" in vix["html"] and "**" not in vix["html"]
    assert 'data-page="atm-implied-volatility"' in vix["html"]
    assert "</script" not in json.dumps(data)


def test_waiting_lists_only_open_operator_tasks(tmp_path: Path) -> None:
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(
        "| T-1 | decide a thing | TODO. Operator |\n"
        "| T-2 | build a thing | TODO |\n"
        "| T-3 | decided | DONE. Operator |\n"
    )
    assert [t["id"] for t in _tool().waiting(tasks)] == ["T-1"]
