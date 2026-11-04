"""The dashboard's market context: each figure against a hand-worked answer."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from eulerlab import market_context as mc
from eulerlab.features.panel import PanelRow

START = date(2025, 1, 1)


def _days(n: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def _index_file(
    tmp_path: Path, rows: dict[str, list[float]], extra: dict[str, dict[str, float]] | None = None
) -> Path:
    path = tmp_path / "index_history.jsonl"
    n = len(next(iter(rows.values())))
    lines = []
    for i, day in enumerate(_days(n)):
        cells = {name: {"c": closes[i]} for name, closes in rows.items()}
        for name, fields in (extra or {}).items():
            cells.setdefault(name, {}).update(fields)
        lines.append(json.dumps({"d": day.isoformat(), "indices": cells}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- indices ------------------------------------------------------------------


def test_index_changes_over_each_horizon(tmp_path: Path) -> None:
    closes = [100.0 + i for i in range(300)]
    series = mc.indices(_index_file(tmp_path, {"Nifty 50": closes}))
    strip = mc.index_strip(series)
    nifty = strip["indices"][0]
    assert nifty["name"] == "Nifty 50"
    assert nifty["close"] == 399.0
    assert nifty["change"]["1d"] == pytest.approx(399 / 398 - 1, abs=1e-4)
    assert nifty["change"]["1m"] == pytest.approx(399 / 378 - 1, abs=1e-4)
    assert nifty["change"]["1y"] == pytest.approx(399 / 147 - 1, abs=1e-4)


def test_a_short_history_has_no_long_change(tmp_path: Path) -> None:
    series = mc.indices(_index_file(tmp_path, {"Nifty 50": [100.0, 101.0, 102.0]}))
    change = mc.index_strip(series)["indices"][0]["change"]
    assert change["1d"] is not None
    assert change["1w"] is None and change["1y"] is None


def test_vix_is_ranked_against_the_previous_year(tmp_path: Path) -> None:
    vix = [10.0] * 200 + [20.0] * 51 + [15.0]
    series = mc.indices(_index_file(tmp_path, {"Nifty 50": [1.0] * 252, "India VIX": vix}))
    out = mc.index_strip(series)["vix"]
    assert out["level"] == 15.0
    # 200 of the 251 earlier closes are lower.
    assert out["percentile_1y"] == pytest.approx(100 * 200 / 251, abs=0.1)


def test_percentile_counts_strictly_lower_values() -> None:
    assert mc.percentile_of(3.0, [1.0, 2.0, 3.0, 4.0]) == 50.0
    assert mc.percentile_of(0.0, [1.0, 2.0]) == 0.0
    assert mc.percentile_of(5.0, []) is None


def test_pe_is_ranked_only_from_the_consolidated_basis() -> None:
    """NSE's PE fell from about 40 to 33 when it moved to consolidated
    earnings in April 2021; earlier readings must not make today look cheap."""
    before = [
        mc.IndexDay(date(2020, 1, 1) + timedelta(days=i), 1.0, 40.0, 4.0, 1.0) for i in range(100)
    ]
    after = [
        mc.IndexDay(date(2021, 4, 1) + timedelta(days=i), 1.0, 20.0 + i, 3.0, 1.0)
        for i in range(10)
    ]
    latest = mc.IndexDay(date(2021, 5, 1), 1.0, 25.0, 3.5, 1.0)
    out = mc.valuation({"Nifty 50": [*before, *after, latest]})["indices"][0]
    # Among the 10 post-switch readings (20..29), 5 are lower than 25.
    assert out["pe"]["percentile"] == 50.0
    assert out["pe"]["since"] == "2021-04-01"
    # PB keeps the whole history: 10 of 110 earlier readings (3.0) are lower than 3.5.
    assert out["pb"]["percentile"] == pytest.approx(100 * 10 / 110, abs=0.1)


def test_sector_strength_and_phase() -> None:
    days = _days(100)
    nifty = [mc.IndexDay(d, 100.0, None, None, None) for d in days]
    # IT doubles its pace in the last 5 sessions; FMCG falls steadily.
    it = [
        mc.IndexDay(d, 100.0 * (1.001**i) * (1.01 ** max(0, i - 94)), None, None, None)
        for i, d in enumerate(days)
    ]
    fmcg = [mc.IndexDay(d, 100.0 * (0.999**i), None, None, None) for i, d in enumerate(days)]
    out = mc.sector_strength({"Nifty 50": nifty, "Nifty IT": it, "Nifty FMCG": fmcg})
    rows = {row["name"]: row for row in out["sectors"]}
    assert rows["Nifty IT"]["phase"] == "leading"
    assert rows["Nifty FMCG"]["phase"] == "lagging"
    assert rows["Nifty FMCG"]["relative"]["3m"] == pytest.approx(0.999**63 - 1, abs=1e-4)
    assert [row["name"] for row in out["sectors"]] == ["Nifty IT", "Nifty FMCG"]


def test_a_sector_behind_but_gaining_is_improving() -> None:
    days = _days(100)
    nifty = [mc.IndexDay(d, 100.0, None, None, None) for d in days]
    closes = [100.0 * (0.998**i) for i in range(95)] + [
        100.0 * 0.998**94 * 1.004**k for k in range(1, 6)
    ]
    sector = [mc.IndexDay(d, c, None, None, None) for d, c in zip(days, closes, strict=True)]
    row = mc.sector_strength({"Nifty 50": nifty, "Nifty Auto": sector})["sectors"][0]
    assert row["relative"]["3m"] < 0
    assert row["rising"] is True
    assert row["phase"] == "improving"


def test_each_sector_carries_a_weekly_rotation_trail_ending_today() -> None:
    days = _days(120)
    nifty = [mc.IndexDay(d, 100.0, None, None, None) for d in days]
    fmcg = [mc.IndexDay(d, 100.0 * (0.999**i), None, None, None) for i, d in enumerate(days)]
    row = mc.sector_strength({"Nifty 50": nifty, "Nifty FMCG": fmcg})["sectors"][0]
    assert len(row["trail"]) == mc.TRAIL_WEEKS
    # The last point is today's: the same 3-month lead and momentum the row reports.
    assert row["trail"][-1] == [row["relative"]["3m"], row["momentum"]]
    # A steady fall: every week's 3-month lead is the same, below zero.
    assert all(x == pytest.approx(0.999**63 - 1, abs=1e-4) for x, _ in row["trail"])


# --- breadth ------------------------------------------------------------------


def _row(day: date, symbol: str, close: float, turnover: float = 2e8, isin: str = "") -> PanelRow:
    return PanelRow(
        day=day,
        symbol=symbol,
        close=close,
        volume=1.0,
        turnover=turnover,
        isin=isin or f"INE{symbol}",
    )


def test_a_bonus_issue_is_not_a_crash() -> None:
    """A 1:1 bonus halves the raw close. Adjusted, the stock stays above its
    average and prints no new low."""
    days = _days(270)
    rows = [
        _row(d, "BONUS", 100.0 + i * 0.1 if i < 260 else (100.0 + i * 0.1) / 2)
        for i, d in enumerate(days)
    ]
    raw = mc.breadth(mc.price_grid(rows, {}), sessions=10)
    adjusted = mc.breadth(mc.price_grid(rows, {"INEBONUS": [(days[260], 2.0)]}), sessions=10)
    # The series starts on the ex-date: unadjusted, that day is a new low.
    assert raw["series"]["new_lows"][0] == 1
    assert raw["latest"]["above_200"] == 0.0
    assert sum(adjusted["series"]["new_lows"]) == 0
    assert adjusted["latest"]["new_highs"] == 1
    assert adjusted["latest"]["above_200"] == 100.0


def test_breadth_counts_shares_above_each_average() -> None:
    days = _days(260)
    rows = []
    for i, d in enumerate(days):
        rows.append(_row(d, "UP", 100.0 + i))  # always above its averages
        rows.append(_row(d, "DOWN", 400.0 - i))  # always below
        rows.append(_row(d, "FLAT", 50.0))  # equal: not above
    out = mc.breadth(mc.price_grid(rows, {}), sessions=10)
    latest = out["latest"]
    assert latest["above_20"] == pytest.approx(100 / 3, abs=0.1)
    assert latest["above_200"] == pytest.approx(100 / 3, abs=0.1)
    assert latest["new_highs"] == 1 and latest["new_lows"] == 1
    assert latest["record_high_percent"] == 50.0
    assert [r["symbol"] for r in out["new_high_names"]] == ["UP"]
    assert [r["symbol"] for r in out["new_low_names"]] == ["DOWN"]
    assert len(out["series"]["days"]) == 10


def test_funds_are_not_stocks() -> None:
    days = _days(30)
    rows = [_row(d, "LIQUIDBEES", 1000.0 + i, isin="INF732E01037") for i, d in enumerate(days)]
    rows += [_row(d, "ACME", 10.0) for d in days]
    grid = mc.price_grid(rows, {})
    assert grid.symbols == ["ACME"]


def test_thin_names_are_counted_but_not_listed() -> None:
    days = _days(260)
    rows = [_row(d, "THIN", 10.0 + i, turnover=1e6) for i, d in enumerate(days)]
    out = mc.breadth(mc.price_grid(rows, {}), sessions=3)
    assert out["latest"]["new_highs"] == 1
    assert out["new_high_names"] == []


def test_a_stock_with_too_short_a_history_makes_no_new_high() -> None:
    days = _days(260)
    rows = [_row(d, "NEW", 10.0 + i) for i, d in enumerate(days) if i >= 100]
    out = mc.breadth(mc.price_grid(rows, {}), sessions=3)
    assert out["latest"]["new_highs"] == 0


def test_rolling_mean_needs_most_of_its_window() -> None:
    values = np.array([[1.0], [np.nan], [3.0], [5.0]])
    out = mc.rolling_mean(values, 2)
    assert np.isnan(out[0, 0]) and np.isnan(out[1, 0]) and np.isnan(out[2, 0])
    assert out[3, 0] == 4.0


# --- participant positions -----------------------------------------------------

REPORT = b""""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Oct 27, 2026",,,
Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short
Client,300,100,1,1,50,40,30,20
DII,80,20,1,1,0,0,0,0
FII,25,75,1,1,10,20,30,5
Pro,50,50,1,1,0,0,0,0
TOTAL,455,245,4,4,60,60,60,25
"""


def test_the_participant_report_is_read_with_padded_headers() -> None:
    parsed = mc.parse_positions(REPORT)
    assert parsed is not None
    assert parsed["FII"]["Future Index Long"] == 25
    assert parsed["Client"]["Future Stock Short"] == 1
    assert "TOTAL" not in parsed
    assert mc.parse_positions(b"<html>error</html>") is None


def test_positioning_long_share_and_changes() -> None:
    parsed = mc.parse_positions(REPORT)
    assert parsed is not None
    earlier = json.loads(json.dumps(parsed))
    earlier["FII"]["Future Index Long"] = 50  # 50 / 125 = 0.4
    days = {date(2026, 10, 20 + i): earlier for i in range(6)}
    days[date(2026, 10, 27)] = parsed
    out = mc.positioning(days)
    fii = next(r for r in out["participants"] if r["participant"] == "FII")
    assert fii["index_futures_long_share"] == 0.25
    assert fii["change_1d"] == pytest.approx(0.25 - 0.4)
    assert fii["percentile"] == 0.0
    assert fii["index_calls_net"] == 10 - 30
    assert fii["index_puts_net"] == 20 - 5


def test_position_history_reads_local_files_and_keeps_them(tmp_path: Path) -> None:
    files = {f"participant_oi/2026/10/2026-10-{d:02d}_csv.csv": REPORT for d in (26, 27)}
    reads: list[str] = []

    def read(relative: str) -> bytes:
        reads.append(relative)
        return files[relative]

    history = mc.PositionHistory(tmp_path / "positions.jsonl")
    held = history.days(lambda: sorted(files), read, lambda _: True)
    assert sorted(held) == [date(2026, 10, 26), date(2026, 10, 27)]
    again = mc.PositionHistory(tmp_path / "positions.jsonl")
    again.days(lambda: sorted(files), read, lambda _: True)
    assert len(reads) == 2  # the second history read nothing: both were kept


def test_remote_days_are_read_when_asked_to_wait(tmp_path: Path) -> None:
    files = {"participant_oi/2026/10/2026-10-27_csv.csv": REPORT}
    history = mc.PositionHistory(tmp_path / "positions.jsonl")
    held = history.days(lambda: sorted(files), files.__getitem__, lambda _: False, background=False)
    assert list(held) == [date(2026, 10, 27)]


# --- delivery -----------------------------------------------------------------


def test_last_lines_reads_from_the_end(tmp_path: Path) -> None:
    path = tmp_path / "big.jsonl"
    path.write_bytes(b"".join(f"line {i}\n".encode() for i in range(1000)))
    assert mc.last_lines(path, 3, block=16) == [b"line 997", b"line 998", b"line 999"]
    assert len(mc.last_lines(path, 5000, block=16)) == 1000
    assert mc.last_lines(tmp_path / "absent", 3) == []


def test_delivery_spikes_need_liquidity_and_history() -> None:
    days = [(date(2026, 10, i), {"ACME": 20.0, "THIN": 10.0, "NEWCO": 5.0}) for i in range(1, 21)]
    days[-1] = (date(2026, 10, 20), {"ACME": 50.0, "THIN": 60.0, "NEWCO": 40.0, "FRESH": 90.0})
    days[0] = (date(2026, 10, 1), {"ACME": 20.0, "THIN": 10.0})
    latest = {"ACME": (2e8, 0.03), "THIN": (1e6, 0.1), "NEWCO": (2e8, 0.0), "FRESH": (2e8, 0.0)}
    out = mc.delivery_watch(days, latest)
    names = [row["symbol"] for row in out["stocks"]]
    assert names == ["NEWCO", "ACME"]  # THIN is illiquid; FRESH has no history
    acme = out["stocks"][1]
    assert acme["ratio"] == 2.5 and acme["usual_pct"] == 20.0


def test_too_few_delivery_sessions_say_so() -> None:
    out = mc.delivery_watch([(date(2026, 10, 1), {"A": 1.0})], {})
    assert out["available"] is False


# --- the endpoint ---------------------------------------------------------------


def _fo_zip(lines: list[str]) -> bytes:
    """A minimal F&O bhavcopy, the columns `quotes_from_fo_bhavcopy` reads."""
    import io
    import zipfile

    header = (
        "TradDt,TckrSymb,XpryDt,StrkPric,OptnTp,FinInstrmTp,SttlmPric,ClsPric,"
        "TtlTradgVol,OpnIntrst,UndrlygPric"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("fo.csv", "\n".join([header, *lines]) + "\n")
    return buffer.getvalue()


def test_on_expiry_day_the_chain_is_the_next_open_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bhavcopy is end of day: a chain expiring on the trade date is
    settled, and its straddle is no straddle (HISTORY #31)."""
    from eulerlab.api import server
    from eulerlab.ingest import landing_reader

    lines = []
    for expiry, base in (("2026-10-27", 0.0), ("2026-11-03", 100.0)):
        for strike in (22700, 22750, 22800):
            lines.append(
                f"2026-10-27,NIFTY,{expiry},{strike},CE,IDO,{base + 60},{base + 60},900,5000,22750"
            )
            lines.append(
                f"2026-10-27,NIFTY,{expiry},{strike},PE,IDO,{base + 55},{base + 55},800,6000,22750"
            )
    payload = _fo_zip(lines)
    monkeypatch.setattr(
        landing_reader, "available", lambda *a, **k: ["fo/2026/10/2026-10-27_udiff.zip"]
    )
    monkeypatch.setattr(landing_reader, "read", lambda *a, **k: payload)

    chosen = server._chain_payload("NIFTY", "", "", summary=True)
    assert chosen["expiry"] == "2026-11-03"
    asked = server._chain_payload("NIFTY", "", "2026-10-27", summary=True)
    assert asked["expiry"] == "2026-10-27"  # still reachable when asked for


