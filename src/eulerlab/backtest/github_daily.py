"""Five daily strategies from public GitHub repositories, run on NSE as written.

Research 113. The earlier GitHub rounds (research 088-111) ported intraday
rules to five NSE stocks; every one lost to intraday costs, which take more
than the 2-8 bp a trade those rules earn. These five trade on daily bars,
hold for days to months and pay delivery costs a few times a month at most.

Each follows its repository's rule as stated in the code (fetched 2026-10-18,
recorded in research 113), adapted only where NSE or this engine requires:

- **The engine fills at the next session's close.** Repositories that trade at
  the signal's own close are one day later here; said per strategy.
- **Stock rules run on the point-in-time 250 most-traded stocks**
  (`india_papers.liquid_universe`), the house convention that keeps today's
  winners out of the past.
- **Position rules (enter on one condition, leave on another)** are replayed
  over the last `STATE_WINDOW` sessions at every decision, so the strategy
  needs no memory between calls and a backtest and a paper run agree. A
  position older than the window is treated as opened inside it; the
  approximation is stated in research 113.
- **Long only.** Every rule here is long only in its repository.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence

from eulerlab.backtest.india_papers import (
    INDEX_ETF,
    MONTH,
    YEAR,
    PaperStrategy,
    liquid_universe,
)
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features import indicators
from eulerlab.features.panel import PanelRow

STATE_WINDOW = 250
"""Sessions replayed to know whether a position rule is in a trade today."""

Signal = Callable[[int], bool]


def in_trade(n: int, enter: Signal, leave: Signal, *, start: int) -> int | None:
    """The bar a still-open trade was entered on, or None when flat at bar n-1.

    Walks bars `start..n-1`: flat until `enter(i)`, then in until `leave(i)`.
    A bar that enters cannot also leave.
    """
    entered: int | None = None
    for i in range(start, n):
        if entered is None:
            if enter(i):
                entered = i
        elif leave(i):
            entered = None
    return entered


def prior_extreme(values: Sequence[float], window: int, *, highest: bool) -> list[float | None]:
    """At each i, the max (or min) of `values[i-window:i]`, the bars before i.

    Linear time with a monotonic deque: slicing a window at every bar made the
    Turtle rule cost ~5,000 operations per stock per day.
    """
    out: list[float | None] = [None] * len(values)
    kept: deque[int] = deque()
    for i, value in enumerate(values):
        if i >= window:
            out[i] = values[kept[0]]
        while kept and (values[kept[-1]] <= value if highest else values[kept[-1]] >= value):
            kept.pop()
        kept.append(i)
        if kept[0] <= i - window:
            kept.popleft()
    return out


def _closes(rows: Sequence[PanelRow]) -> list[float]:
    return [r.close for r in rows]


Age = int | None
"""Sessions since a rule entered its open trade (0 = entered today), or None when flat."""


def _age(n: int, entered: int | None) -> Age:
    return None if entered is None else n - 1 - entered


class PositionRule(Strategy):
    """Hold up to `slots` stocks a per-stock entry/exit rule says are in a trade.

    Each holding is a fixed 1/`slots` of capital. When more than `slots` are in,
    the longest-held are kept, as a trader holding positions to their exit
    would. Until 2026-10-18 every in-trade stock got an equal share instead:
    with a hundred names above a golden cross, each day's change in the count
    re-sized all of them, and the bill for those trims (122,004 fills for the
    golden cross) was charged to the rule. Research 113 states both runs.
    """

    rebalance_every = 1

    def __init__(
        self,
        name: str,
        rule: Callable[[Sequence[PanelRow]], Age],
        *,
        lookback: int,
        slots: int,
        instruments: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.rule = rule
        self.lookback = lookback
        self.slots = slots
        self.instruments = instruments
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        names = list(self.instruments) or liquid_universe(view)
        aged: list[tuple[int, str]] = []
        for s in names:
            rows = view.history.get(s)
            if rows and rows[-1].day == view.as_of and (age := self.rule(rows)) is not None:
                aged.append((age, s))
        aged.sort(key=lambda item: (-item[0], item[1]))
        return {s: 1.0 / self.slots for _, s in aged[: self.slots]}


# --- 1. Connors RSI(2) ------------------------------------------------------------


def rsi2_rule(rows: Sequence[PanelRow]) -> Age:
    """leo-aa88/larry_connors_rsi2_bot: above the 200-day average, in when RSI(2) < 5,
    out when the close is above the 5-day average."""
    closes = _closes(rows)
    n = len(closes)
    if n < 200 + 2:
        return None
    sma200, sma5, rsi2 = (
        indicators.sma(closes, 200),
        indicators.sma(closes, 5),
        indicators.rsi(closes, 2),
    )

    def enter(i: int) -> bool:
        trend, value = sma200[i], rsi2[i]
        return trend is not None and value is not None and closes[i] > trend and value < 5

    def leave(i: int) -> bool:
        short = sma5[i]
        return short is not None and closes[i] > short

    return _age(n, in_trade(n, enter, leave, start=max(200, n - STATE_WINDOW)))


# --- 2. IBS -----------------------------------------------------------------------


def _ibs(row: PanelRow) -> float:
    _, high, low, close = row.ohlc()
    return (close - low) / (high - low) if high > low else 0.5


def ibs_rule(rows: Sequence[PanelRow]) -> Age:
    """toniker10/SPY-IBS-Mean-Reversion-Strategy: in when IBS < 0.20, out when IBS > 0.80.
    IBS = (close - low) / (high - low); a day with no range counts 0.5, as there."""
    n = len(rows)
    return _age(
        n,
        in_trade(
            n,
            lambda i: _ibs(rows[i]) < 0.20,
            lambda i: _ibs(rows[i]) > 0.80,
            start=max(0, n - STATE_WINDOW),
        ),
    )


# --- 3. Turtle 20/10 --------------------------------------------------------------


def turtle_rule(rows: Sequence[PanelRow]) -> Age:
    """Harvey-Sun/TurtleTrading, its 20/10 system on stock dailies: in on a close
    above the prior 20-day high; out on a close below the prior 10-day low, or
    2 ATR(20) below the entry close. Units, pyramiding and the 'mean' exit
    variant are left out: one unit, the plain channel exit."""
    n = len(rows)
    if n < 22:
        return None
    bars = [r.ohlc() for r in rows]
    highs, lows, closes = [b[1] for b in bars], [b[2] for b in bars], [b[3] for b in bars]
    atr = indicators.atr(highs, lows, closes, 20)
    high20 = prior_extreme(highs, 20, highest=True)
    low10 = prior_extreme(lows, 10, highest=False)
    entry_close: list[float] = []

    def enter(i: int) -> bool:
        ceiling = high20[i]
        if ceiling is None or closes[i] <= ceiling:
            return False
        entry_close[:] = [closes[i]]
        return True

    def leave(i: int) -> bool:
        stop, floor = atr[i], low10[i]
        below_channel = floor is not None and closes[i] < floor
        below_stop = (
            stop is not None and bool(entry_close) and closes[i] < entry_close[0] - 2 * stop
        )
        return below_channel or below_stop

    return _age(n, in_trade(n, enter, leave, start=max(20, n - STATE_WINDOW)))


# --- 4. Minervini trend template --------------------------------------------------


RS_WEIGHTS = ((63, 0.40), (126, 0.20), (189, 0.20), (252, 0.20))
"""abeer555/Trend-Radar `RS_WEIGHTS`: 3, 6, 9 and 12-month returns."""


def rs_raw(closes: Sequence[float]) -> float | None:
    if len(closes) <= 252 or closes[-253] <= 0:
        return None
    return sum(w * (closes[-1] / closes[-1 - d] - 1.0) for d, w in RS_WEIGHTS)


def trend_template(closes: Sequence[float]) -> bool:
    """abeer555/Trend-Radar `compute_trend_template`, the seven price criteria."""
    if len(closes) < 200 + 22:
        return False
    price = closes[-1]
    ma50, ma150, ma200 = (sum(closes[-k:]) / k for k in (50, 150, 200))
    ma200_month_ago = sum(closes[-222:-22]) / 200
    year = closes[-252:]
    high, low = max(year), min(year)
    return (
        price > ma50
        and price > ma150
        and price > ma200
        and ma150 > ma200
        and ma200 > ma200_month_ago
        and (price - low) / low >= 0.30
        and (high - price) / high <= 0.25
    )


class TrendTemplate(Strategy):
    """Each month, the stocks passing all eight criteria, top 20 by RS score.

    The eighth criterion is the RS rank gate (70, Trend-Radar's
    `TT_MIN_RS_RANK`): a stock's RS composite must be at or above the 70th
    percentile of the point-in-time top 250.
    """

    def __init__(self, name: str, *, hold: int = 20) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = MONTH
        self.lookback = YEAR + 30

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored: list[tuple[float, str, bool]] = []
        for symbol in liquid_universe(view):
            closes = _closes(view.history[symbol])
            score = rs_raw(closes)
            if score is not None:
                scored.append((score, symbol, trend_template(closes)))
        if not scored:
            return {}
        ordered = sorted(score for score, _, _ in scored)
        gate = ordered[int(0.70 * (len(ordered) - 1))]
        passing = sorted(
            ((score, symbol) for score, symbol, ok in scored if ok and score >= gate),
            key=lambda item: (-item[0], item[1]),
        )[: self.hold]
        return {symbol: 1.0 / self.hold for _, symbol in passing}


# --- 5. Accelerating dual momentum ------------------------------------------------


DUAL = ("NIFTYBEES", "JUNIORBEES", "GOLDBEES", "LIQUIDBEES")


def _ret(rows: Sequence[PanelRow], days: int) -> float | None:
    if len(rows) <= days or rows[-1 - days].close <= 0:
        return None
    return rows[-1].close / rows[-1 - days].close - 1.0


class DualMomentum(Strategy):
    """AleksLi1/Accelerating_Dual_Momentum on Indian ETFs.

    The repository's SPY and VBR (large and small caps) become NIFTYBEES and
    JUNIORBEES (the Nifty Next 50); its safe pair, long Treasuries and TIPS,
    becomes GOLDBEES and LIQUIDBEES. Monthly: the risk asset with the higher
    mean of 1, 3 and 6-month return, if that mean is positive; otherwise the
    safe asset with the higher 1-month return.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 6 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        def score(symbol: str) -> float | None:
            rows = view.history.get(symbol) or []
            found = [_ret(rows, d) for d in (MONTH, 3 * MONTH, 6 * MONTH)]
            return None if None in found else sum(x for x in found if x is not None) / 3

        risky = [(s, score(s)) for s in DUAL[:2]]
        best = max(((v, s) for s, v in risky if v is not None), default=None)
        if best is not None and best[0] > 0:
            return {best[1]: 1.0}
        safe = [
            (r, s) for s in DUAL[2:] if (r := _ret(view.history.get(s) or [], MONTH)) is not None
        ]
        return {max(safe)[1]: 1.0} if safe else {}


