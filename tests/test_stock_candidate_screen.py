from datetime import date

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import stock_candidate as screen


def _day(prices: list[float]) -> ip.Day:
    opens = list(prices)
    highs: list[float | None] = [price + 0.1 for price in prices]
    lows: list[float | None] = [price - 0.1 for price in prices]
    closes = prices.copy()
    volumes = [1000.0] * len(prices)
    return ip.Day(
        day=date(2024, 1, 2),
        open_=tuple(opens),
        high=tuple(highs),
        low=tuple(lows),
        close=tuple(closes),
        volume=tuple(volumes),
        last=len(prices) - 1,
    )


def test_correlation_returns_one_for_identical_returns() -> None:
    assert screen._correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_spread_z_uses_only_its_intraday_lookback() -> None:
    a = _day([100.0 + index for index in range(100)])
    b = _day([100.0] * 100)

    z = screen._spread_z(a, b, 99)

    assert z is not None and z > 0


def test_daily_stats_compound_returns_and_measure_drawdown() -> None:
    result = screen._daily_stats(
        [(date(2024, 1, 2), 0.1), (date(2024, 1, 3), -0.2), (date(2024, 1, 4), 0.1)]
    )

    assert result["total_return"] == -0.032
    assert result["max_drawdown"] == -0.2
