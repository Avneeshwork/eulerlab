"""Indian transaction costs, versioned by effective date.

**The central fact of this module: the rates changed inside our backtest
window, more than once.** STT on futures was 0.0125% until October 2024, then
0.02%, and 0.05% from April 2026 — a factor of four across a history we
actually hold. A constants file would silently apply today's rates to a 2016
trade, and that is not a conservative error, it is simply a wrong one.

So costs are a schedule keyed by effective date and queried with the *trade
date*, the same shape as the time-versioned lot sizes in Sprint 3. Sources and
fetch dates are in `docs/RESEARCH/013-indian-transaction-costs.md`.

**Every charge is modelled as it is actually levied**, because the sides
differ and a blended round-trip percentage is wrong in both directions:

- STT: delivery both sides; intraday and futures **sell only**; options
  premium **sell only**; exercise on the **buyer**.
- Stamp duty: **buy side only**.
- GST: 18% on **brokerage plus transaction charges**, never on turnover.
- SEBI fee: a flat ₹10 per crore.

**The exercise rule is itself time-versioned**, and this is the trap the
module exists for. Until 2019-08-31 STT on exercise was charged on the full
notional settlement value; from 2019-09-01 it is charged on intrinsic value
only. On a near-the-money expiry the old rule could cost more than the entire
profit — the "STT trap" — so a 2016-2019 options backtest that ignores it
overstates returns on every single expiry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Segment(StrEnum):
    EQUITY_DELIVERY = "equity_delivery"
    EQUITY_INTRADAY = "equity_intraday"
    FUTURES = "futures"
    OPTIONS = "options"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class ExerciseBasis(StrEnum):
    """What STT on an exercised option is charged on."""

    NOTIONAL = "notional"
    """Settlement price times quantity. The rule until 2019-08-31."""

    INTRINSIC = "intrinsic"
    """(settlement - strike) times quantity. From 2019-09-01."""


@dataclass(frozen=True)
class RateSet:
    """Every rate in force from `effective_from` until the next entry."""

    effective_from: date
    stt_delivery: float
    """Both sides."""
    stt_intraday_sell: float
    stt_futures_sell: float
    stt_options_premium_sell: float
    stt_options_exercise: float
    exercise_basis: ExerciseBasis
    stamp_delivery_buy: float
    stamp_intraday_buy: float
    stamp_futures_buy: float
    stamp_options_buy: float
    exchange_txn_cash: float
    exchange_txn_futures: float
    exchange_txn_options: float
    sebi_turnover_fee: float
    gst: float
    stt_fund_delivery_sell: float = 0.00001
    """A unit of an equity-oriented fund (an ETF) with delivery: 0.001% on the
    sale and nothing on the purchase, against 0.1% on both sides of a share.
    Intraday, a unit pays the share rate. Unchanged over the whole schedule.

    # ASSUMPTION A-047: from two AMC publications (research 066); the statute
    # itself could not be fetched."""
    note: str = ""


# Ordered oldest first. A trade takes the last entry whose effective_from is
# on or before its trade date.
#
# ASSUMPTION A-016: every rate here comes from broker and tax-portal summaries
# that agree with one another, not from the CBDT notification or the NSE
# circular — both NSE sources timed out on repeated fetches and circular
# FATAX73524 would not decode. See docs/RESEARCH/013.
SCHEDULE: tuple[RateSet, ...] = (
    RateSet(
        effective_from=date(2015, 1, 1),
        stt_delivery=0.001,
        stt_intraday_sell=0.00025,
        stt_futures_sell=0.000125,
        stt_options_premium_sell=0.000625,
        stt_options_exercise=0.00125,
        exercise_basis=ExerciseBasis.NOTIONAL,
        stamp_delivery_buy=0.00015,
        stamp_intraday_buy=0.00003,
        stamp_futures_buy=0.00002,
        stamp_options_buy=0.00003,
        exchange_txn_cash=0.0000297,
        exchange_txn_futures=0.0000173,
        exchange_txn_options=0.000035,
        sebi_turnover_fee=0.000001,
        gst=0.18,
        note=(
            "Earliest known F&O rates, used as the floor of the backtest window. "
            "Exercise on NOTIONAL - the STT trap era."
        ),
    ),
    RateSet(
        effective_from=date(2019, 9, 1),
        stt_delivery=0.001,
        stt_intraday_sell=0.00025,
        stt_futures_sell=0.000125,
        stt_options_premium_sell=0.000625,
        stt_options_exercise=0.00125,
        exercise_basis=ExerciseBasis.INTRINSIC,
        stamp_delivery_buy=0.00015,
        stamp_intraday_buy=0.00003,
        stamp_futures_buy=0.00002,
        stamp_options_buy=0.00003,
        exchange_txn_cash=0.0000297,
        exchange_txn_futures=0.0000173,
        exchange_txn_options=0.000035,
        sebi_turnover_fee=0.000001,
        gst=0.18,
        note="Exercise basis moves from notional to intrinsic value. Rates unchanged.",
    ),
    RateSet(
        effective_from=date(2024, 10, 1),
        stt_delivery=0.001,
        stt_intraday_sell=0.00025,
        stt_futures_sell=0.0002,
        stt_options_premium_sell=0.001,
        stt_options_exercise=0.00125,
        exercise_basis=ExerciseBasis.INTRINSIC,
        stamp_delivery_buy=0.00015,
        stamp_intraday_buy=0.00003,
        stamp_futures_buy=0.00002,
        stamp_options_buy=0.00003,
        exchange_txn_cash=0.0000297,
        exchange_txn_futures=0.0000173,
        exchange_txn_options=0.000035,
        sebi_turnover_fee=0.000001,
        gst=0.18,
        note="Budget 2024: futures 0.0125% -> 0.02%, options premium 0.0625% -> 0.10%.",
    ),
    RateSet(
        effective_from=date(2026, 4, 1),
        stt_delivery=0.001,
        stt_intraday_sell=0.00025,
        stt_futures_sell=0.0005,
        stt_options_premium_sell=0.0015,
        stt_options_exercise=0.0015,
        exercise_basis=ExerciseBasis.INTRINSIC,
        stamp_delivery_buy=0.00015,
        stamp_intraday_buy=0.00003,
        stamp_futures_buy=0.00002,
        stamp_options_buy=0.00003,
        exchange_txn_cash=0.0000297,
        exchange_txn_futures=0.0000173,
        exchange_txn_options=0.000035,
        sebi_turnover_fee=0.000001,
        gst=0.18,
        note="Budget 2026: futures -> 0.05%, options premium and exercise -> 0.15%.",
    ),
)


def rates_on(trade_date: date) -> RateSet:
    """The rates in force on `trade_date`.

    Raises rather than falling back to the newest set: a trade before the
    schedule begins would otherwise be costed with rates from years later, and
    silently. An explicit failure is the only safe answer.
    """
    applicable = [r for r in SCHEDULE if r.effective_from <= trade_date]
    if not applicable:
        msg = (
            f"no cost schedule covers {trade_date}; the schedule starts "
            f"{SCHEDULE[0].effective_from}. Costing it with later rates would be silent"
            f" and wrong."
        )
        raise ValueError(msg)
    return applicable[-1]
