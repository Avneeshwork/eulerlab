"""The knowledge agent's summary counts read as English (T-4345)."""

from eulerlab.agents.workers.knowledge import _plural


def test_plurals() -> None:
    assert _plural("hypothesis", 19) == "hypotheses"
    assert _plural("paper", 125) == "papers"
    assert _plural("hypothesis", 1) == "hypothesis"
    assert _plural("index", 2) == "indexes"