# --- batch 2 (research 113): golden cross, Supertrend, MACD, Faber TAA -------------


def crossing_rule(fast: Sequence[float | None], slow: Sequence[float | None], n: int) -> Age:
    """In from a cross of `fast` above `slow`, out at the cross back below."""

    def above(i: int) -> bool | None:
        a, b = fast[i], slow[i]
        return None if a is None or b is None else a > b

    def enter(i: int) -> bool:
        return i > 0 and above(i) is True and above(i - 1) is False

    def leave(i: int) -> bool:
        return i > 0 and above(i) is False and above(i - 1) is True

    return _age(n, in_trade(n, enter, leave, start=max(1, n - STATE_WINDOW)))


def golden_cross_rule(rows: Sequence[PanelRow]) -> Age:
    """lukelebaudy/Golden-Cross-Backtester: buy the 50-day average crossing above
    the 200-day, sell the cross back below."""
    closes = _closes(rows)
    if len(closes) < 202:
        return None
    return crossing_rule(indicators.sma(closes, 50), indicators.sma(closes, 200), len(closes))


def _ema(values: Sequence[float], period: int) -> list[float]:
    """Seeded with the first value, as Sunkeerth's `calculate_ema` is."""
    k = 2.0 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * k + out[-1] * (1 - k))
    return out


