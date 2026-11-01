"""Risk on the deployed book, each figure pinned on numbers worked by hand (ADR-071)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.risk import book as rb
from eulerlab.risk import report, watch

START = date(2026, 1, 1)


def days(count: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(count)]


def series(moves: list[float], start: float = 100.0) -> dict[date, float]:
    """Closes that produce exactly these day-on-day returns."""
    out, price = {START: start}, start
    for i, move in enumerate(moves, start=1):
        price *= 1 + move
        out[START + timedelta(days=i)] = price
    return out


def book(
    name: str, holdings: dict[str, float], *, capital: float = 1000.0, cash: float = 0.0
) -> rb.Book:
    held = tuple(rb.Holding(symbol, 1.0, value, value) for symbol, value in holdings.items())
    return rb.Book(name, name, name, capital, sum(holdings.values()) + cash, cash, held, ())


# --- the book run through history ---------------------------------------------------


def test_each_past_day_is_applied_to_todays_rupees() -> None:
    prices = {"A": series([0.10, -0.05]), "B": series([0.00, 0.02])}
    pnl, covered = rb.scenario_pnl(book("x", {"A": 1000.0, "B": 500.0}), prices, days(3))
    assert pnl == pytest.approx([100.0, -40.0])  # 1000*0.10 ; 1000*-0.05 + 500*0.02
    assert covered == 1.0


def test_a_name_with_no_price_is_flat_that_day_and_lowers_coverage() -> None:
    prices = {"A": series([0.10, -0.05]), "NEW": {START + timedelta(days=2): 50.0}}
    pnl, covered = rb.scenario_pnl(book("x", {"A": 1000.0, "NEW": 1000.0}), prices, days(3))
    assert pnl == pytest.approx([100.0, -50.0])
    assert covered == 0.5


def test_var_is_the_kth_worst_day_and_shortfall_the_average_of_the_tail() -> None:
    pnl = [float(v) for v in range(-10, 90)]  # 100 days: -10 .. 89
    var95, es95 = rb.quantile_loss(pnl, 0.95)  # 5 days outside: -10..-6
    assert var95 == 6.0
    assert es95 == 8.0
    var99, es99 = rb.quantile_loss(pnl, 0.99)
    assert (var99, es99) == (10.0, 10.0)
    assert rb.quantile_loss([1.0, 2.0, 3.0], 0.95) == (0.0, 0.0), "a book that never lost"
    assert rb.quantile_loss([], 0.95) == (0.0, 0.0)


def test_the_normal_curve_uses_the_known_multipliers() -> None:
    pnl = [-100.0, 100.0] * 50  # mean 0, sample sd 100.5038
    table = {row["method"]: row for row in rb.var_table(pnl)}
    assert table["normal"]["var95"] == pytest.approx(1.6449 * 100.5038, abs=0.05)
    assert table["normal"]["var99"] == pytest.approx(2.3263 * 100.5038, abs=0.05)
    assert table["normal"]["es95"] == pytest.approx(2.0627 * 100.5038, abs=0.05)
    assert table["historical"]["var95"] == 100.0


def test_recent_days_weigh_more() -> None:
    calm_then_wild = [1.0] * 100 + [10.0] * 10
    wild_then_calm = [10.0] * 10 + [1.0] * 100
    assert rb.recent_sd(calm_then_wild) > 5 > rb.recent_sd(wild_then_calm)
    assert rb.recent_sd([3.0, -3.0], decay=1.0) == pytest.approx(3.0)


def test_components_sum_to_the_total_and_a_hedge_is_negative() -> None:
    a = [10.0, -10.0, 20.0, -20.0]
    parts = {"a": a, "b": [v / 2 for v in a], "hedge": [-v / 4 for v in a]}
    found = rb.components(parts, 100.0)
    assert sum(found.values()) == pytest.approx(100.0)
    # The book is 1.25 a: shares are 1 / 0.5 / -0.25 over 1.25.
    assert found == pytest.approx({"a": 80.0, "b": 40.0, "hedge": -20.0})
    assert rb.components({"flat": [0.0, 0.0]}, 50.0) == {"flat": 0.0}


def test_correlation_and_beta() -> None:
    a = [0.01, -0.02, 0.03, -0.01] * 20
    assert rb.correlation(a, [2 * v for v in a]) == pytest.approx(1.0)
    assert rb.correlation(a, [-v for v in a]) == pytest.approx(-1.0)
    assert rb.correlation(a, [0.0] * len(a)) is None, "a flat book correlates with nothing"
    # A book of 1,000 that makes 1.5x the market's return each day has beta 1.5.
    assert rb.beta([1.5 * v * 1000 for v in a], 1000.0, a) == pytest.approx(1.5)
    assert rb.beta([1.0] * 10, 1000.0, [0.01] * 10) is None, "too few days"
    assert rb.name_beta([0.5 * v for v in a], a) == pytest.approx(0.5)


def test_the_histogram_counts_every_day_into_round_bins() -> None:
    bins = rb.histogram([-12.0, -3.0, 4.0, 9.0], 1000.0, bins=4)  # -1.2% .. +0.9%
    assert [(b["from"], b["to"]) for b in bins] == [
        (-2.0, -1.0),
        (-1.0, 0.0),
        (0.0, 1.0),
        (1.0, 2.0),
    ]
    assert [b["days"] for b in bins] == [1, 1, 2, 0]
    assert rb.histogram([], 1000.0) == []
    # One freak day in 200 does not set the scale: it lands in the end bin.
    wide = rb.histogram([1.0, -1.0] * 100 + [500.0], 1000.0, bins=4)
    assert wide[-1]["to"] <= 0.5 and sum(b["days"] for b in wide) == 201


# --- equity paths -------------------------------------------------------------------


def test_drawdown_is_measured_from_the_highest_point_so_far() -> None:
    d = days(5)
    found = rb.drawdown(list(zip(d, [100.0, 110.0, 99.0, 104.5, 121.0], strict=True)))
    assert found["deepest"] == pytest.approx(-0.10) and found["deepest_day"] == d[2].isoformat()
    assert found["now"] == 0.0 and found["peak_day"] == d[4].isoformat()
    assert [round(v, 2) for _, v in found["path"]] == [0.0, 0.0, -0.1, -0.05, 0.0]


def test_the_book_curve_counts_money_not_yet_started_and_carries_the_last_value() -> None:
    d = days(3)
    early = rb.Book("e", "e", "e", 100.0, 120.0, 0.0, (), ((d[0], 110.0), (d[1], 120.0)))
    late = rb.Book("l", "l", "l", 50.0, 45.0, 0.0, (), ((d[2], 45.0),))
    assert rb.combined_curve([early, late]) == [(d[0], 160.0), (d[1], 170.0), (d[2], 165.0)]
    assert rb.today_pnl(early, d[1]) == 10.0
    assert rb.today_pnl(early, d[2]) == 0.0, "its curve stops a day short: no figure for today"


def test_the_backtest_band_is_percentiles_of_every_stretch_of_that_length() -> None:
    backtest = [100.0 * 1.01**i for i in range(200)]  # 1% every day, exactly
    band = rb.backtest_band(backtest, 3)
    assert [row["day"] for row in band] == [0, 1, 2, 3]
    assert band[3]["low"] == pytest.approx(103.0301) == band[3]["high"]
    assert rb.backtest_band([100.0, 101.0], 5) == [
        {"day": 0, "low": 100.0, "mid": 100.0, "high": 100.0}
    ]


def test_a_deployment_is_judged_against_its_backtest_only_after_twenty_days() -> None:
    backtest = [100.0 * 1.001**i for i in range(400)]
    d = days(30)

    def live(count: int, end: float) -> rb.Book:
        curve = tuple((d[i], 1000.0 + (end - 1000.0) * (i + 1) / count) for i in range(count))
        return rb.Book("x", "x", "x", 1000.0, end, 0.0, (), curve)

    assert rb.against_backtest(live(5, 900.0), backtest)["verdict"] == "too_early"
    assert rb.against_backtest(live(25, 900.0), backtest)["verdict"] == "below"
    assert rb.against_backtest(live(25, 1200.0), backtest)["verdict"] == "above"
    inside = rb.against_backtest(live(25, 1000.0 * 1.001**25), backtest)
    assert inside["verdict"] == "inside" and inside["expected"] == pytest.approx(
        1.001**25 - 1, abs=1e-5
    )
    assert rb.against_backtest(live(25, 1000.0), [])["verdict"] == "no_backtest"


# --- exposure, stress, limits -------------------------------------------------------


def test_a_name_held_twice_is_one_position_in_the_book() -> None:
    names = rb.by_name([book("a", {"X": 100.0, "Y": 50.0}), book("b", {"X": 200.0})])
    assert [(n["symbol"], n["value"], n["held_by"]) for n in names] == [
        ("X", 300.0, ["a", "b"]),
        ("Y", 50.0, ["a"]),
    ]
    grouped = rb.by_sector(names, {"X": "Banks"})
    assert [(g["sector"], g["value"]) for g in grouped] == [
        ("Banks", 300.0),
        ("Unclassified", 50.0),
    ]
    assert grouped[0]["share"] == pytest.approx(300 / 350, abs=1e-6)


def test_stress_moves_each_name_by_its_beta_and_a_missing_beta_is_one() -> None:
    names = rb.by_name([book("a", {"X": 1000.0, "Y": 500.0})])
    found = {
        row["key"]: row
        for row in rb.stress(
            names, {"X": 2.0, "Y": None}, {"X": "Banks", "Y": "IT"}, 2000.0, ("2026-03-13", -77.0)
        )
    }
    assert found["nifty_10"]["loss"] == -250.0  # 1000*2*-0.10 + 500*1*-0.10
    assert found["nifty_10"]["share"] == -0.125
    assert found["sector"]["label"].startswith("Banks") and found["sector"]["loss"] == -80.0
    assert found["name"]["loss"] == -200.0 and found["name"]["note"] == "X"
    assert found["worst_day"]["loss"] == -77.0


def test_a_limit_row_says_how_much_is_used() -> None:
    assert rb.limit_row("x", 50.0, 100.0, "INR", "enforced", "w")["state"] == "ok"
    assert rb.limit_row("x", 80.0, 100.0, "INR", "enforced", "w")["state"] == "near"
    over = rb.limit_row("x", 120.0, 100.0, "INR", "enforced", "w")
    assert over["state"] == "over" and over["used"] == 1.2


def test_a_deployment_with_no_state_is_all_cash() -> None:
    found = rb.book_from_state("d", "s", "S", 5000.0, "active", None)
    assert (found.equity, found.cash, found.holdings, found.curve) == (5000.0, 5000.0, (), ())


# --- the payload --------------------------------------------------------------------


def _payload(books: list[rb.Book], prices: dict[str, dict[date, float]]) -> dict:  # type: ignore[type-arg]
    return report.build(
        books,
        prices,
        {"A": "Banks", "B": "IT"},
        enforced={"max_daily_loss": 10_000.0, "max_position_notional": 500_000.0},
        watch=watch.WatchLevels(),
        backtests={},
    )


def test_the_payload_adds_up() -> None:
    moves = [0.01, -0.02, 0.015, -0.005] * 30  # 120 days
    prices = {"A": series(moves), "B": series([-m / 2 for m in moves]), rb.MARKET: series(moves)}
    books = [book("one", {"A": 1000.0}, cash=100.0), book("two", {"A": 500.0, "B": 500.0})]
    found = _payload(books, prices)
    assert found["enough_history"] and found["history_days"] == 120
    total = found["book"]
    assert total["equity"] == 2100.0 and total["invested"] == 2000.0 and total["cash"] == 100.0
    assert total["names"] == 2 and total["shared_names"] == 1
    # The parts of the VaR sum to the whole, and the shares to one.
    assert sum(r["var_component"] for r in found["deployments"]) == pytest.approx(
        total["var95"], abs=0.02
    )
    assert sum(r["var_share"] for r in found["deployments"]) == pytest.approx(1.0, abs=1e-4)
    assert total["diversification"] >= 0
    assert sum(b["days"] for b in found["var"]["histogram"]) == 120
    # "one" is all A, which is the market: beta of its holdings is 1.
    assert found["deployments"][0]["beta"] == pytest.approx(1000 / 1100, abs=1e-3)
    assert found["correlation"]["matrix"][0][0] == 1.0
    assert {row["kind"] for row in found["limits"]} == {"enforced", "watch"}


def test_too_little_history_gives_no_risk_figure_rather_than_a_guess() -> None:
    prices = {"A": series([0.01] * 10)}
    found = _payload([book("one", {"A": 1000.0})], prices)
    assert found["enough_history"] is False
    assert found["var"]["methods"] == [] and found["book"]["var95"] == 0.0
    assert (
        found["deployments"][0]["var95"] is None and found["deployments"][0]["volatility"] is None
    )


def test_a_flat_deployment_is_marked_and_has_no_risk() -> None:
    moves = [0.01, -0.02] * 40
    prices = {"A": series(moves), rb.MARKET: series(moves)}
    found = _payload(
        [book("flat", {}, capital=5000.0, cash=5000.0), book("held", {"A": 1000.0})], prices
    )
    flat = found["deployments"][0]
    assert flat["flat"] is True and flat["var95"] == 0.0 and flat["beta"] is None
    assert found["correlation"]["matrix"][0] == [None, None]
    assert found["deployments"][1]["var_share"] == pytest.approx(1.0)


def test_two_deployments_of_one_strategy_are_told_apart_by_capital() -> None:
    moves = [0.01, -0.02] * 40
    prices = {"A": series(moves)}
    a = rb.Book(
        "a", "s", "Momentum", 100000.0, 100000.0, 0.0, (rb.Holding("A", 1, 1.0, 1000.0),), ()
    )
    # Rs 10,000 at the start and Rs 20,000 deposited: named by the Rs 30,000
    # in it now, not the starting capital (T-4345).
    b = rb.Book(
        "b",
        "s",
        "Momentum",
        10000.0,
        30000.0,
        0.0,
        (rb.Holding("A", 1, 1.0, 100.0),),
        (),
        flows=((date(2026, 10, 1), 20000.0),),
    )
    titles = [row["title"] for row in _payload([a, b], prices)["deployments"]]
    assert titles == ["₹1 L in · Momentum", "₹30,000 in · Momentum"]


def test_watch_levels_come_from_the_file_and_reject_an_unknown_key(tmp_path: Path) -> None:
    path = tmp_path / "w.yaml"
    path.write_text("book_var_pct: 1.5\n", encoding="utf-8")
    assert watch.load(path).book_var_pct == 1.5 and watch.load(path).sector_pct == 35.0
    assert watch.load(tmp_path / "absent.yaml") == watch.WatchLevels()
    path.write_text("stop_trading_at: 3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        watch.load(path)
    assert watch.load(Path("config/risk_watch.yaml")).book_drawdown_pct > 0


# --- a position held only overnight (ADR-072) ---------------------------------------


def rule(
    gaps: list[float], held: set[int], *, notional: float = 1000.0, held_now: float = 0.0
) -> rb.GapRule:
    """A gap rule whose morning i (1-based) gapped by gaps[i - 1]."""
    mornings = {START + timedelta(days=i): move for i, move in enumerate(gaps, start=1)}
    return rb.GapRule(
        contract="NIFTY-FUT",
        lots=1,
        lot_size=10,
        notional=notional,
        gaps=mornings,
        held=frozenset(START + timedelta(days=i) for i in held),
        held_now=held_now,
        worst=(date(2020, 3, 23), -0.10),
    )


def test_a_gap_rule_makes_money_only_on_the_nights_it_held() -> None:
    found = rb.rule_pnl(rule([0.01, -0.02, 0.03], {1, 2}), days(4))
    assert found == pytest.approx([10.0, -20.0, 0.0])


def test_the_var_on_a_night_it_holds_uses_only_those_nights() -> None:
    # 100 nights; it held the 40 even ones, and lost 5% on two of them.
    gaps = [0.001] * 100
    gaps[9] = -0.05
    gaps[19] = -0.05
    gaps[10] = -0.30  # a night it sat out: never met
    held = set(range(2, 101, 2))
    found = rb.gap_summary(rule(gaps, held), days(101))
    assert (found["nights"], found["nights_held"], found["held_share"]) == (100, 50, 0.5)
    # 50 nights, 5% outside: k = 3, so the third worst, which is a +0.1% night.
    assert found["var95_when_held"] == 0.0
    assert found["es95_when_held"] == pytest.approx((50.0 + 50.0 - 1.0) / 3, abs=0.01)
    assert found["worst_night"] == {"day": (START + timedelta(days=10)).isoformat(), "pnl": -50.0}
    assert found["worst_ever"] == {"day": "2020-03-23", "gap": -0.1, "pnl": -100.0}
    assert found["holds_tonight"] is False


def test_too_few_nights_held_gives_no_gap_var() -> None:
    found = rb.gap_summary(rule([-0.01] * 100, {1, 2, 3}), days(101))
    assert found["enough"] is False and found["var95_when_held"] == 0.0


def test_a_futures_deployment_is_in_the_book_var_and_is_not_flat() -> None:
    moves = [0.01, -0.02, 0.015, -0.005] * 30
    prices = {"A": series(moves), rb.MARKET: series(moves)}
    gaps = [-0.03 if i % 10 == 0 else 0.002 for i in range(120)]
    future = rb.Book(
        "fut",
        "nifty_calm_rise_overnight",
        "Overnight",
        5000.0,
        5000.0,
        5000.0,
        (),
        (),
        rule=rule(gaps, set(range(1, 121)), notional=4000.0),
    )
    shares = book("shares", {"A": 1000.0})
    alone = _payload([shares], prices)
    both = _payload([shares, future], prices)
    row = both["deployments"][1]
    assert row["flat"] is False and row["gap"]["notional"] == 4000.0
    assert row["var95"] == pytest.approx(120.0)  # the 3% gaps on 4,000
    assert both["book"]["var95"] > alone["book"]["var95"]
    assert sum(r["var_component"] for r in both["deployments"]) == pytest.approx(
        both["book"]["var95"], abs=0.02
    )
    # Stopping the future leaves the shares' own VaR, and the other way round.
    assert row["var_without"] == pytest.approx(alone["book"]["var95"], abs=0.01)
    keys = {s["key"] for s in both["stress"]}
    assert {"gap_3", "gap_worst"} <= keys and "gap_3" not in {s["key"] for s in alone["stress"]}
    gap3 = next(s for s in both["stress"] if s["key"] == "gap_3")
    assert gap3["loss"] == -120.0
    # A bad night is set beside the kill switch's daily loss.
    assert any(row["name"].startswith("A bad night in the future") for row in both["limits"])


# --- adding and removing a deployment -----------------------------------------------


def test_a_deployment_keeps_its_colour_slot_and_a_stopped_one_is_listed_apart() -> None:
    moves = [0.01, -0.02] * 40
    prices = {"A": series(moves)}
    gone = rb.Book(
        "old", "s", "Old", 1000.0, 1100.0, 1100.0, (), ((START, 1100.0),), status="stopped"
    )
    found = report.build(
        [book("new", {"A": 1000.0})],
        prices,
        {},
        enforced={"max_daily_loss": 10_000.0, "max_position_notional": 500_000.0},
        watch=watch.WatchLevels(),
        backtests={},
        slots={"old": 0, "new": 1},
        stopped=[gone],
    )
    assert [(d["id"], d["slot"]) for d in found["deployments"]] == [("new", 1)]
    assert found["stopped"][0]["made"] == 100.0 and found["stopped"][0]["slot"] == 0
    # The stopped one is in no total and no risk figure.
    assert found["book"]["equity"] == 1000.0 and found["book"]["deployments"] == 1


def test_what_if_says_what_adding_a_strategy_does_to_the_book() -> None:
    moves = [0.01, -0.02, 0.015, -0.005] * 30
    prices = {"A": series(moves), "B": series([-m for m in moves])}
    held = [book("one", {"A": 1000.0})]
    same = report.what_if(held, book("candidate", {"A": 1000.0}), prices)
    assert same["var_after"] == pytest.approx(2 * same["var_before"])
    assert same["correlation_with_book"] == pytest.approx(1.0)
    assert same["most_alike"] == {"title": "one", "correlation": 1.0}
    hedge = report.what_if(held, book("candidate", {"B": 1000.0}), prices)
    assert hedge["var_after"] < hedge["var_before"] and hedge["var_added"] < 0
    first = report.what_if([], book("candidate", {"A": 1000.0}), prices)
    assert first["var_before"] == 0.0 and first["var_after"] == first["var_own"]
    short = report.what_if(held, book("candidate", {"A": 1.0}), {"A": series([0.01] * 5)})
    assert short == {"enough_history": False, "history_days": 5}


def test_an_exact_file_is_looked_up_as_a_file_not_a_folder() -> None:
    from eulerlab.ingest import landing_reader

    assert landing_reader._literal_prefix("history/*.jsonl.gz") == "history/"
    assert landing_reader._literal_prefix("*/*/*.jsonl.gz") == ""
    assert (
        landing_reader._literal_prefix("2026/10/2026-10-13_udiff.zip")
        == "2026/10/2026-10-13_udiff.zip"
    )


# --- deposits and withdrawals are not profit ----------------------------------------


def _deposited() -> rb.Book:
    """₹1,000 that earns 10%, then ₹1,000 more added, then 10% again on the lot."""
    d = days(3)
    curve = ((d[0], 1000.0), (d[1], 1100.0), (d[2], 2310.0))
    return rb.Book("x", "s", "x", 1000.0, 2310.0, 2310.0, (), curve, flows=((d[2], 1000.0),))


def test_a_deposit_is_not_profit() -> None:
    """2026-10-17: adding money showed as profit on the paper trading pages."""
    b = _deposited()
    assert b.deployed == 2000.0 and b.made == pytest.approx(310.0)
    assert b.total_return == pytest.approx(1.1 * 1.1 - 1)
    assert rb.today_pnl(b, days(3)[2]) == pytest.approx(210.0), "not 1,210"


def test_a_withdrawal_is_not_a_loss_or_a_drawdown() -> None:
    d = days(3)
    curve = ((d[0], 1000.0), (d[1], 1100.0), (d[2], 600.0))
    b = rb.Book("x", "s", "x", 1000.0, 600.0, 600.0, (), curve, flows=((d[2], -500.0),))
    assert b.made == pytest.approx(100.0) and b.total_return == pytest.approx(0.1)
    assert rb.today_pnl(b, d[2]) == 0.0
    assert rb.drawdown(b.growth())["now"] == 0.0


def test_live_against_backtest_takes_the_deposit_out() -> None:
    live = rb.against_backtest(_deposited(), [])["live"]
    assert [p["value"] for p in live] == [100.0, 100.0, 110.0, 121.0]


def test_flows_are_read_from_state_and_reach_the_payload() -> None:
    d = days(3)
    state = {
        "equity": 2310.0,
        "cash": 2310.0,
        "curve": [[day.isoformat(), v] for day, v in zip(d, (1000.0, 1100.0, 2310.0), strict=True)],
        "flows": [
            {"amount": 1000.0, "decision_day": d[1].isoformat(), "applied_day": d[2].isoformat()}
        ],
    }
    found = rb.book_from_state("x", "s", "x", 1000.0, "active", state)
    assert found.flows == ((d[2], 1000.0),)
    payload = _payload([found], {rb.MARKET: series([0.0] * 5)})
    row, total = payload["deployments"][0], payload["book"]
    assert row["capital"] == 2000.0 and row["moved"] == 1000.0 and row["made"] == 310.0
    assert row["since_start"] == pytest.approx(0.21) and row["drawdown_now"] == 0.0
    # Rupees made over money put in, so the pair on screen agrees (T-4345):
    # 310 on 2,000 is 15.5%. The time-weighted 21% stays for the backtest check.
    assert row["made_pct"] == pytest.approx(0.155)
    assert total["since_start"] == 310.0 and total["since_start_pct"] == pytest.approx(0.155)
    assert total["since_start_twr"] == pytest.approx(0.21)
    assert total["today"] == pytest.approx(210.0) and total["today_pct"] == pytest.approx(0.1)
