"""`make scout` — cost a search, and draft hypothesis cards from real sources.

Three deliberate limits, each one a place where an automated research loop
usually goes wrong.

**It prices the search before running it.** Generating hypotheses raises the
statistical bar for every candidate, including ones already evaluated, so the
first thing printed is what this search would cost. If the cost is
unaffordable it refuses outright rather than producing cards nobody can ever
justify.

**It does not invent sources.** A card without a real URL and fetch date is
rejected by `card.validate`. `CLAUDE.md` forbids fabricating a source, and a
fabricated citation inside a pre-registration would corrupt the one artefact
the gate depends on. This command therefore takes sources as input rather than
conjuring them — the web search that finds candidate papers is a human-directed
step, and what is automated is the discipline applied afterwards.

**It does not register anything.** Cards are written as `status: draft`. The
gate reads `hypotheses/*.yaml`, so a draft is inert until someone changes that
field deliberately.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date

from eulerlab.features.panel import read_panel, trading_days
from eulerlab.research import budget, card

HOLDOUT_START = date(2025, 1, 1)
"""Matches H-0001 so every hypothesis is judged on the same withheld period.
A per-card holdout would let a weak candidate pick a kinder one."""


def available_years() -> float:
    rows = read_panel()
    if not rows:
        return 0.0
    return len(trading_days(rows)) / 252


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scout", description=__doc__)
    parser.add_argument(
        "--propose",
        type=int,
        default=1,
        help="how many hypotheses this search would produce",
    )
    parser.add_argument("--draft", default="", metavar="TITLE", help="draft a card with this title")
    parser.add_argument("--source", default="", help="URL the claim comes from")
    parser.add_argument("--claim", default="")
    args = parser.parse_args(argv)

    years = available_years()
    cost = budget.price_search(args.propose, available_years=years)
    print(cost.render())

    if not cost.affordable:
        print("\nrefusing to draft. Reduce the number of hypotheses, or extend the history.")
        return 1

    if not args.draft:
        print(
            "\nNo card drafted. Pass --draft TITLE --source URL --claim '...' to write one.\n"
            "Cards are written as status: draft and are inert until registered."
        )
        return 0

    if not args.source:
        print("\nrefusing: --source is required. CLAUDE.md forbids inventing a source.")
        return 1

    draft = card.Card(
        id=card.next_id(),
        title=args.draft,
        claim=args.claim,
        configurations=[],
        red_flags=[],
        holdout_starts=HOLDOUT_START,
        source_url=args.source,
        source_fetched=date.today().isoformat(),  # noqa: DTZ011 - a fetch date, not a knowledge time
    )
    checked = card.validate(draft)
    print(f"\ndraft {draft.id}: {'valid' if checked.ok else 'INCOMPLETE'}")
    for problem in checked.problems:
        print(f"  - {problem}")
    if not checked.ok:
        print(
            "\nA card is only written once it is a usable pre-registration. Fill in\n"
            "the configurations and red flags and re-run — the red flags are the\n"
            "objections you would otherwise rationalise away once the numbers arrive."
        )
        return 1

    path = card.write(draft)
    print(f"written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
