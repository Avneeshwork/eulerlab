"""A builder spec, turned into the one `Strategy` interface.

`BuiltStrategy` is an ordinary `Strategy`: handed a `MarketView`, it returns
target weights. It runs unchanged in Tier A, Tier B and paper, like every other
strategy here.

### Stops without memory

A stop needs the entry price, and the interface forbids a strategy from
remembering anything between calls (state carried between bars makes Tier A and
Tier B disagree for reasons no test can localise). So each instrument's
position is **re-derived from the view**: the rules are replayed bar by bar over
the history the view contains, entering when the entry rules hold and leaving
on the first exit rule, stop, target, trailing stop or holding limit. The
answer is a pure function of the view.

Replaying from the first bar on every call would be quadratic. The replay is
therefore cached per instrument and extended by the new bars only — and the
cache is thrown away whenever the history it was built on is not a prefix of
the history now in view. That happens when a corporate action becomes knowable:
`MarketView` back-adjusts every earlier price, the first close changes, and the
replay restarts from scratch on the adjusted series. A cached answer and a
fresh one are therefore the same answer, which `test_builder.py` checks.

### What "entry price" means here

The close of the bar the rules fired on. The engine fills afterwards, at its
own price and with costs, so a 5% stop here is 5% below the signal close, not
below the fill. Stops are also judged on closes: a day that traded through the
stop and recovered does not trigger it. Both are stated in the builder page.

### Signal, then slots

Every instrument is replayed independently. When more instruments are in a
position than there are slots, the ranking (or, without one, the earliest
entries) decides which are held. An instrument that signalled but was not given
a slot still has its stop tracked from its own signal, so it can take a slot
later only while its own trade is still alive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.builder.indicators import BY_NAME, Bar, Indicator
from eulerlab.builder.spec import (
    TURNOVER_PERIOD,
    VOLATILITY_PERIOD,
    BuilderSpec,
    Operand,
    Rule,
    RuleGroup,
)
from eulerlab.features.panel import PanelRow

VOLATILITY = Operand(name="volatility", params={"period": VOLATILITY_PERIOD})
TURNOVER = Operand(name="turnover_sma", params={"period": TURNOVER_PERIOD})


@dataclass
class Replay:
    """One instrument's rules, replayed up to the last bar fed."""

    series: dict[str, Indicator]
    values: dict[str, float | None] = field(default_factory=dict)
    previous: dict[str, float | None] = field(default_factory=dict)
    bars: int = 0
    first_day: date | None = None
    first_close: float = 0.0
    last_day: date | None = None
    last_close: float = 0.0
    holding: bool = False
    entry_day: date | None = None
    entry_price: float = 0.0
    entry_bar: int = 0
    entry_vol: float | None = None
    peak: float = 0.0
    last_exit: str = ""

    def matches(self, rows: list[PanelRow]) -> bool:
        """Whether `rows` extends the history this replay was built on."""
        if self.bars == 0 or len(rows) < self.bars:
            return False
        head, tail = rows[0], rows[self.bars - 1]
        return (
            head.day == self.first_day
            and head.close == self.first_close
            and tail.day == self.last_day
            and tail.close == self.last_close
        )


def _bar(row: PanelRow) -> Bar:
    o, h, low, c = row.ohlc()
    return Bar(open=o, high=h, low=low, close=c, volume=row.volume, turnover=row.turnover)


