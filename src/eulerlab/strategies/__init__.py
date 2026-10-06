"""The strategy registry — one place that knows what strategies exist.

ADR-037: a strategy is described by **three declarations** — what it must see,
when it is asked, and what it may say. This package holds those declarations
and nothing else. It does not run anything.

**Stage is derived, never stored.** A strategy's lifecycle position is read
from the trial ledger, the same way the research report reads gate verdicts
(T-1606): if it has been evaluated it is `backtested`, otherwise `registered`.
`forward_testing` and `live` are deliberately unreachable today, because no
mechanism exists to put a strategy into either — and a UI that can display a
state the system cannot produce is a UI that will eventually display a lie.

The performance figures shown against a strategy come from the ledger too. Most
strategies have none, and the honest rendering of that is "not measured" rather
than a zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from eulerlab.validation.ledger import LEDGER_PATH, sharpe_of
from eulerlab.validation.ledger import read as read_ledger


class AssetClass(StrEnum):
    """What kind of instrument a strategy trades.

    A `StrEnum` so it serialises to JSON as its value without a converter.
    """

    EQUITY = "equity"
    FUTURES = "futures"
    OPTIONS = "options"
    CRYPTO = "crypto"
    FX = "fx"
    US = "us"
    """US equities, via Alpaca. A separate class from `EQUITY` rather than a
    universe inside it: the two differ in currency, session, settlement and fee
    schedule, and every one of those has already caused a wrong number when the
    distinction was blurred — a QQQ trade charged Indian STT, a dollar result
    labelled in rupees, an NSE session line under a US tab."""
    MUTUAL_FUND = "mutual_fund"
    """AMFI scheme NAVs, resampled to daily bars by `features/alt_panel`.

    A real asset class here rather than a special case: 14,280 schemes are
    landed, and without a name for them the instrument picker could not offer
    them at all.
    """


class Timeframe(StrEnum):
    MINUTE = "1m"
    DAILY = "1d"
    WEEKLY = "1w"


class Stage(StrEnum):
    """Lifecycle position. Only the first two are reachable today."""

    REGISTERED = "registered"
    BACKTESTED = "backtested"
    FORWARD_TESTING = "forward_testing"
    LIVE = "live"
    RETIRED = "retired"


class Emits(StrEnum):
    """Which `Intent` kind the strategy produces (ADR-037)."""

    TARGET_WEIGHT = "TargetWeight"
    TARGET_QUANTITY = "TargetQuantity"
    CONDITIONAL_ENTRY = "ConditionalEntry"
    STRUCTURE = "Structure"


@dataclass(frozen=True)
class Declaration:
    """Everything the console needs to list a strategy.

    `ledger_subjects` is how a strategy is matched to its evidence. It is a
    list because a strategy may have been evaluated under a hypothesis id as
    well as a feature name, and an empty list is the common and honest case —
    most strategies here have never been formally evaluated at all.
    """

    id: str
    title: str
    summary: str

    kind: str
    """`technical`, `fundamental`, `quant`, or `long-term` — how the operator
    thinks about it, not how the engine runs it."""

    shape: str
    """`cross-section`, `pattern`, `event`, or `structure`."""

    asset_class: AssetClass
    timeframe: Timeframe
    emits: Emits

    lookback: int
    """Trailing periods required, in units of `timeframe`."""

    risk_manager: str = ""
    trade_manager: str = ""
    """Empty means none attached. RM and TM are not built yet (ADR-036), so
    every strategy currently reports the flat equal-weight behaviour it
    actually has rather than a sizer it does not."""

    is_strategy_subclass: bool = True
    """False for Tweezer, which cannot satisfy the `Strategy` interface today —
    its data cannot even be expressed in a `MarketView` (ADR-037). Recording it
    here keeps the reason visible instead of leaving it an unexplained absence.
    """

    source: str = ""
    """Where the rule came from, to the section. Empty for hand-written
    strategies; a citation for anything coded from a paper, so provenance is
    carried by the object rather than by memory."""

    published: str = ""
    """What the source reported. Carried so a result here can never be read
    without the prior it is arguing against — which matters most when the prior
    is a published failure."""

    paper_url: str = ""
    """Where the source can be read. A citation says what to look for; a link
    is what a reader actually follows, and the difference decides whether the
    provenance is checked or taken on trust."""

    paper_pdf: str = ""
    """Repo-relative path to the fetched PDF, when `docs/RESEARCH/papers/fetch.sh`
    has run. Empty is the normal state — the PDFs are deliberately not committed,
    because arXiv is a permanent archive and a 1.1 MB binary in git buys nothing
    a single request does not."""

    tested_on: str = ""
    """The instrument and market the source paper tested, in its own words.

    Not what this platform runs it on. Every intraday signal here was published
    against MNQ futures or US equities and runs here on NSE minute bars —
    reading a result without that gap credits a strategy with evidence gathered
    somewhere else entirely.
    """

    recommended_class: str = ""
    """The asset class the source studied, which may differ from the one a run
    was pointed at."""

    logic: list[str] = field(default_factory=list)
    """The implementation, step by step, as coded."""

    ledger_subjects: list[str] = field(default_factory=list)


RESEARCH: dict[str, tuple[str, str, str, list[str]]] = {
    # id -> (citation, what the source reported, what the source tested, steps)
    #
    # The steps describe what the code does, not what the paper proposes. Where
    # the two differ the difference is stated in the step itself, because the
    # console presents these as "the steps as coded" and a reader comparing
    # them against the citation has no other way to see the gap.
    "momentum_12_1": (
        "Jegadeesh & Titman (1993)",
        "Winners minus losers earned about 1% a month over 1965-1989, "
        "before costs and before the crash risk later work identified.",
        "NYSE and AMEX common stocks, monthly, 1965-1989",
        [
            "Score each name by its total return from 252 trading days ago to "
            "21 days ago — twelve months, skipping the most recent one.",
            "The skip is the construction, not a detail: 12-month momentum and "
            "1-month reversal point opposite ways, so an unskipped return "
            "averages a signal with its own opposite.",
            "Sit the day out unless at least 50 names can be scored.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
            "Needs 263 days of history per name, so the first 263 days of any "
            "window produce no position at all.",
        ],
    ),
    "momentum_6_1": (
        "Jegadeesh & Titman (1993)",
        "The same paper's shorter formation window; weaker than 12-1 in their own results.",
        "NYSE and AMEX common stocks, monthly, 1965-1989",
        [
            "Score each name by its total return from 126 trading days ago to "
            "21 days ago — six months, skipping the most recent one.",
            "Sit the day out unless at least 50 names can be scored.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
            "Needs 158 days of history per name.",
        ],
    ),
    "short_term_reversal": (
        "Jegadeesh (1990)",
        "Last month's losers outperformed last month's winners over 1934-1987 "
        "— the opposite sign to momentum at a longer horizon.",
        "NYSE common stocks, monthly, 1934-1987",
        [
            "Score each name by its last 21 trading days' return, negated, so "
            "the worst recent performer ranks highest.",
            "Sit the day out unless at least 50 names can be scored.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
            "Needs 32 days of history per name.",
        ],
    ),
    "low_volatility": (
        "Baker, Bradley & Wurgler (2011)",
        "The lowest-volatility quintile beat the highest over 1968-2008, "
        "which is the opposite of what a risk premium predicts.",
        "US equities, monthly, 1968-2008",
        [
            "Score each name by the median absolute deviation of its daily "
            "returns over the last 63 trading days, negated — quietest ranks "
            "highest.",
            "Median absolute deviation rather than standard deviation: one "
            "spike dominates a stdev, so the score would describe a single day "
            "rather than the stock.",
            "Needs at least 20 usable returns, or the name is unscored.",
            "Sit the day out unless at least 50 names can be scored.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        ],
    ),
    "fifty_two_week_high": (
        "George & Hwang (2004)",
        "Nearness to the 52-week high forecast returns and, unlike momentum, "
        "the forecasts did not reverse over the long run.",
        "US equities, monthly, 1963-2001",
        [
            "Score each name by its last close divided by the highest close in "
            "the last 252 trading days — 1.0 means sitting at its 52-week high.",
            "Needs at least 200 rows in that window, or the name is unscored.",
            "Sit the day out unless at least 50 names can be scored.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        ],
    ),
    "illiquidity_premium": (
        "Amihud (2002)",
        "Illiquid stocks earned a premium for being illiquid, over 1964-1997.",
        "NYSE common stocks, 1964-1997",
        [
            "Score each name by the median of |daily return| / turnover over "
            "the last 63 trading days, negated.",
            "The negation makes the *most liquid* name score highest, and the "
            "engine holds the highest — so as coded this buys the most liquid "
            "names, which is the opposite end from the premium Amihud "
            "measured. Recorded as S-032; not silently flipped, because "
            "turning it round changes what the strategy trades.",
            "Sit the day out unless at least 50 names can be scored.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
            "Market impact is not modelled anywhere in this engine, so a real "
            "illiquidity premium would be collected here without paying the "
            "cost that is the whole reason it exists.",
        ],
    ),
    "small_size": (
        "Banz (1981)",
        "Small firms outearned large ones over 1936-1975 after adjusting for beta.",
        "NYSE common stocks, 1936-1975",
        [
            "Score each name by the negated log of its last close, so a "
            "low-priced name ranks highest.",
            "This is a weak proxy and is here to be measured, not believed: "
            "size is price times shares outstanding, and the share count is "
            "not in the bhavcopy. A low price is not a small company — it is "
            "often a normal one after a split.",
            "Sit the day out unless at least 50 names can be scored.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        ],
    ),
    "quality_composite": (
        "",
        "",
        "",
        [
            "Not from a paper. The three components each have their own "
            "literature; combining them is a choice made here, and it is the "
            "kind of choice the trial ledger exists to count.",
            "Score each name three times — negated return dispersion over 63 "
            "days, negated worst 6-month drawdown, and log median turnover "
            "over 63 days.",
            "Convert each score to a within-feature percentile rank, then average the three.",
            "Drop any name not scored by all three: a name ranked on two "
            "features is not comparable to one ranked on three.",
            "Sit the day out unless at least 20 names survive.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        ],
    ),
    "momentum_quality": (
        "",
        "",
        "",
        [
            "Not from a paper. Momentum's known failure is the crash — winners "
            "are high-beta going into a reversal — and averaging its rank with "
            "drawdown and volatility is the standard response to that. Whether "
            "it helps on this data is an open question.",
            "Score each name on 12-1 momentum, negated worst 6-month drawdown, "
            "and negated 63-day return dispersion.",
            "Convert each to a percentile rank within its feature and average "
            "the three; drop names missing any of them.",
            "Sit the day out unless at least 20 names survive.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        ],
    ),
    "value_reversal": (
        "",
        "",
        "",
        [
            "Not from a paper. Reversal is strongest in illiquid names and most "
            "expensive to trade there; this pairing exposes that tension rather "
            "than resolving it.",
            "Score each name on negated 21-day return and on log median turnover over 63 days.",
            "Convert each to a percentile rank within its feature and average "
            "the two; drop names missing either.",
            "Sit the day out unless at least 20 names survive.",
            "Hold the top 30 equally weighted, rebalancing every 21 trading days.",
        ],
    ),
}
"""Citation, published result, tested universe and coded steps, per strategy.

