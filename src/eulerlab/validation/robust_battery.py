"""A fixed robustness battery for a screen survivor, run before the gate (#158, ADR-211).

The screen already asks for both halves positive, 2x costs, the five best
stocks removed, 60% of years positive and no 1% of days holding half the
profit (ADR-150). It does not ask whether the result is a lucky point, a
lucky set of stocks, a leak, or one market state. This module asks, in code,
the same four questions of every survivor:

    neighbours   each number in the rule (a threshold, a window, the hold)
                 moved 20% either way, one at a time: in most neighbours the
                 net Sharpe must keep half the rule's own
    halves       the rule on 20 random halves of the stock list (fixed by its
                 fingerprint): the median net Sharpe must be above zero
    placebos     the rule's entries moved 5 to 60 sessions later, 20 times:
                 they must make less than half the rule's own Sharpe, or the
                 edge is the market's drift or a leak, not the timing
    regimes      the rule's daily returns split four ways (Nifty above or
                 below its 200-session mean, India VIX terciles, before or
                 after 2020, before or after the September 2021 peak-margin
                 rules): no split may have one state hold more than 80% of
                 the profit

Every run is on data cut at `discovery_end` (ADR-210) and is one `robust` row
in the experiment store, so the search it adds is counted. It spends no ledger
trial: it can only stop a rule before the gate, never pass one.

An honest limit: a cross-section rule's top N is chosen before a half universe
is applied, so a half holds fewer names rather than the next best ones.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import statistics
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.features.formula import Node, text_of
from eulerlab.intraday import rule_engine
from eulerlab.research import experiments, lang

STEP = 0.2
"""How far each number moves, either way."""
KEEP = 0.5
"""Share of the rule's own net Sharpe a neighbour must keep, and that a placebo must stay under."""
HALVES = 20
PLACEBOS = 20
LAGS = (5, 60)
"""Sessions a placebo's entries are moved later, drawn uniformly."""
REGIME_SHARE = 0.8
MIN_DAYS = 60
"""A regime with fewer sessions than this is not read."""
MAX_NEIGHBOURS = 16
# ASSUMPTION: A-159 — STEP, KEEP, HALVES, PLACEBOS, LAGS and REGIME_SHARE are the
# issue's numbers (#158), chosen by hand and not fitted.
PEAK_MARGIN = date(2021, 9, 1)
# ASSUMPTION: A-160 — SEBI's peak-margin rule reached its full 100% on 2021-09-01
# (phased in from 2020-12-01); used here only as a date to split returns at.
COVID = date(2020, 1, 1)


@dataclass(frozen=True)
class Test:
    name: str
    passed: bool | None
    """None when the test could not be read (too few trades, no index data)."""
    detail: str
    figures: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Battery:
    fingerprint: str
    sharpe: float | None
    tests: tuple[Test, ...]

    @property
    def passed(self) -> bool:
        """No test failed. A test that could not be read does not fail the rule."""
        return all(t.passed is not False for t in self.tests)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "sharpe": self.sharpe,
            "passed": self.passed,
            "tests": [asdict(t) for t in self.tests],
        }


# --- neighbours --------------------------------------------------------------------------


def _moves(node: Node) -> Iterator[tuple[str, Node]]:
    """Every one-number change of `node`: (what changed, the new tree)."""
    if node.op == "const" and node.value is not None and abs(node.value) not in (0.0, 1.0):
        for f in (1 - STEP, 1 + STEP):
            v = round(node.value * f, 6)
            yield f"{node.value:g} -> {v:g}", node.model_copy(update={"value": v})
    for i, p in enumerate(node.params):
        lower = max(1, min(p - 1, round(p * (1 - STEP))))
        upper = max(p + 1, round(p * (1 + STEP)))
        for q in sorted({lower, upper} - {p}):
            params = (*node.params[:i], q, *node.params[i + 1 :])
            yield f"{node.op} {p} -> {q}", node.model_copy(update={"params": params})
    for i, arg in enumerate(node.args):
        for what, moved in _moves(arg):
            args = (*node.args[:i], moved, *node.args[i + 1 :])
            yield what, node.model_copy(update={"args": args})


def neighbours(spec: lang.Spec) -> list[tuple[str, lang.Spec]]:
    """The rule with each number moved `STEP` either way; a move that is not a valid rule is dropped."""
    body = spec.model_dump(mode="json")
    out: list[tuple[str, lang.Spec]] = []
    seen = {spec.fingerprint()}

    def add(what: str, change: Mapping[str, Any]) -> None:
        try:
            made = lang.Spec.model_validate({**body, **change})
        except ValueError:  # a lag moved to look ahead, a hold out of range
            return
        if made.fingerprint() not in seen:
            seen.add(made.fingerprint())
            out.append((what, made))

    for key, tree in spec.trees.items():
        if tree.op == "const":
            continue  # `when: 1` is "always", not a number to move
        for what, moved in _moves(tree):
            add(f"{key}: {what}", {key: text_of(moved)})
    if spec.kind == "swing":
        for h in sorted({max(2, round(spec.hold * (1 - STEP))), round(spec.hold * (1 + STEP))}):
            add(f"hold {spec.hold} -> {h}", {"hold": min(h, 60)})
    return out[:MAX_NEIGHBOURS]


