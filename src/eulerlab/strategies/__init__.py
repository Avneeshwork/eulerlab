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
    ),
    "tweezer_bottom": Declaration(
        id="tweezer_bottom",
        title="Tweezer Bottom",
        summary=(
            "Two-candle reversal on minute bars, with a stop-entry bracket. "
            "Extremely rare: 2 setups in 136,740 candles."
        ),
        kind="technical",
        shape="pattern",
        asset_class=AssetClass.EQUITY,
        timeframe=Timeframe.MINUTE,
        emits=Emits.CONDITIONAL_ENTRY,
        lookback=60,
        risk_manager="risk-pct",
        trade_manager="bracket",
        is_strategy_subclass=False,
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
}

CITATION_TAGS = ("[paper] ", "[literature] ", "[practitioner] ")
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
            logic=list(signal.logic),
        )
        for signal in CRYPTO_SIGNALS.values()
    }


REGISTRY.update(_paper_signals())
REGISTRY.update(_crypto_signals())


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