Separate from the `_published` spec because that tuple is positional and
already long enough that a seventh field would be read by counting commas.
"""


def _published() -> dict[str, Declaration]:
    """The ten from `docs/RESEARCH/017`, each citing its paper.

    Declared here and built by `backtest.published.BUILDERS`, so a strategy
    cannot appear in the console without something able to run it.
    """
    spec: list[tuple[str, str, str, str, str, int, list[str]]] = [
        (
            "momentum_12_1",
            "Momentum 12-1",
            "Buy 12-month winners, skipping the last month. Jegadeesh & Titman (1993).",
            "technical",
            "cross-section",
            263,
            ["H-0001", "momentum_12_1"],
        ),
        (
            "momentum_6_1",
            "Momentum 6-1",
            "The shorter formation window Jegadeesh & Titman (1993) also test.",
            "technical",
            "cross-section",
            158,
            ["momentum_6_1"],
        ),
        (
            "short_term_reversal",
            "Short-term reversal",
            "Last month's losers outperform. Jegadeesh (1990), Lehmann (1990).",
            "technical",
            "cross-section",
            32,
            ["reversal_1m"],
        ),
        (
            "low_volatility",
            "Low-volatility anomaly",
            "Low-volatility stocks outperformed over 41 years. Baker, Bradley & Wurgler (2011).",
            "quant",
            "cross-section",
            73,
            ["low_volatility"],
        ),
        (
            "fifty_two_week_high",
            "52-week high",
            "Nearness to the 52-week high forecasts returns, and does not reverse. George & Hwang (2004).",
            "technical",
            "cross-section",
            210,
            ["price_to_52w_high"],
        ),
        (
            "illiquidity_premium",
            "Illiquidity premium",
            "Illiquid stocks earn a premium. Amihud (2002). Market impact is NOT modelled here (T-907).",
            "quant",
            "cross-section",
            73,
            ["illiquidity_amihud"],
        ),
        (
            "small_size",
            "Size effect",
            "Small firms outearned large. Banz (1981). Proxied by negated log price, which is weak.",
            "fundamental",
            "cross-section",
            11,
            ["small_size"],
        ),
        (
            "quality_composite",
            "Quality composite",
            "Low volatility, shallow drawdowns and liquidity ranked together. No single paper.",
            "quant",
            "cross-section",
            136,
            [],
        ),
        (
            "momentum_quality",
            "Momentum, crash-filtered",
            "Momentum averaged with drawdown and volatility — the standard answer to momentum crashes.",
            "quant",
            "cross-section",
            263,
            ["momentum_12_1"],
        ),
        (
            "value_reversal",
            "Reversal, liquidity-filtered",
            "Reversal is strongest where it is most expensive to trade. This pairing exposes that.",
            "quant",
            "cross-section",
            73,
            ["reversal_1m"],
        ),
    ]
    return {
        key: Declaration(
            id=key,
            title=title,
            summary=summary,
            kind=kind,
            shape=shape,
            asset_class=AssetClass.EQUITY,
            timeframe=Timeframe.DAILY,
            emits=Emits.TARGET_WEIGHT,
            lookback=lookback,
            ledger_subjects=subjects,
            source=RESEARCH.get(key, ("", "", "", []))[0],
            published=RESEARCH.get(key, ("", "", "", []))[1],
            tested_on=RESEARCH.get(key, ("", "", "", []))[2],
            recommended_class=AssetClass.EQUITY if RESEARCH.get(key, ("",))[0] else "",
            logic=RESEARCH.get(key, ("", "", "", []))[3],
            paper_url=paper_url(RESEARCH.get(key, ("",))[0]),
            paper_pdf=paper_pdf(RESEARCH.get(key, ("",))[0]),
        )
        for key, title, summary, kind, shape, lookback, subjects in spec
    }


REGISTRY: dict[str, Declaration] = {
    "rank_and_hold": Declaration(
        id="rank_and_hold",
        title="Rank and hold",
        summary="Hold the top N names by a feature, equally weighted, rebalanced periodically.",
        kind="technical",
        shape="cross-section",
        asset_class=AssetClass.EQUITY,
        timeframe=Timeframe.DAILY,
        emits=Emits.TARGET_WEIGHT,
        lookback=263,
        # Every `ic` trial in the ledger evaluated a feature that this strategy
        # ranks on, and H-0001 is the momentum configuration the gate killed.
        ledger_subjects=["H-0001", "momentum_12_1"],
    ),
    "buy_and_hold": Declaration(
        id="buy_and_hold",
        title="Buy and hold",
        summary="Equal-weight the most liquid names and never trade again. The engine's control.",
        kind="technical",
        shape="cross-section",
        asset_class=AssetClass.EQUITY,
        timeframe=Timeframe.DAILY,
        emits=Emits.TARGET_WEIGHT,
        lookback=2,
        logic=[
            "Not from a paper — this is the engine's control, and it is here "
            "to be compared against, not traded.",
            "Rank every instrument by the turnover on its latest row and take the 30 largest.",
            "Hold them equally weighted and never rebalance.",
            "Its return should track the market and its cost should be one "
            "round of entry charges. If either is wrong the engine is wrong, "
            "which is far easier to see here than inside a real strategy.",
        ],
    ),
    "tweezer_bottom": Declaration(
        id="tweezer_bottom",
        title="Tweezer Bottom",
        summary=(
            "Two-candle intraday reversal on 15, 30 or 60-minute candles, entered on a "
            "break of the first candle's high, as specified in the operator's report "
            "(research/papers/protective-collar-2026-tweezer-bottom.yaml)."
        ),
        kind="technical",
        shape="pattern",
        asset_class=AssetClass.EQUITY,
        timeframe=Timeframe.MINUTE,
        emits=Emits.CONDITIONAL_ENTRY,
        lookback=100,
        risk_manager="risk-pct",
        trade_manager="bracket",
        is_strategy_subclass=False,
        logic=[
            "A practitioner candlestick pattern, specified in the operator's June 2026 "
            "report rather than a published paper.",
            "Candles of 15, 30 or 60 minutes built from Kite minute bars; indicators "
            "read the last 100 candles across sessions.",
            "Require candle 1 bearish, its body at least 30% of its range, "
            "and its range at least 0.05% of price.",
            "Require candle 2 bullish, body at least 60% of its range, same range floor.",
            "Require the two lows to match within 0.15% — that matching pair is the tweezer.",
            "Require a downtrend into it: candle 2 closes below a falling 20-period SMA.",
            "Require the pair to sit within 0.5% of the swing low of the 10 "
            "candles before candle 1.",
            "Require 25 <= ADX(14) < 50, 25 <= RSI(14) <= 40, and ATR(14) at least 0.3% "
            "of price. No signal from a candle closing at or after 15:00.",
            "Enter on a stop at candle 1's high; stop at the pattern low minus the larger "
            "of 0.1% and one ATR; skip unless risk is 1.0-1.5% of entry.",
            "Half off at 2R, the rest at 3R; after +1.5R trail 0.5% below the peak. "
            "Sized so the stop costs 1% of equity.",
        ],
    ),
}


PAPERS: dict[str, tuple[str, str]] = {
    # citation prefix -> (url, repo-relative pdf)
    "Mesfin (2026) arXiv:2605.04004": (
        "https://arxiv.org/abs/2605.04004",
        "docs/RESEARCH/papers/mesfin-2026-arxiv-2605.04004-intraday-falsification.pdf",
    ),
    "Zarattini": (
        "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284",
        "",
    ),
    "Cohen (2023)": (
        "https://www.aimspress.com/article/doi/10.3934/math.2023419",
        "",
    ),
    # The same paper as above, cited in the other house style. Both spellings
    # are kept rather than normalised at one call site, because a citation is
    # written by whoever declares the signal and the lookup has to survive that.
    "Cohen, G. (2023)": (
        "https://www.aimspress.com/article/doi/10.3934/math.2023419",
        "",
    ),
    # The daily cross-sectional factors. DOIs rather than publisher pages: a
    # DOI is the identifier that does not rot when a journal re-platforms.
    # Each was resolved against Crossref before being written here, because a
    # citation that links to the wrong paper is worse than one that links
    # nowhere — it is confidently wrong, and nobody re-checks a working link.
    "Jegadeesh & Titman (1993)": (
        "https://doi.org/10.1111/j.1540-6261.1993.tb04702.x",
        "",
    ),
    "Jegadeesh (1990)": (
        "https://doi.org/10.1111/j.1540-6261.1990.tb05110.x",
        "",
    ),
    "Baker, Bradley & Wurgler (2011)": (
        "https://doi.org/10.2469/faj.v67.n1.4",
        "",
    ),
    "George & Hwang (2004)": (
        "https://doi.org/10.1111/j.1540-6261.2004.00695.x",
        "",
    ),
    "Amihud (2002)": (
        "https://doi.org/10.1016/S1386-4181(01)00024-6",
        "",
    ),
    "Banz (1981)": (
        "https://doi.org/10.1016/0304-405X(81)90018-0",
        "",
    ),
}

CITATION_TAGS = ("[paper] ", "[literature] ", "[practitioner] ", "[adaptation] ")
"""Prefixes a declaration may put in front of its citation.

