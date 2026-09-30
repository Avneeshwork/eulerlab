"""Citation lookups, and the two ways they silently returned nothing.

Both failures had the same symptom — no paper link, no error — and paper links
are provenance, so an absent one reads as "this signal has no published source"
rather than as "the lookup missed".
"""

from __future__ import annotations

from eulerlab.strategies import REGISTRY, paper_pdf, paper_url


def test_a_tagged_citation_still_resolves() -> None:
    """`par_deviation` cites `[paper] Cohen, G. (2023)...` and showed no link.

    The tag classifies how much weight a source carries and sits in front of
    the citation, so a plain prefix match against `Cohen` missed it entirely.
    """
    assert paper_url("[paper] Cohen, G. (2023). Intraday trading of cryptocurrencies")
    assert paper_url("Cohen (2023)")


def test_the_declared_source_is_what_resolves_not_the_id() -> None:
    """The sweep endpoint shipped passing a strategy id, so every link was empty."""
    declaration = REGISTRY["orb_breakout"]
    assert paper_url(declaration.source) == "https://arxiv.org/abs/2605.04004"
    assert paper_url("orb_breakout") == ""


def test_practitioner_sources_resolve_to_nothing_on_purpose() -> None:
    """Not every signal has a paper, and inventing one would be worse."""
    assert paper_url("[practitioner] Widely documented practitioner rule") == ""
    assert paper_url("[literature] Intraday time-series momentum") == ""


def test_every_registered_paper_citation_resolves() -> None:
    """The regression guard: a signal whose source *is* a known paper gets its link.

    Matched on what the citation opens with, after any tag, rather than on the
    name appearing anywhere in it. `volume_climax` is a practitioner rule whose
    citation mentions Mesfin in passing — "Mesfin (2026) tested the weaker
    volume variant" — and it correctly resolves to nothing. A looser test flags
    that as a missing link and would push toward attributing a practitioner
    construction to a paper that did not publish it.
    """
    from eulerlab.strategies import _bare_citation

    known = ("Mesfin", "Zarattini", "Cohen")
    for declaration in REGISTRY.values():
        source = declaration.source or ""
        if not _bare_citation(source).startswith(known):
            continue
        assert paper_url(source), f"{declaration.id}: {source!r} resolved to nothing"


def test_a_passing_mention_is_not_an_attribution() -> None:
    """Stated directly, since the sweep above depends on it."""
    citation = REGISTRY["volume_climax"].source or ""
    assert "Mesfin" in citation
    assert paper_url(citation) == ""


def test_pdf_is_only_claimed_when_the_file_is_present() -> None:
    """A link that 404s reads as broken provenance, not as an unfetched file."""
    from pathlib import Path

    for declaration in REGISTRY.values():
        pdf = paper_pdf(declaration.source or "")
        if pdf:
            assert Path(pdf).exists()
