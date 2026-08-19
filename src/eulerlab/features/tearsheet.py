"""`make ic FEATURE=...` — evaluate a feature and print an honest tear sheet.

Honest means the sheet is built so a weak result cannot be mistaken for a
strong one. It leads with the t-statistic rather than the mean IC, because a
mean of 0.03 is interesting over 500 periods and meaningless over 8; it prints
the per-year breakdown, because a feature that worked in one year and nowhere
else has a flattering average; and it states the overlap caveat rather than
letting the t-statistic imply more independence than the sampling provides.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from eulerlab.features import independence, trials
from eulerlab.features.ic import ICResult, evaluate
from eulerlab.features.library import BY_NAME, LIBRARY
from eulerlab.features.panel import read_panel, trading_days


def render(result: ICResult, *, step: int) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"\nfeature       : {result.feature}")
    feature = BY_NAME.get(result.feature)
    if feature:
        add(f"                {feature.description}")
    add(f"horizon       : {result.horizon_days} trading days")
    add(f"periods       : {result.n:,} cross-sections, every {step}th trading day")
    if result.periods:
        add(f"names/period  : {sum(p.n for p in result.periods) // result.n:,} median")
    add("")
    add(f"mean IC       : {result.mean_ic:+.4f}")
    add(f"IC std dev    : {result.std_ic:.4f}")
    add(f"t-statistic   : {result.t_stat:+.2f}   <- the number that matters")
    add(f"hit rate      : {result.hit_rate:.1%} of periods positive")
    if result.skipped_thin:
        add(f"thin periods  : {result.skipped_thin:,} skipped for too few names")

    add("\nIC by year (a signal that worked in one year only is not a signal):")
    for year, (mean, n) in result.by_year().items():
        bar = "#" * min(40, int(abs(mean) * 800))
        add(f"  {year}  {mean:+.4f}  n={n:>4}  {bar}")

    add("")
    verdict = _verdict(result)
    add(verdict)
    add(
        "\nCaveat: cross-sections overlap at this horizon, so the t-statistic is\n"
        "optimistic. It is a screen, not a test. Nothing here is evidence of\n"
        "tradeable edge until it survives costs and the Sprint 13 battery."
    )
    return "\n".join(lines)


def _verdict(result: ICResult) -> str:
    """State the reading plainly, including when it is 'nothing here'."""
    if result.n < 20:
        return "VERDICT: too few periods to say anything. Extend the panel."
    t = abs(result.t_stat)
    if t < 2.0:
        return (
            "VERDICT: indistinguishable from noise. This is the expected outcome for most features."
        )
    if t < 3.0:
        return "VERDICT: weakly suggestive. Below the t>3 bar the promotion gate will apply."
    return (
        "VERDICT: statistically interesting, and that is all. Overlapping periods\n"
        "         inflate this, and it has not met a cost model or an overfitting test."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ic", description=__doc__)
    parser.add_argument("--feature", default="", help="feature name; omit to list")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--all", action="store_true", help="evaluate every feature")
    args = parser.parse_args(argv)

    if not args.feature and not args.all:
        print("features:")
        for feature in LIBRARY:
            print(f"  {feature.name:<22} {feature.description}")
        print(f"\ntrials logged so far: {trials.count():,}")
        return 0

    rows = read_panel()
    if not rows:
        print("no panel. Run `make build-panel` first.")
        return 2
    days = trading_days(rows)
    print(f"panel: {len(rows):,} rows, {len(days):,} days, {days[0]} to {days[-1]}")

    chosen = LIBRARY if args.all else (BY_NAME[args.feature],)
    collected: list[ICResult] = []
    for feature in chosen:
        result = evaluate(rows, feature, horizon=args.horizon, step=args.step)
        collected.append(result)
        print(render(result, step=args.step))
        total = trials.append(
            trials.Trial(
                logged_at=trials.now_iso(),
                feature=feature.name,
                horizon_days=args.horizon,
                step_days=args.step,
                panel_start=days[0].isoformat(),
                panel_end=days[-1].isoformat(),
                n_periods=result.n,
                mean_ic=round(result.mean_ic, 6),
                t_stat=round(result.t_stat, 4),
            )
        )
        print(f"\ntrial logged; {total:,} configurations evaluated in total")

    if len(collected) > 1:
        # Printed automatically, because the first full sweep produced ten
        # features with zero noise results and that needed explaining rather
        # than celebrating.
        print(independence.render(collected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