They classify how much weight the source carries — a peer-reviewed paper is not
a practitioner blog post — and they sit *before* the citation, so a plain
`startswith` match against a citation prefix misses every tagged source. That is
how `par_deviation` came to show no paper link while citing Cohen (2023): the
declaration reads `[paper] Cohen, G. (2023)...` and the lookup was comparing
against `Cohen`."""


def _bare_citation(source: str) -> str:
    """A citation with any classification tag stripped from the front."""
    for tag in CITATION_TAGS:
        if source.startswith(tag):
            return source[len(tag) :]
    return source


"""Where each cited source can actually be read.

Matched on the citation's prefix rather than stored per signal, because
seventeen signals cite six sections of one paper and repeating the URL
seventeen times is seventeen chances for one of them to drift.

The PDF path is empty where the file is not fetchable by script — SSRN answers
403 — and empty is the honest value. `docs/RESEARCH/papers/fetch.sh` populates
what it can; the PDFs are deliberately uncommitted.
"""


def paper_url(source: str) -> str:
    """The link for a citation, or empty when the source is not a paper.

    Takes the citation text, not a strategy id — passing an id returns empty,
    which is how the sweep endpoint shipped with every paper link missing.
    """
    bare = _bare_citation(source)
    for prefix, (url, _pdf) in PAPERS.items():
        if bare.startswith(prefix):
            return url
    return ""


def paper_pdf(source: str) -> str:
    """The local PDF for a citation, if one has been fetched."""
    from pathlib import Path

    bare = _bare_citation(source)
    for prefix, (_url, pdf) in PAPERS.items():
        if bare.startswith(prefix) and pdf and Path(pdf).exists():
            return pdf
    return ""


def _paper_signals() -> dict[str, Declaration]:
    """Declarations for the intraday signals coded from published papers.

    Derived from `intraday.papers.SIGNALS` rather than hand-written, so the
    library cannot list a signal that does not exist or miss one that does.

    All of them report `is_strategy_subclass=False` for the same reason Tweezer
    does: they emit a conditional entry with a bracket, which cannot be
    expressed as target weights over a daily panel (ADR-037). They run through
    the intraday scanner instead.
    """
    from eulerlab.intraday.papers import SIGNALS

    return {
        signal.id: Declaration(
            id=signal.id,
            title=signal.title,
            summary=signal.published,
            kind="technical",
            shape="pattern",
            asset_class=AssetClass.EQUITY,
            timeframe=Timeframe.MINUTE,
            emits=Emits.CONDITIONAL_ENTRY,
            lookback=80,
            risk_manager="risk-pct",
            trade_manager="bracket",
            is_strategy_subclass=False,
            source=signal.source,
            published=signal.published,
            tested_on=signal.tested_on,
            recommended_class=signal.recommended_class,
            logic=list(signal.logic),
            paper_url=paper_url(signal.source),
            paper_pdf=paper_pdf(signal.source),
        )
        for signal in SIGNALS.values()
    }


def _india_signals() -> dict[str, Declaration]:
    """The four US signals that cleared the bar, re-declared for NSE.

    Separate registry entries sharing the US `detect` functions. A strategy id
    that carried both a US and an India result would show one strategy with two
    Sharpes and no way to say which claim was being made — and would count as
    one subject where two were tested, which is the denominator the
    deflated-Sharpe correction uses.
    """
    from eulerlab.intraday.india import INDIA_SIGNALS

    return {
        signal.id: Declaration(
            id=signal.id,
            title=signal.title,
            summary=signal.published,
            kind="technical",
            shape="pattern",
            asset_class=AssetClass.EQUITY,
            timeframe=Timeframe.MINUTE,
            emits=Emits.CONDITIONAL_ENTRY,
            lookback=80,
            risk_manager="risk-pct",
            trade_manager="bracket",
            is_strategy_subclass=False,
            source=signal.source,
            published=signal.published,
            tested_on=signal.tested_on,
            recommended_class=signal.recommended_class,
            logic=list(signal.logic),
            # The adaptation cites the same paper, so the link resolves through
            # the `[adaptation] ` tag exactly as `[paper] ` does.
            paper_url=paper_url(signal.source),
            paper_pdf=paper_pdf(signal.source),
        )
        for signal in INDIA_SIGNALS.values()
    }


# The published set joins the hand-written ones. `rank_and_hold` is dropped in
# favour of `momentum_12_1`, which is the same strategy under its paper's name.
REGISTRY.pop("rank_and_hold", None)
REGISTRY.update(_published())


def _crypto_signals() -> dict[str, Declaration]:
    """Declarations for the minute-level crypto signals.

    Their `published` field carries the provenance tier, because these do not
    all have the same standing: one is from a peer-reviewed paper, two from
    documented literature, seven are practitioner constructions with no
    academic validation found. A library that presented them identically would
    be flattering seven of them.
    """
    from eulerlab.intraday.crypto_signals import CRYPTO_SIGNALS

    return {
        signal.id: Declaration(
            id=signal.id,
            title=signal.title,
            summary=signal.published,
            kind="technical",
            shape="pattern",
            asset_class=AssetClass.CRYPTO,
            timeframe=Timeframe.MINUTE,
            emits=Emits.CONDITIONAL_ENTRY,
            lookback=120,
            risk_manager="risk-pct",
            trade_manager="bracket",
            is_strategy_subclass=False,
            source=f"[{signal.provenance}] {signal.source}",
            published=signal.published,
            tested_on=signal.source,
            recommended_class=AssetClass.CRYPTO.value,
            # Resolved here as well as in `_paper_signals`, or a crypto signal
            # with a real paper shows none. `par_deviation` cites Cohen (2023)
            # and displayed no source for exactly this reason: the field was
            # only ever populated on the other branch.
            paper_url=paper_url(f"[{signal.provenance}] {signal.source}"),
            paper_pdf=paper_pdf(f"[{signal.provenance}] {signal.source}"),
            logic=list(signal.logic),
        )
        for signal in CRYPTO_SIGNALS.values()
    }


REGISTRY.update(_paper_signals())
REGISTRY.update(_crypto_signals())
REGISTRY.update(_india_signals())


@dataclass(frozen=True)
class FleetRow:
    """A declaration joined to whatever evidence the ledger holds about it."""

    declaration: Declaration
    stage: Stage
    sharpe: float | None
    """None means never measured. It is not zero, and must not render as zero."""

    trials: int


def _evidence(
    path: object = LEDGER_PATH,
) -> tuple[dict[str, float], dict[str, int], dict[str, int]]:
    """Latest Sharpe, total trials, and trials that actually ran the strategy.

    The third is separate for a reason. An `ic` entry evaluates a **feature** —
    its rank correlation with forward returns — not the strategy that ranks on
    it. Counting one as a backtest would let `short_term_reversal` report
    "backtested" because somebody once IC-screened `reversal_1m`, which is a
    different claim about a different object.

    The trial still counts toward the bar, because the search really happened.
    Only the *stage* is withheld.
    """
    sharpes: dict[str, float] = {}
    counts: dict[str, int] = {}
    evaluated: dict[str, int] = {}
    for entry in read_ledger(path):  # type: ignore[arg-type]
        counts[entry.subject] = counts.get(entry.subject, 0) + 1
        if entry.kind != "ic":
            evaluated[entry.subject] = evaluated.get(entry.subject, 0) + 1
        value = sharpe_of(entry)
        if value is not None:
            sharpes[entry.subject] = value
    return sharpes, counts, evaluated


def fleet(path: object = LEDGER_PATH) -> list[FleetRow]:
    """Every registered strategy, with its evidence.

    Sorted by id so the list is stable between calls — a console whose rows
    move between refreshes is one nobody can point at.
    """
    sharpes, counts, evaluated = _evidence(path)
    rows: list[FleetRow] = []
    for declaration in REGISTRY.values():
        subjects = declaration.ledger_subjects
        trials = sum(counts.get(s, 0) for s in subjects)
        ran = sum(evaluated.get(s, 0) for s in subjects)
        measured = [sharpes[s] for s in subjects if s in sharpes]
        rows.append(
            FleetRow(
                declaration=declaration,
                # Backtested requires the STRATEGY to have been run, not a
                # feature it happens to rank on. Nothing can be further along:
                # there is no mechanism to promote to forward testing or live,
                # so those stages are unreachable by design.
                stage=Stage.BACKTESTED if ran else Stage.REGISTERED,
                sharpe=max(measured) if measured else None,
                trials=trials,
            )
        )
    return sorted(rows, key=lambda r: r.declaration.id)