def test_one_broken_section_does_not_blank_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.api import server

    def broken() -> dict[str, object]:
        raise ValueError("bad file")

    monkeypatch.setattr(
        server, "_breadth_and_latest", lambda: ({"available": False, "reason": "loading"}, {})
    )
    monkeypatch.setattr(server, "_positioning", broken)
    monkeypatch.setattr(server, "_options_context", lambda: {"available": False, "reason": "none"})
    monkeypatch.setattr(mc, "indices", lambda path=mc.INDEX_HISTORY: {})
    monkeypatch.setattr(server, "_MARKET_CONTEXT", {})
    out = server.market_context_route()
    assert out["positioning"] == {"available": False, "reason": "ValueError: bad file"}
    assert out["delivery"]["reason"] == "the price panel is loading"
    assert out["strip"]["available"] is False
    assert server._MARKET_CONTEXT == {}  # an incomplete answer is not kept


# --- what the charts are sent (ADR-082) --------------------------------------------


def test_thin_keeps_the_shape_and_the_last_value() -> None:
    values = [float(i) for i in range(252)]
    out = mc.thin(values, 64)
    assert len(out) == 64
    assert out[0] == 0.0 and out[-1] == 251.0
    assert out == sorted(out)
    assert mc.thin([1.0, 2.0], 64) == [1.0, 2.0]