class BuiltStrategy(Strategy):
    hold_unchanged = True
    """A held position keeps its quantity until its weight changes. Weights
    here are fixed per slot from entry, so the engine trades on entries and
    exits only, not on daily drift."""

    rebalance_every = 1
    """Decided every day: a rule can fire on any close. The batch runner reads
    this instead of its default monthly cadence."""

    lookback = None
    """Full history. The replay cache depends on the view starting at the same
    first bar every day; a sliding window would invalidate it on every call."""

    def __init__(self, spec: BuilderSpec) -> None:
        self.spec = spec
        self.name = spec.id
        operands = [*spec.operands(), VOLATILITY, TURNOVER]
        self._operands: dict[str, Operand] = {o.key(): o for o in operands if o.kind == "indicator"}
        self._replays: dict[str, Replay] = {}

    def describe(self) -> str:
        return f"{self.spec.name} ({self.spec.id})"

    # --- the replay -------------------------------------------------------

    def _fresh(self) -> Replay:
        return Replay(
            series={key: BY_NAME[o.name].make(o.params) for key, o in self._operands.items()}
        )

    def _value(self, replay: Replay, operand: Operand, *, previous: bool) -> float | None:
        if operand.kind == "value":
            return operand.value
        source = replay.previous if previous else replay.values
        raw = source.get(operand.key())
        return None if raw is None else raw * operand.multiplier

    def _holds(self, replay: Replay, rule: Rule) -> bool:
        left = self._value(replay, rule.left, previous=False)
        right = self._value(replay, rule.right, previous=False)
        if left is None or right is None:
            return False
        if rule.op == "above":
            return left > right
        if rule.op == "below":
            return left < right
        before_left = self._value(replay, rule.left, previous=True)
        before_right = self._value(replay, rule.right, previous=True)
        if before_left is None or before_right is None:
            return False
        if rule.op == "crosses_above":
            return before_left <= before_right and left > right
        return before_left >= before_right and left < right

    def _group(self, replay: Replay, group: RuleGroup) -> bool:
        if not group.rules:
            return False
        results = (self._holds(replay, rule) for rule in group.rules)
        return all(results) if group.match == "all" else any(results)

    def _eligible(self, replay: Replay, close: float) -> bool:
        u = self.spec.universe
        if u.min_price and close < u.min_price:
            return False
        if u.max_price and close > u.max_price:
            return False
        if u.min_turnover:
            turnover = replay.values.get(TURNOVER.key())
            if turnover is None or turnover < u.min_turnover:
                return False
        return True

    def _exit_reason(self, replay: Replay, close: float) -> str:
        risk = self.spec.risk
        if risk.stop_loss_pct and close <= replay.entry_price * (1 - risk.stop_loss_pct / 100):
            return "stop_loss"
        if risk.take_profit_pct and close >= replay.entry_price * (1 + risk.take_profit_pct / 100):
            return "take_profit"
        if risk.trailing_stop_pct and close <= replay.peak * (1 - risk.trailing_stop_pct / 100):
            return "trailing_stop"
        if risk.max_hold_days and replay.bars - 1 - replay.entry_bar >= risk.max_hold_days:
            return "max_hold"
        if self._group(replay, self.spec.exit):
            return "exit_rule"
        return ""

    def _feed(self, replay: Replay, row: PanelRow) -> None:
        bar = _bar(row)
        replay.previous = replay.values
        replay.values = {key: series.update(bar) for key, series in replay.series.items()}
        if replay.bars == 0:
            replay.first_day, replay.first_close = row.day, row.close
        replay.bars += 1
        replay.last_day, replay.last_close = row.day, row.close

        close = bar.close
        if replay.holding:
            replay.peak = max(replay.peak, close)
            reason = self._exit_reason(replay, close)
            if reason:
                replay.holding = False
                replay.last_exit = reason
            return
        if self._eligible(replay, close) and self._group(replay, self.spec.entry):
            replay.holding = True
            replay.entry_day = row.day
            replay.entry_price = close
            replay.entry_bar = replay.bars - 1
            replay.peak = close
            replay.entry_vol = replay.values.get(VOLATILITY.key())

    def replay(self, symbol: str, rows: list[PanelRow]) -> Replay:
        """The instrument's state after the last row, reusing what is still valid."""
        cached = self._replays.get(symbol)
        if cached is None or not cached.matches(rows):
            cached = self._fresh()
            start = 0
        else:
            start = cached.bars
        for row in rows[start:]:
            self._feed(cached, row)
        self._replays[symbol] = cached
        return cached

    # --- the interface ----------------------------------------------------

    def target_weights(self, view: MarketView) -> dict[str, float]:
        holding: list[tuple[str, Replay]] = []
        for symbol in view.symbols():
            rows = list(view.history[symbol])
            if not rows:
                continue
            replay = self.replay(symbol, rows)
            if replay.holding:
                holding.append((symbol, replay))

        sizing = self.spec.sizing
        if len(holding) > sizing.max_positions:
            if sizing.ranking is not None:
                by = sizing.ranking.by
                highest = sizing.ranking.order == "highest"

                def rank(item: tuple[str, Replay]) -> tuple[int, float, str]:
                    value = self._value(item[1], by, previous=False)
                    if value is None:
                        return (1, 0.0, item[0])
                    return (0, -value if highest else value, item[0])

                holding.sort(key=rank)
            else:
                holding.sort(key=lambda item: (item[1].entry_day or date.min, item[0]))
            holding = holding[: sizing.max_positions]

        if not holding:
            return {}
        slot = 1.0 / sizing.max_positions
        if sizing.method == "equal":
            return {symbol: slot for symbol, _ in holding}

        target = sizing.vol_target_pct
        return {
            symbol: slot * min(1.0, target / replay.entry_vol)
            if replay.entry_vol and replay.entry_vol > 0
            else slot
            for symbol, replay in holding
        }


def compile_spec(spec: BuilderSpec) -> BuiltStrategy:
    return BuiltStrategy(spec)
