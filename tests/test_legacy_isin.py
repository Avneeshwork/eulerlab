"""Pre-2011 rows get an ISIN only through a checkable chain (ADR-187)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from eulerlab.master import legacy_isin as li

DAYS = [f"2011-01-{d:02d}" for d in range(3, 13)]  # ten sessions


def _staging(tmp_path: Path, rows: list[tuple[int, str, str]]) -> Path:
    path = tmp_path / "staging.jsonl"
    ordered = sorted(rows)
    path.write_text(
        "".join(
            json.dumps({"d": DAYS[i], "s": s, "isin": isin, "c": 1.0}, sort_keys=True) + "\n"
            for i, s, isin in ordered
        )
    )
    return path


def _filled(
    tmp_path: Path,
    rows: list[tuple[int, str, str]],
    changes: list[li.SymbolChange],
    max_gap: int = 3,
) -> tuple[dict[tuple[str, str], str], li.FillReport]:
    out = tmp_path / "out.jsonl"
    report = li.fill(_staging(tmp_path, rows), out, changes, max_gap=max_gap)
    got = {(r["d"], r["s"]): r["isin"] for r in map(json.loads, out.read_text().splitlines())}
    return got, report


def test_the_symbol_change_list_parses_as_nse_publishes_it() -> None:
    payload = (
        b"NAME OF THE COMPANY,OLD SYMBOL,NEW SYMBOL,EFFECTIVE DATE\n"
        b"iGate Global Solutions Limited,MASCOT,IGS,07-AUG-2003\n"
        b",780LTFL30,799LTFL30,19-FEB-2025\n"
    )
    assert li.parse_symbol_changes(payload) == [
        li.SymbolChange("MASCOT", "IGS", date(2003, 8, 7)),
        li.SymbolChange("780LTFL30", "799LTFL30", date(2025, 2, 19)),
    ]


def test_a_renamed_symbol_follows_its_change_to_the_anchor(tmp_path: Path) -> None:
    rows = [(i, "OLD", "") for i in range(3)] + [(i, "NEW", "") for i in range(3, 6)]
    rows += [(i, "NEW", "INE000A01011") for i in range(6, 10)]
    got, report = _filled(tmp_path, rows, [li.SymbolChange("OLD", "NEW", date(2011, 1, 6))])
    assert got[(DAYS[0], "OLD")] == got[(DAYS[4], "NEW")] == "INE000A01011"
    assert report.filled == 6 and not report.left_out


def test_a_long_silence_is_not_bridged(tmp_path: Path) -> None:
    rows = [(0, "GONE", ""), (6, "GONE", "INE111A01011"), (7, "GONE", "INE111A01011")]
    # The market kept trading; ISINs start on day 6 for everyone.
    rows += [(i, "DAILY", "INE999A01011" if i >= 6 else "") for i in range(10)]
    got, report = _filled(tmp_path, rows, [])
    assert (DAYS[0], "GONE") not in got
    assert report.left_out["gap in trading"] == 1


def test_a_symbol_another_company_takes_over_is_ambiguous(tmp_path: Path) -> None:
    rows = [(i, "ABC", "") for i in range(4)] + [(i, "ABC", "INE222A01011") for i in range(4, 6)]
    takeover = li.SymbolChange("XYZ", "ABC", date(2011, 1, 5))
    got, report = _filled(tmp_path, rows, [takeover])
    assert (DAYS[0], "ABC") not in got
    assert report.left_out["symbol taken over"] >= 1


def test_an_anchor_with_two_isins_is_left_out(tmp_path: Path) -> None:
    rows = [(0, "TWO", ""), (1, "TWO", "INE333A01011"), (2, "TWO", "INE444A01011")]
    got, report = _filled(tmp_path, rows, [])
    assert (DAYS[0], "TWO") not in got
    assert report.left_out["anchor has two ISINs"] == 1


def test_two_symbols_resolving_to_one_isin_on_a_day_are_both_left_out(tmp_path: Path) -> None:
    rows = [(0, "A", ""), (0, "B", ""), (1, "B", ""), (2, "C", "INE555A01011")]
    changes = [
        li.SymbolChange("A", "C", date(2011, 1, 5)),
        li.SymbolChange("B", "C", date(2011, 1, 5)),
    ]
    got, report = _filled(tmp_path, rows, changes)
    assert (DAYS[0], "A") not in got and (DAYS[0], "B") not in got
    assert report.left_out["two symbols, one ISIN"] == 2


def test_a_symbol_that_never_gains_an_isin_is_left_out(tmp_path: Path) -> None:
    got, report = _filled(tmp_path, [(0, "DELISTED", ""), (1, "OTHER", "INE666A01011")], [])
    assert (DAYS[0], "DELISTED") not in got
    assert report.left_out["no anchor"] == 1
