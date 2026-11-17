"""The strategy registry — one place that knows what strategies exist.

ADR-037: a strategy is described by **three declarations** — what it must see,
when it is asked, and what it may say. This package holds those declarations
and nothing else. It does not run anything.

**Stage is derived, never stored.** A strategy's lifecycle position is read
from the trial ledger, the same way the research report reads gate verdicts
(T-1606): if it has been evaluated it is `backtested`, otherwise `registered`.
`forward_testing` and `live` are read the same way (`forward.stage`, T-3311):
forward testing is a gate PROMOTE in the ledger plus a paper deployment the
operator started on or after it; live is an active live deployment.

The performance figures shown against a strategy come from the ledger too. Most
strategies have none, and the honest rendering of that is "not measured" rather
than a zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

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
    """Lifecycle position, derived from the ledger and the deployments (`forward.stage`)."""

    REGISTERED = "registered"
    BACKTESTED = "backtested"
    PROMOTED = "promoted"
    """The gate said PROMOTE; no paper deployment yet."""
    PAPER_CANDIDATE = "paper_candidate"
    """The gate said PAPER; no paper deployment yet (ADR-141)."""
    PAPER_EVALUATION = "paper_evaluation"
    """Paper-trading on a gate PAPER verdict: more evidence, never live (ADR-141)."""
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


def _research() -> dict[str, tuple[str, str, str, list[str]]]:
    """id -> (citation, what the source reported, what the source tested, steps).

    Each published strategy's file holds its own entry (`RESEARCH`), beside the
    code it describes (ADR-219).

    The steps describe what the code does, not what the paper proposes. Where
    the two differ the difference is stated in the step itself, because the
    console presents these as "the steps as coded" and a reader comparing
    them against the citation has no other way to see the gap.
    """
    from eulerlab.strategies.daily.published import MODULES

    return {module.__name__.rsplit(".", 1)[1]: module.RESEARCH for module in MODULES}


def _published() -> dict[str, Declaration]:
    """The ten from `docs/RESEARCH/017`, each citing its paper.

    Declared here and built by `backtest.published.BUILDERS`, so a strategy
    cannot appear in the console without something able to run it.
    """
    from eulerlab.strategies.daily.published import MODULES

    spec: list[tuple[str, str, str, str, str, int, list[str]]] = [
        (module.__name__.rsplit(".", 1)[1], *module.SPEC) for module in MODULES
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
    from eulerlab.strategies.intraday.papers import SIGNALS

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
    from eulerlab.strategies.intraday.india import INDIA_SIGNALS

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
RESEARCH = _research()
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
    from eulerlab.strategies.intraday.crypto import CRYPTO_SIGNALS

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


def _india_papers() -> dict[str, Declaration]:
    """Strategies from papers on Indian equities, one per paper in
    `research/papers/`, built by `backtest.india_papers`."""
    from eulerlab.strategies.daily.india_papers import STRATEGIES

    return {
        s.id: Declaration(
            id=s.id,
            title=s.title,
            summary=s.summary,
            kind="quant",
            shape="cross-section" if s.universe != "all" else "single-instrument",
            asset_class=AssetClass.EQUITY,
            timeframe=Timeframe.DAILY,
            emits=Emits.TARGET_WEIGHT,
            lookback=s.lookback,
            source=f"[paper] {s.citation}",
            published=s.summary,
            tested_on="NSE equities",
            recommended_class=AssetClass.EQUITY,
            logic=list(s.logic),
        )
        for s in STRATEGIES
    }


def _screener_models() -> dict[str, Declaration]:
    """The stock screener's long-term and swing models (ADR-136), built by
    `backtest.screener_models`, on the same engine and universe as the India papers."""
    from eulerlab.strategies.daily.screener import STRATEGIES

    return {
        s.id: Declaration(
            id=s.id,
            title=s.title,
            summary=s.summary,
            kind="quant",
            shape="single-instrument",
            asset_class=AssetClass.EQUITY,
            timeframe=Timeframe.DAILY,
            emits=Emits.TARGET_WEIGHT,
            lookback=s.lookback,
            source=f"[paper] {s.citation}",
            published=s.summary,
            tested_on="NSE equities",
            recommended_class=AssetClass.EQUITY,
            logic=list(s.logic),
        )
        for s in STRATEGIES
    }


def _github_daily() -> dict[str, Declaration]:
    """Daily rules from public GitHub repositories (research 113), built by
    `backtest.github_daily`, and the published momentum and reversal
    refinements of its batch 3 (`backtest.evidence_daily`), on the same engine
    and universe as the India papers."""
    from eulerlab.strategies.daily import events as events_daily
    from eulerlab.strategies.daily import evidence as evidence_daily
    from eulerlab.strategies.daily import github as github_daily

    # A GitHub rule is cited as one wherever it is coded (`nse_github_*`).
    tagged = [("[GitHub]", s) for s in github_daily.STRATEGIES] + [
        ("[GitHub]" if s.id.startswith("nse_github_") else "[paper]", s)
        for s in (*evidence_daily.STRATEGIES, *events_daily.STRATEGIES)
    ]

    return {
        s.id: Declaration(
            id=s.id,
            title=s.title,
            summary=s.summary,
            kind="quant",
            shape="single-instrument",
            asset_class=AssetClass.EQUITY,
            timeframe=Timeframe.DAILY,
            emits=Emits.TARGET_WEIGHT,
            lookback=s.lookback,
            source=f"{tag} {s.citation}",
            published=s.summary,
            tested_on="NSE equities",
            recommended_class=AssetClass.EQUITY,
            logic=list(s.logic),
        )
        for tag, s in tagged
    }


def _studies() -> dict[str, Declaration]:
    """Strategies that run as calculations, outside both engines.

    The gap strategy holds a future from one close to the next open. Tier A and
    Tier B fill a decision at the *next close*, so it cannot be a `Strategy`;
    it is listed here so it can be found, run and compared like any other, and
    the API runs it through `research.gap_forecast` (research 072).
    """
    from eulerlab.research.gap_forecast import CALM_RISE_ID, CALM_RISE_LOGIC, CALM_RISE_TITLE

    return {
        CALM_RISE_ID: Declaration(
            id=CALM_RISE_ID,
            title=CALM_RISE_TITLE,
            summary=(
                "After a rising Nifty day on which India VIX fell, hold the near-month "
                "Nifty future from the close to the next open."
            ),
            kind="quant",
            shape="event",
            asset_class=AssetClass.FUTURES,
            timeframe=Timeframe.DAILY,
            emits=Emits.TARGET_QUANTITY,
            lookback=1,
            is_strategy_subclass=False,
            source="[paper] Mukherjee & Mandal (2025), IJFMR 7(4)",
            published=(
                "A GREEN candle with falling India VIX was followed by a gap up 69.6% of "
                "the time (810 of 1,163), 2010 to June 2025. Accuracy only; no trade, no costs."
            ),
            paper_url="https://www.ijfmr.com/papers/2025/4/53859.pdf",
            tested_on="Nifty 50 index, daily, 2010 to June 2025",
            recommended_class=AssetClass.FUTURES.value,
            logic=list(CALM_RISE_LOGIC),
        )
    }


REGISTRY.update(_paper_signals())
REGISTRY.update(_crypto_signals())
REGISTRY.update(_india_signals())
REGISTRY.update(_india_papers())
REGISTRY.update(_github_daily())
REGISTRY.update(_screener_models())
REGISTRY.update(_studies())


def _research_studies() -> dict[str, Declaration]:
    """Papers coded as studies and run by their own make target.

    `studies.ENTRIES` is the list. None can be run from the library; their
    results reach it through `research/library_sync.py`.
    """
    from eulerlab.strategies import studies

    out: dict[str, Declaration] = {}
    for entry in studies.ENTRIES:
        asset_class = AssetClass(entry["asset_class"])
        out[entry["id"]] = Declaration(
            id=entry["id"],
            title=entry["title"],
            summary=entry["summary"],
            kind=entry["kind"],
            shape=entry["shape"],
            asset_class=asset_class,
            timeframe=Timeframe(entry["timeframe"]),
            emits=Emits.STRUCTURE if entry["shape"] == "structure" else Emits.CONDITIONAL_ENTRY,
            lookback=1,
            is_strategy_subclass=False,
            source=entry["source"],
            published=entry["published"],
            paper_url=entry["paper_url"],
            tested_on=entry["tested_on"],
            recommended_class=asset_class.value,
            logic=[
                *entry["logic"],
                f"Run with `{studies.COMMANDS[entry['study']]}`; written up in {entry['research']}.",
            ],
        )
    return out


REGISTRY.update(_research_studies())


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


def _stage(strategy_id: str, ran: int, gate: dict[str, Any], active: list[Any]) -> Stage:
    from eulerlab import forward

    later = forward.stage(strategy_id, gate=gate, deployments=active)
    if later == "live":
        return Stage.LIVE
    if later == "forward_testing":
        return Stage.FORWARD_TESTING
    if later == "paper_evaluation":
        return Stage.PAPER_EVALUATION
    if later == "promoted":
        return Stage.PROMOTED
    if later == "paper_candidate":
        return Stage.PAPER_CANDIDATE
    return Stage.BACKTESTED if ran else Stage.REGISTERED


def _config_line(config: dict[str, Any]) -> str:
    """One configuration in words: the rule, or the feature with its settings, so a card's
    configurations that share a feature still read as different lines."""
    if config.get("rule"):
        return str(config["rule"])
    parts = [str(config.get("feature") or "")]
    if config.get("top_n"):
        parts.append(f"top {config['top_n']}")
    if config.get("rebalance"):
        parts.append(f"rebalance every {config['rebalance']} days")
    return ", ".join(p for p in parts if p)


def gated_hypotheses(gate: dict[str, Any], root: object = None) -> list[Declaration]:
    """A declaration for each hypothesis whose latest gate verdict is PROMOTE or PAPER.

    So the console lists what the gate passed and its Deploy button can start
    a paper book (`forward.build` for rank-and-hold cards, `deploy/rule_book.py`
    for the intraday rules). Built at read time because verdicts change.
    """
    from pathlib import Path

    import yaml

    from eulerlab import forward
    from eulerlab.deploy import rule_book
    from eulerlab.filecache import read_yaml

    folder = Path(str(root)) if root is not None else forward.HYPOTHESES
    out: list[Declaration] = []
    for hypothesis, (verdict, _) in sorted(gate.items()):
        verdict = verdict.upper()
        if not forward.is_hypothesis(hypothesis) or not verdict.startswith(("PROMOTE", "PAPER")):
            continue
        path = folder / f"{hypothesis}.yaml"
        try:
            card = read_yaml(path) or {}
        except (OSError, yaml.YAMLError):
            continue
        intraday = rule_book.is_rule(hypothesis)
        rules = [_config_line(c) for c in card.get("configurations") or []]
        out.append(
            Declaration(
                id=hypothesis,
                title=f"{hypothesis} · {card.get('title', '')}",
                summary=str(card.get("claim") or ""),
                kind="quant",
                shape="event" if intraday else "cross-section",
                asset_class=AssetClass.EQUITY,
                timeframe=Timeframe.MINUTE if intraday else Timeframe.DAILY,
                emits=Emits.CONDITIONAL_ENTRY if intraday else Emits.TARGET_WEIGHT,
                lookback=1,
                is_strategy_subclass=not intraday,
                source=f"research {(card.get('source') or {}).get('research', '')}".strip(),
                published=f"gate verdict {verdict}",
                logic=[r for r in rules if r],
                ledger_subjects=[hypothesis],
            )
        )
    return out


def fleet(path: object = LEDGER_PATH) -> list[FleetRow]:
    """Every registered strategy, with its evidence.

    Sorted by id so the list is stable between calls — a console whose rows
    move between refreshes is one nobody can point at.
    """
    sharpes, counts, evaluated = _evidence(path)
    from eulerlab import forward

    gate = forward.verdicts(path)  # type: ignore[arg-type]
    try:
        from eulerlab.deploy import deployments as store

        active = store.all_deployments()
    except Exception:  # a broken deployment file must not hide the strategy list
        active = []
    rows: list[FleetRow] = []
    gated = [d for d in gated_hypotheses(gate) if d.id not in REGISTRY]
    for declaration in [*REGISTRY.values(), *gated]:
        subjects = declaration.ledger_subjects
        trials = sum(counts.get(s, 0) for s in subjects)
        ran = sum(evaluated.get(s, 0) for s in subjects)
        measured = [sharpes[s] for s in subjects if s in sharpes]
        rows.append(
            FleetRow(
                declaration=declaration,
                # Backtested requires the STRATEGY to have been run, not a
                # feature it happens to rank on. Forward testing and live are
                # read from a gate PROMOTE plus a deployment (forward.stage, T-3311).
                stage=_stage(declaration.id, ran, gate, active),
                sharpe=max(measured) if measured else None,
                trials=trials,
            )
        )
    return sorted(rows, key=lambda r: r.declaration.id)