def macd_rule(rows: Sequence[PanelRow]) -> Age:
    """Sunkeerth/macd-crossover-backtest-three-frameworks: MACD(12, 26) crossing
    above its 9-period signal to buy, below to sell. Long only here."""
    closes = _closes(rows)
    if len(closes) < 60:
        return None
    line = [a - b for a, b in zip(_ema(closes, 12), _ema(closes, 26), strict=True)]
    signal = _ema(line, 9)
    return crossing_rule(list(line), list(signal), len(closes))


def supertrend_up(rows: Sequence[PanelRow], period: int = 10, multiplier: float = 2.2) -> list[int]:
    """darshandeshmukh11/supertrend-backtester `compute_supertrend`: ATR as the
    simple mean of true range, bands at hl2 +/- multiplier x ATR, the usual
    final-band carry, direction +1 up, -1 down, starting down."""
    bars = [r.ohlc() for r in rows]
    highs, lows, closes = [b[1] for b in bars], [b[2] for b in bars], [b[3] for b in bars]
    true_range = [highs[0] - lows[0]] + [
        max(hi - lo, abs(hi - before), abs(lo - before))
        for hi, lo, before in zip(highs[1:], lows[1:], closes[:-1], strict=True)
    ]
    direction: list[int] = []
    upper = lower = 0.0
    for i in range(len(rows)):
        window = true_range[max(0, i - period + 1) : i + 1]
        atr = sum(window) / len(window)
        mid = (highs[i] + lows[i]) / 2
        basic_upper, basic_lower = mid + multiplier * atr, mid - multiplier * atr
        if i == 0:
            upper, lower = basic_upper, basic_lower
            direction.append(-1)
            continue
        upper = basic_upper if basic_upper < upper or closes[i - 1] > upper else upper
        lower = basic_lower if basic_lower > lower or closes[i - 1] < lower else lower
        if direction[-1] == -1:
            direction.append(1 if closes[i] > upper else -1)
        else:
            direction.append(-1 if closes[i] < lower else 1)
    return direction


