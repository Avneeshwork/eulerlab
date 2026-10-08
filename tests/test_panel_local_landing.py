"""The panel reads a day still in local landing from disk, not from B2.

On 2026-10-08 the cloud sync failed and `make daily` stopped before the panel,
so the paper books stayed a day behind. A day that is on disk must not need
the cloud at all.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from eulerlab.features.panel import build, read_panel

UDIFF = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
    "2026-10-08,2026-10-08,CM,NSE,STK,1,INE000A01001,ACME,EQ,,,,,ACME,100,110,95,105,"
    "105,99,,105,,,5000,525000,200,F1,1,,,,,\n"
)


def _land(root: Path, day: str) -> Path:
    key = f"cm/{day[:4]}/{day[5:7]}/{day}_udiff.zip"
    (root / key).parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bhav.csv", UDIFF)
    (root / key).write_bytes(buf.getvalue())
    manifest = root / "manifest.jsonl"
    manifest.write_text(
        json.dumps({"segment": "cm", "trade_date": day, "path": key}) + "\n", encoding="utf-8"
    )
    return manifest


def test_a_landed_day_builds_without_cloud_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("B2_KEY_ID", raising=False)
    monkeypatch.delenv("B2_APP_KEY", raising=False)
    manifest = _land(tmp_path / "nse", "2026-10-08")
    panel = tmp_path / "panel.jsonl"

    written, note = build(start="2026-10-01", end="2026-10-31", manifest=manifest, path=panel)

    assert (written, note) == (1, "")
    rows = read_panel(panel)
    assert [(r.symbol, r.close) for r in rows] == [("ACME", 105.0)]


def test_a_second_build_writes_nothing(tmp_path: Path) -> None:
    manifest = _land(tmp_path / "nse", "2026-10-08")
    panel = tmp_path / "panel.jsonl"
    build(start="2026-10-01", end="2026-10-31", manifest=manifest, path=panel)
    first = panel.read_bytes()

    assert build(start="2026-10-01", end="2026-10-31", manifest=manifest, path=panel) == (0, "")
    assert panel.read_bytes() == first
