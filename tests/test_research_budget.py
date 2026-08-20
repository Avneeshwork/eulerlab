"""What searching costs. The bar rises for everything, every time you look."""

from __future__ import annotations

from eulerlab.research.budget import SearchCost


def _cost(already: int, proposed: int, years: float = 11.4) -> SearchCost:
    return SearchCost(trials_already=already, trials_proposed=proposed, available_years=years)


def test_proposing_more_hypotheses_raises_the_bar() -> None:
    """Not a penalty bolted on - it is what the statistic means. The best of
    twenty coin flips looks good precisely because twenty were tried."""
    assert _cost(17, 20).bar_after > _cost(17, 20).bar_now


def test_a_bigger_search_raises_it_further() -> None:
    assert _cost(17, 100).bar_after > _cost(17, 20).bar_after


def test_the_bar_is_already_non_trivial_after_real_use() -> None:
    """17 trials have actually been logged, and that alone requires beating a
    Sharpe well above zero."""
    assert _cost(17, 0).bar_now > 1.5


def test_a_search_that_outruns_the_available_history_is_unaffordable() -> None:
    """Afterwards no strategy this data can support would clear the bar the
    search itself created."""
    assert not _cost(17, 100_000, years=11.4).affordable


def test_a_modest_search_remains_affordable() -> None:
    assert _cost(17, 20, years=11.4).affordable


def test_an_unaffordable_search_says_so_in_the_report() -> None:
    assert "NOT AFFORDABLE" in _cost(17, 100_000, years=11.4).render()


def test_the_report_states_both_bars() -> None:
    text = _cost(17, 20).render()
    assert "today" in text
    assert "after this search" in text


def test_more_history_makes_a_search_affordable_again() -> None:
    """The only honest way to buy back the cost of searching."""
    big = _cost(17, 5000, years=5.0)
    same_with_more_data = _cost(17, 5000, years=500.0)
    assert not big.affordable
    assert same_with_more_data.affordable