def supertrend_rule(rows: Sequence[PanelRow]) -> Age:
    """In from the bar the direction turns up until it turns down."""
    if len(rows) < 20:
        return None
    direction = supertrend_up(rows[-STATE_WINDOW:])
    if direction[-1] != 1:
        return None
    turned = next(i for i in range(len(direction) - 1, 0, -1) if direction[i - 1] != 1)
    return len(direction) - 1 - turned


FABER = ("NIFTYBEES", "JUNIORBEES", "GOLDBEES", "MON100")
"""Faber's GTAA classes, as Indian ETFs: large caps, mid caps, gold, US stocks."""
CASH = "LIQUIDBEES"


class FaberTAA(Strategy):
    """mmoraschini/faber-taa on Indian ETFs: each month, each sleeve holds its
    ETF while the close is above its 10-month average (the mean daily close over
    the last ten months, as the repository computes it), else LIQUIDBEES. A
    sleeve whose ETF has under ten months of history sits in LIQUIDBEES."""

    sizing = "strategy"  # fixed sleeve weights are the allocation itself (ADR-122)

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 10 * MONTH + 5

    def target_weights(self, view: MarketView) -> dict[str, float]:
        weights: dict[str, float] = {}
        share = 1.0 / len(FABER)
        for symbol in FABER:
            rows = view.history.get(symbol) or []
            closes = _closes(rows[-10 * MONTH :])
            above = len(closes) >= 10 * MONTH and closes[-1] > sum(closes) / len(closes)
            chosen = symbol if above and rows[-1].day == view.as_of else CASH
            weights[chosen] = weights.get(chosen, 0.0) + share
        return weights


