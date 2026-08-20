"""`make research` — the loop, and the weekly report it owes you.

The build plan's verification for this phase is *"weekly: hypotheses tested,
passed, killed, and why"*. That sentence is the whole specification, and the
important word is **why**: a loop that reports throughput teaches you nothing,
because the throughput of a research process is not the thing that matters.

The stages run in this order for a reason. Each is cheaper than the next, so
the expensive ones only see candidates the cheap ones could not dismiss:

    card  ->  critic  ->  codegen  ->  [operator registers]  ->  battery  ->  gate
             free       free                                    ~40 min    seconds

The loop **stops at registration**. It reads cards, criticises them, and can
build them, but it does not register, validate or promote anything. That is
not caution for its own sake — an agent that could originate a hypothesis and
then decide it was worth testing would be selecting on its own output, and the
trial counter would be measuring a search it no longer controlled.

What it reports is deliberately unflattering: how many hypotheses exist, how
many were killed and by which rule, and what the accumulated searching has
done to the bar every future candidate must clear.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from eulerlab.research import codegen, critic
from eulerlab.research.budget import price_search
from eulerlab.research.scout import available_years
from eulerlab.validation.ledger import read as read_ledger

HYPOTHESES = Path("hypotheses")


@dataclass
class CardStatus:
    id: str
    title: str
    status: str
    configurations: int
    blockers: int
    concerns: int
    buildable: bool
    gate_verdict: str


def survey(directory: Path = HYPOTHESES, *, years: float) -> list[CardStatus]:
    """Every card, its critic review, and whatever the gate has said."""
    verdicts: dict[str, str] = {}
    for entry in read_ledger():
        if entry.kind == "gate":
            verdicts[entry.subject] = str(entry.outcome.get("verdict", "?"))

    out: list[CardStatus] = []
    for path in sorted(directory.glob("H-*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        review = critic.review(path, available_years=years)
        try:
            codegen.build_from_card(path)
            buildable = True
        except codegen.UnknownPrimitive:
            buildable = False
        out.append(
            CardStatus(
                id=path.stem,
                title=str(spec.get("title", "")),
                status=str(spec.get("status", "draft")),
                configurations=len(spec.get("configurations") or []),
                blockers=len(review.blockers),
                concerns=sum(1 for o in review.objections if o.severity == critic.Severity.CONCERN),
                buildable=buildable,
                gate_verdict=verdicts.get(path.stem, "—"),
            )
        )
    return out


def render(cards: Sequence[CardStatus], *, years: float) -> str:
    lines = ["", "=" * 74, "RESEARCH LOOP — hypotheses, and why", "=" * 74, ""]
    lines.append(
        f"{'id':<9}{'status':<12}{'cfgs':>5}{'blk':>5}{'conc':>6}{'built':>7}  {'gate':<9} title"
    )
    for c in cards:
        lines.append(
            f"{c.id:<9}{c.status:<12}{c.configurations:>5}{c.blockers:>5}{c.concerns:>6}"
            f"{('yes' if c.buildable else 'NO'):>7}  {c.gate_verdict:<9} {c.title[:28]}"
        )

    killed = [c for c in cards if c.gate_verdict == "KILL"]
    promoted = [c for c in cards if c.gate_verdict == "PROMOTE"]
    untested = [c for c in cards if c.gate_verdict == "—"]

    lines.append("")
    lines.append(f"  hypotheses    : {len(cards)}")
    lines.append(f"  killed        : {len(killed)}  {', '.join(c.id for c in killed) or '-'}")
    lines.append(f"  promoted      : {len(promoted)}  {', '.join(c.id for c in promoted) or '-'}")
    lines.append(f"  never tested  : {len(untested)}  {', '.join(c.id for c in untested) or '-'}")

    cost = price_search(0, available_years=years)
    lines.append("")
    lines.append(f"  trials logged : {cost.trials_already}")
    lines.append(f"  the bar now   : Sharpe {cost.bar_now:.2f} from noise alone")
    lines.append(
        "\n  Reading: the bar is what accumulated searching has cost, and it applies\n"
        "  to every future candidate. A loop that generates more hypotheses raises\n"
        "  it further. Throughput is not the goal — each hypothesis being\n"
        "  pre-registered and honestly counted is (ADR-026)."
    )
    if promoted:
        lines.append(
            "\n  A hypothesis has been PROMOTED. That authorises one holdout read by\n"
            "  the operator. It does not authorise capital."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research", description=__doc__)
    parser.add_argument("--hypotheses", type=Path, default=HYPOTHESES)
    parser.add_argument("--critic", default="", metavar="ID", help="full review of one card")
    parser.add_argument("--library", action="store_true", help="what a card may reference")
    args = parser.parse_args(argv)

    if args.library:
        print(codegen.describe_library())
        return 0

    years = available_years()

    if args.critic:
        path = args.hypotheses / f"{args.critic}.yaml"
        if not path.exists():
            print(f"no card at {path}")
            return 2
        print(critic.review(path, available_years=years).render())
        return 0

    cards = survey(args.hypotheses, years=years)
    if not cards:
        print("no hypothesis cards. Draft one with `make scout`.")
        return 0
    print(render(cards, years=years))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