# --- the battery -------------------------------------------------------------------------


def _sharpe(screen: Mapping[str, Any]) -> float | None:
    value = (screen.get("net") or {}).get("sharpe")
    return float(value) if value is not None else None


def _rng(fingerprint: str, what: str) -> random.Random:
    seed = int(hashlib.sha256(f"{fingerprint}:{what}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)  # seeded: the same rule always gets the same draws


def _median(values: Sequence[float | None]) -> float | None:
    found = [v for v in values if v is not None]
    return statistics.median(found) if found else None


def _neighbour_test(base: float, sharpes: Mapping[str, float | None]) -> Test:
    kept = [w for w, s in sharpes.items() if s is not None and s >= KEEP * base]
    if not sharpes:
        return Test("neighbours", None, "the rule has no number to move")
    passed = len(kept) > len(sharpes) / 2
    detail = f"{len(kept)} of {len(sharpes)} neighbours keep half the Sharpe {base:.2f}"
    return Test("neighbours", passed, detail, {"sharpes": dict(sharpes)})


def _shift(
    data: rule_engine.Data, events: Sequence[rule_engine.Event], lag: int
) -> list[rule_engine.Event]:
    out: list[rule_engine.Event] = []
    for day, symbol, side, rank in events:
        i = data.index.get(day)
        if i is None or i + lag >= len(data.sessions):
            continue
        later = data.sessions[i + lag]
        if data.tradable(symbol, later):
            out.append((later, symbol, side, rank))
    return out


def regime_labels(
    sessions: Sequence[date], nifty: Mapping[date, float], vix: Mapping[date, float]
) -> dict[str, dict[date, str]]:
    """Each split's state on each session, from the session before it (nothing read ahead)."""
    out: dict[str, dict[date, str]] = {
        "before or after 2020": {d: "before" if d < COVID else "after" for d in sessions},
        "peak margin rules": {d: "before" if d < PEAK_MARGIN else "after" for d in sessions},
    }
    days = sorted(nifty)
    trend: dict[date, str] = {}
    for k in range(200, len(days)):
        mean = statistics.fmean(nifty[d] for d in days[k - 200 : k])
        trend[days[k]] = "above" if nifty[days[k - 1]] > mean else "below"
    out["Nifty vs 200-session mean"] = {d: trend[d] for d in sessions if d in trend}
    known = sorted(vix)
    if len(known) >= 3:
        levels = sorted(vix.values())
        low, high = levels[len(levels) // 3], levels[2 * len(levels) // 3]
        prior = {b: vix[a] for a, b in pairwise(known)}
        out["India VIX tercile"] = {
            d: "low" if prior[d] < low else "high" if prior[d] >= high else "middle"
            for d in sessions
            if d in prior
        }
    return out


def _regime_test(daily: Mapping[date, float], labels: Mapping[str, Mapping[date, str]]) -> Test:
    table: dict[str, dict[str, float]] = {}
    worst: tuple[float, str] | None = None
    for split, states in labels.items():
        sums: dict[str, float] = defaultdict(float)
        days: dict[str, int] = defaultdict(int)
        for d, v in daily.items():
            if d in states:
                sums[states[d]] += v
                days[states[d]] += 1
        read = {s: round(v, 6) for s, v in sums.items() if days[s] >= MIN_DAYS}
        profit = sum(v for v in read.values() if v > 0)
        if len(read) < 2 or profit <= 0:
            continue
        table[split] = read
        share = max(read.values()) / profit
        if worst is None or share > worst[0]:
            worst = (share, split)
    if worst is None:
        return Test("regimes", None, "no split has two states with enough sessions")
    share, split = worst
    detail = f"largest share of profit in one state: {share:.0%} ({split})"
    return Test("regimes", share <= REGIME_SHARE, detail, {"by_split": table})


def run(
    spec: lang.Spec,
    engine: rule_engine.Engine,
    *,
    labels: Mapping[str, Mapping[date, str]] | None = None,
    hypothesis: str = "",
    asked_by: str = "robust_battery",
    now: datetime | None = None,
    record: bool = True,
) -> Battery:
    """The four tests on `engine`'s data, each run recorded as a `robust` row."""
    fp = spec.fingerprint()
    data = engine.data
    end = min(data.end, data.sessions[-1])

    def screen(
        events: Sequence[rule_engine.Event] | None, rule: lang.Spec, test: str
    ) -> float | None:
        found = engine.screen(rule, events)
        engine.returns.pop(rule.fingerprint(), None)
        sharpe = _sharpe(found)
        if record:
            experiments.record(
                purpose="robust",
                fingerprint=rule.fingerprint(),
                hypothesis=hypothesis,
                family=f"robust:{test}",
                first=rule.first,
                end=end,
                metrics={"test": test, "of": fp, "count": found.get("count"), "net_sharpe": sharpe},
                asked_by=asked_by,
                now=now,
                spec=rule.model_dump(mode="json") if rule is not spec else None,
            )
        return sharpe

    own = engine.screen(spec)
    daily = engine.returns.pop(fp, {})
    base = _sharpe(own)
    if base is None or base <= 0:
        test = Test("screen", False, "the rule's own net Sharpe is not above zero")
        return Battery(fp, base, (test,))
    tests: list[Test] = []

    moved = {what: screen(None, n, "neighbour") for what, n in neighbours(spec)}
    tests.append(_neighbour_test(base, moved))

    events = engine.events(spec)
    symbols = sorted(data.panel)
    rng = _rng(fp, "halves")
    halves = []
    for _ in range(HALVES):
        keep = set(rng.sample(symbols, len(symbols) // 2))
        halves.append(screen([e for e in events if e[1] in keep], spec, "half"))
    median = _median(halves)
    tests.append(
        Test(
            "halves",
            None if median is None else median > 0,
            f"median net Sharpe on {HALVES} random half universes: "
            + ("none" if median is None else f"{median:.2f}"),
            {"sharpes": halves},
        )
    )

    rng = _rng(fp, "placebos")
    lags = [rng.randint(*LAGS) for _ in range(PLACEBOS)]
    placebos = [screen(_shift(data, events, lag), spec, "placebo") for lag in lags]
    found = [p for p in placebos if p is not None]
    mean = statistics.fmean(found) if found else None
    tests.append(
        Test(
            "placebos",
            None if mean is None else mean < KEEP * base,
            f"mean net Sharpe with entries moved {LAGS[0]}-{LAGS[1]} sessions later: "
            + ("none" if mean is None else f"{mean:.2f} against the rule's {base:.2f}"),
            {"lags": lags, "sharpes": placebos},
        )
    )

    tests.append(_regime_test(daily, labels if labels is not None else default_labels(data)))
    return Battery(fp, base, tuple(tests))


def default_labels(data: rule_engine.Data) -> dict[str, dict[date, str]]:
    """The regime splits from NSE's official Nifty 50 and India VIX closes."""
    from eulerlab.intraday import mft_screen as mft

    try:
        nifty, vix = mft._official_closes("Nifty 50"), mft._official_closes("India VIX")
    except OSError:
        nifty, vix = {}, {}
    return regime_labels(data.sessions, nifty, vix)


def render(rows: Sequence[tuple[str, Battery]]) -> str:
    """The battery as one markdown table, a row per card."""
    lines = [
        "| Card | Net Sharpe | Neighbours | Halves | Placebos | Regimes | Passed |",
        "|---|---|---|---|---|---|---|",
    ]
    said = {True: "pass", False: "FAIL", None: "n/a"}
    for card, b in rows:
        by = {t.name: t for t in b.tests}
        cells = [
            f"{said[by[n].passed]}: {by[n].detail}" if n in by else "not run"
            for n in ("neighbours", "halves", "placebos", "regimes")
        ]
        sharpe = "none" if b.sharpe is None else f"{b.sharpe:.2f}"
        lines.append(f"| {card} | {sharpe} | {' | '.join(cells)} | {said[b.passed]} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make robust-battery", description=__doc__)
    parser.add_argument("cards", nargs="+", help="H-NNNN cards with an engine rule")
    parser.add_argument("--out", type=Path, default=None, help="write the table here too")
    args = parser.parse_args(argv)
    from eulerlab import constitution
    from eulerlab.research import agent_tools

    engine = agent_tools.discovery_engine(constitution.load().periods.discovery_end)
    labels = default_labels(engine.data)
    rows: list[tuple[str, Battery]] = []
    for card in args.cards:
        rule = rule_engine.card_spec(card) or rule_engine.reference_specs().get(card)
        if rule is None:
            print(f"{card}: no engine rule on the card; skipped")
            continue
        spec = lang.from_rule(rule) if isinstance(rule, rule_engine.RuleSpec) else rule
        assert isinstance(spec, lang.Spec)
        rows.append((card, run(spec, engine, labels=labels, hypothesis=card)))
    text = render(rows)
    print(text)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