# --- the registry entries -----------------------------------------------------------


STRATEGIES: tuple[PaperStrategy, ...] = (
    PaperStrategy(
        "nse_github_rsi2_daily",
        "Connors RSI(2), daily, liquid NSE stocks (GitHub rule)",
        "github-2021-connors-rsi2-bot",
        "leo-aa88/larry_connors_rsi2_bot (GitHub, 2021)",
        "Above the 200-day average, buy when RSI(2) is under 5; sell when the close is back above the 5-day average.",
        (
            "Among the point-in-time 250 most-traded stocks: in when close > SMA(200) and "
            "RSI(2) < 5, out when close > SMA(5). The repository runs the rule on 15-minute "
            "crypto bars; Connors wrote it for daily stocks, which is what is run here.",
            "Up to 10 names at a tenth of capital each; filled at the next session's close.",
        ),
        200 + STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_rsi2_daily", rsi2_rule, lookback=200 + STATE_WINDOW + 5, slots=10
        ),
    ),
    PaperStrategy(
        "nse_github_ibs_niftybees",
        "IBS reversion on NIFTYBEES (GitHub rule)",
        "github-2026-spy-ibs-mean-reversion",
        "toniker10/SPY-IBS-Mean-Reversion-Strategy (GitHub, 2026)",
        "Buy the Nifty ETF after a close in the bottom fifth of the day's range; sell after one in the top fifth.",
        (
            "IBS = (close - low) / (high - low). In when IBS < 0.20, out when IBS > 0.80, on "
            "NIFTYBEES as the stand-in for SPY.",
            "The repository holds from the signal close; the engine fills at the next close, "
            "one session later.",
        ),
        STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_ibs_niftybees",
            ibs_rule,
            lookback=STATE_WINDOW + 5,
            slots=1,
            instruments=(INDEX_ETF,),
        ),
        "all",
        (INDEX_ETF,),
    ),
    PaperStrategy(
        "nse_github_turtle_20_10",
        "Turtle 20/10 breakout, liquid NSE stocks (GitHub rule)",
        "github-2017-turtle-trading-stocks",
        "Harvey-Sun/TurtleTrading (GitHub, 2017)",
        "Buy a close above the prior 20-day high; sell below the prior 10-day low or 2 ATR under entry.",
        (
            "Among the point-in-time 250 most-traded stocks. One unit; the repository's "
            "pyramiding to four units and ATR position sizing are left out.",
            "Up to 20 names at a twentieth of capital each; filled at the next session's close.",
        ),
        STATE_WINDOW + 25,
        lambda: PositionRule(
            "nse_github_turtle_20_10", turtle_rule, lookback=STATE_WINDOW + 25, slots=20
        ),
    ),
    PaperStrategy(
        "nse_github_minervini_template",
        "Minervini trend template, top 20 by RS (GitHub rule)",
        "github-2026-trend-radar-minervini",
        "abeer555/Trend-Radar (GitHub, 2026)",
        "Each month, hold up to 20 stocks that pass all eight trend-template criteria, ranked by relative strength.",
        (
            "Price above the 50, 150 and 200-day averages; 150 above 200; 200 rising over a "
            "month; at least 30% above the 52-week low and within 25% of the high.",
            "RS = 0.4 x 3-month + 0.2 x each of 6, 9 and 12-month return; RS at or above the "
            "70th percentile of the point-in-time 250. Equal twentieths; monthly.",
        ),
        YEAR + 30,
        lambda: TrendTemplate("nse_github_minervini_template"),
    ),
    PaperStrategy(
        "nse_github_dual_momentum_etf",
        "Accelerating dual momentum, Indian ETFs (GitHub rule)",
        "github-2025-accelerating-dual-momentum",
        "AleksLi1/Accelerating_Dual_Momentum (GitHub, 2025)",
        "Each month, hold the Nifty 50 or Next 50 ETF with the better 1/3/6-month momentum if positive; otherwise gold or cash.",
        (
            "Score = mean of 1, 3 and 6-month return for NIFTYBEES and JUNIORBEES (the "
            "repository's SPY and VBR). Hold the higher if its score is positive.",
            "Otherwise hold GOLDBEES or LIQUIDBEES (for its Treasuries and TIPS), whichever "
            "returned more over the month. Monthly; all in one ETF.",
        ),
        6 * MONTH + 10,
        lambda: DualMomentum("nse_github_dual_momentum_etf"),
        "all",
        DUAL,
    ),
)