def test_each_index_carries_a_year_line(tmp_path: Path) -> None:
    series = mc.indices(_index_file(tmp_path, {"Nifty 50": [100.0 + i for i in range(300)]}))
    row = mc.index_strip(series)["indices"][0]
    assert len(row["spark"]) == mc.SPARK_POINTS
    assert row["spark"][-1] == 399.0


def test_valuation_carries_the_range_for_its_bar() -> None:
    days = [
        mc.IndexDay(date(2021, 4, 1) + timedelta(days=i), 1.0, 20.0 + i, 3.0, 1.0)
        for i in range(10)
    ]
    latest = mc.IndexDay(date(2021, 5, 1), 1.0, 25.0, 3.5, 1.0)
    pe = mc.valuation({"Nifty 50": [*days, latest]})["indices"][0]["pe"]
    assert (pe["low"], pe["high"], pe["median"]) == (20.0, 29.0, 24.5)


def test_sectors_carry_their_momentum_for_the_rotation_chart() -> None:
    days = _days(100)
    nifty = [mc.IndexDay(d, 100.0, None, None, None) for d in days]
    it = [
        mc.IndexDay(d, 100.0 * (1.001**i) * (1.01 ** max(0, i - 94)), None, None, None)
        for i, d in enumerate(days)
    ]
    row = mc.sector_strength({"Nifty 50": nifty, "Nifty IT": it})["sectors"][0]
    assert row["momentum"] is not None and row["momentum"] > 0
    assert row["phase"] == "leading"


def test_positioning_carries_each_groups_usual_share() -> None:
    parsed = mc.parse_positions(REPORT)
    assert parsed is not None
    days = {date(2026, 10, 20 + i): parsed for i in range(4)}
    fii = next(r for r in mc.positioning(days)["participants"] if r["participant"] == "FII")
    assert fii["usual"] == 0.25
