"""Every strategy's info panel must carry real content.

The console presents these as "the steps as coded". Twelve daily strategies
shipped with no citation, no link and no steps at all, showing only a shared
sentence about the rebalance mechanics that was identical for all of them
except one number — so the panel for `momentum_12_1` never said what momentum
is. These pin the parts that were empty.
"""

from __future__ import annotations

import pytest

from eulerlab.strategies import PAPERS, RESEARCH, _published, paper_url


@pytest.mark.parametrize("key", sorted(_published()))
def test_every_daily_strategy_states_its_steps(key: str) -> None:
    steps = _published()[key].logic
    assert steps, f"{key} shows no implementation steps"
    assert all(step.strip() for step in steps), f"{key} has an empty step"
    assert len(steps) >= 3, f"{key} has only {len(steps)} steps — too thin to be the procedure"


@pytest.mark.parametrize("key", sorted(_published()))
def test_a_cited_strategy_links_somewhere_readable(key: str) -> None:
    """A citation with no link is a name to go and search for."""
    declaration = _published()[key]
    if not declaration.source:
        # Uncited is allowed, but it must say so in the steps rather than
        # leaving the reader to assume a paper exists.
        assert any("not from a paper" in s.lower() for s in declaration.logic), (
            f"{key} cites nothing and never says so"
        )
        return
    assert declaration.paper_url, f"{key} cites {declaration.source!r} with no link"
    assert declaration.published, f"{key} cites a paper without saying what it reported"
    assert declaration.tested_on, f"{key} cites a paper without saying what it tested"


@pytest.mark.parametrize("citation", sorted(RESEARCH))
def test_every_citation_resolves_in_the_paper_registry(citation: str) -> None:
    """A citation the registry cannot match renders as a missing link.

    This is the failure that shipped once already: `par_deviation` cited
    Cohen (2023) with a `[paper] ` tag in front, and the prefix match missed
    it, so a strategy with a perfectly good paper showed none.
    """
    source = RESEARCH[citation][0]
    if not source:
        return
    assert paper_url(source), f"{citation} cites {source!r}, which no PAPERS entry matches"


def test_paper_registry_entries_are_well_formed() -> None:
    for prefix, (url, pdf) in PAPERS.items():
        assert url.startswith("https://"), f"{prefix} has no usable url"
        assert not pdf or pdf.endswith(".pdf"), f"{prefix} points at a non-pdf"


def test_the_steps_do_not_restate_the_engine_boilerplate() -> None:
    """Steps must say what *this* strategy computes.

    The panel used to show one sentence about scoring and rebalancing that was
    the same for all twelve. If every strategy's first step is identical again,
    the panel has drifted back to describing the engine.
    """
    firsts = {key: d.logic[0] for key, d in _published().items() if d.logic}
    assert len(set(firsts.values())) == len(firsts), (
        "two strategies open with the same step — that is engine boilerplate, "
        f"not their own procedure: {sorted(firsts)}"
    )