STRATEGIES += (
    PaperStrategy(
        "nse_github_golden_cross",
        "Golden cross 50/200, liquid NSE stocks (GitHub rule)",
        "github-2026-golden-cross-backtester",
        "lukelebaudy/Golden-Cross-Backtester (GitHub, 2026)",
        "Buy when the 50-day average crosses above the 200-day; sell at the cross back below.",
        (
            "Among the point-in-time 250 most-traded stocks. A stock is held from a golden "
            "cross to the next death cross, replayed over the last 250 sessions.",
            "Up to 20 names at a twentieth of capital each, or an equal share when more "
            "are in; filled at the next session's close.",
        ),
        200 + STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_golden_cross", golden_cross_rule, lookback=200 + STATE_WINDOW + 5, slots=20
        ),
    ),
    PaperStrategy(
        "nse_github_supertrend_10_22",
        "Supertrend (10, 2.2), liquid NSE stocks (GitHub rule)",
        "github-2026-supertrend-backtester",
        "darshandeshmukh11/supertrend-backtester (GitHub, 2026)",
        "Hold a stock while its Supertrend (ATR 10, multiplier 2.2) points up.",
        (
            "Supertrend as the repository computes it: ATR the simple mean of true range "
            "over 10 days, bands at the bar midpoint +/- 2.2 ATR.",
            "Among the point-in-time 250 most-traded stocks, up to 20 names. The repository "
            "fills at the next open; the engine at the next close.",
        ),
        STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_supertrend_10_22", supertrend_rule, lookback=STATE_WINDOW + 5, slots=20
        ),
    ),
    PaperStrategy(
        "nse_github_macd_crossover",
        "MACD 12/26/9 crossover, liquid NSE stocks (GitHub rule)",
        "github-2026-macd-crossover-three-frameworks",
        "Sunkeerth/macd-crossover-backtest-three-frameworks (GitHub, 2026)",
        "Buy when MACD crosses above its signal line; sell when it crosses below.",
        (
            "MACD = EMA(12) - EMA(26) of the close, signal = EMA(9) of MACD, each seeded "
            "with its first value as the repository does. Long only.",
            "Among the point-in-time 250 most-traded stocks, up to 20 names; filled at the "
            "next session's close.",
        ),
        STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_macd_crossover", macd_rule, lookback=STATE_WINDOW + 5, slots=20
        ),
    ),
    PaperStrategy(
        "nse_github_faber_taa_etf",
        "Faber tactical allocation, Indian ETFs (GitHub rule)",
        "github-2023-faber-taa",
        "mmoraschini/faber-taa (GitHub, 2023)",
        "Each month, a quarter in each of NIFTYBEES, JUNIORBEES, GOLDBEES and MON100 while above its 10-month average; otherwise that quarter in LIQUIDBEES.",
        (
            "10-month average = mean daily close over the last 210 sessions, as the "
            "repository computes it from monthly sums and counts.",
            "MON100 trades from June 2021; before that its quarter sits in LIQUIDBEES.",
        ),
        10 * MONTH + 5,
        lambda: FaberTAA("nse_github_faber_taa_etf"),
        "all",
        (*FABER, CASH),
    ),
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}
