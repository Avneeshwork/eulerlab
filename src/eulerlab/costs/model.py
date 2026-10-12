"""What one trade costs, itemised the way a contract note itemises it.

Itemised rather than blended, for two reasons. A single "0.1% round trip"
number is wrong in both directions depending on the instrument — it overstates
a delivery buy, which pays no STT on the buy leg under intraday rules but does
under delivery, and understates an options short. And an itemised breakdown
can be checked line by line against a real contract note, which is the
acceptance test this sprint is meant to pass.

**Sides are modelled, not averaged.** STT on intraday and futures falls only
on the sell leg; stamp duty only on the buy leg; GST only on brokerage plus
transaction charges. Averaging them into one percentage loses the asymmetry,
and the asymmetry is what makes a high-turnover strategy expensive.

Everything is `Decimal`. Contract notes are reconciled to the paisa, and a
float that is out by 1e-9 fails that comparison for reasons that have nothing
to do with the model being right.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from eulerlab.costs.schedule import ExerciseBasis, RateSet, Segment, Side, rates_on

PAISA = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    """To the paisa, half up — the convention contract notes use."""
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Brokerage:
    """A broker's fee structure.

    Configurable rather than hardcoded to Zerodha, because the brokerage is
    the one line here that is a commercial choice rather than a statutory
    rate, and it is also the smallest. Defaults are Zerodha's published
    schedule: free on delivery, and the lesser of 0.03% or ₹20 elsewhere.
    """

    delivery_pct: Decimal = Decimal(0)
    intraday_pct: Decimal = Decimal("0.0003")
    intraday_cap: Decimal = Decimal(20)
    futures_pct: Decimal = Decimal("0.0003")
    futures_cap: Decimal = Decimal(20)
    options_flat: Decimal = Decimal(20)

    def charge(self, segment: Segment, turnover: Decimal) -> Decimal:
        if segment is Segment.EQUITY_DELIVERY:
            return turnover * self.delivery_pct
        if segment is Segment.EQUITY_INTRADAY:
            return min(turnover * self.intraday_pct, self.intraday_cap)
        if segment is Segment.FUTURES:
            return min(turnover * self.futures_pct, self.futures_cap)
        return self.options_flat


@dataclass(frozen=True)
class CostBreakdown:
    """Every line of a contract note, plus the total."""

    brokerage: Decimal
    stt: Decimal
    stamp_duty: Decimal
    exchange_txn: Decimal
    sebi_fee: Decimal
    gst: Decimal
    turnover: Decimal

    @property
    def total(self) -> Decimal:
        return _round(
            self.brokerage
            + self.stt
            + self.stamp_duty
            + self.exchange_txn
            + self.sebi_fee
            + self.gst
        )

    @property
    def bps(self) -> Decimal:
        """Total as basis points of turnover — the number a strategy feels."""
        if self.turnover <= 0:
            return Decimal(0)
        return (self.total / self.turnover) * Decimal(10000)

    def lines(self) -> list[tuple[str, Decimal]]:
        return [
            ("brokerage", self.brokerage),
            ("STT", self.stt),
            ("stamp duty", self.stamp_duty),
            ("exchange txn", self.exchange_txn),
            ("SEBI fee", self.sebi_fee),
            ("GST", self.gst),
        ]


def _stt(
    rates: RateSet, segment: Segment, side: Side, turnover: Decimal, *, fund_unit: bool = False
) -> Decimal:
    """STT, charged only on the sides that actually bear it."""
    if segment is Segment.EQUITY_DELIVERY and fund_unit:
        # An ETF unit is not a share: sale only, at a hundredth of the rate.
        # Charging it the share rate overcharged every ETF round trip by about
        # 0.2% (HISTORY #18).
        if side is not Side.SELL:
            return Decimal(0)
        return turnover * Decimal(str(rates.stt_fund_delivery_sell))
    if segment is Segment.EQUITY_DELIVERY:
        return turnover * Decimal(str(rates.stt_delivery))
    if side is not Side.SELL:
        # Intraday, futures and options premium are all sell-side only. A
        # model that charged both legs would roughly double the STT on every
        # round trip.
        return Decimal(0)
    if segment is Segment.EQUITY_INTRADAY:
        return turnover * Decimal(str(rates.stt_intraday_sell))
    if segment is Segment.FUTURES:
        return turnover * Decimal(str(rates.stt_futures_sell))
    return turnover * Decimal(str(rates.stt_options_premium_sell))


def _stamp(rates: RateSet, segment: Segment, side: Side, turnover: Decimal) -> Decimal:
    """Stamp duty is buy-side only, in every segment."""
    if side is not Side.BUY:
        return Decimal(0)
    rate = {
        Segment.EQUITY_DELIVERY: rates.stamp_delivery_buy,
        Segment.EQUITY_INTRADAY: rates.stamp_intraday_buy,
        Segment.FUTURES: rates.stamp_futures_buy,
        Segment.OPTIONS: rates.stamp_options_buy,
    }[segment]
    return turnover * Decimal(str(rate))


def _exchange(rates: RateSet, segment: Segment, turnover: Decimal) -> Decimal:
    rate = {
        Segment.EQUITY_DELIVERY: rates.exchange_txn_cash,
        Segment.EQUITY_INTRADAY: rates.exchange_txn_cash,
        Segment.FUTURES: rates.exchange_txn_futures,
        Segment.OPTIONS: rates.exchange_txn_options,
    }[segment]
    return turnover * Decimal(str(rate))


def cost_of_trade(
    *,
    trade_date: date,
    segment: Segment,
    side: Side,
    price: Decimal,
    quantity: int,
    brokerage: Brokerage | None = None,
    fund_unit: bool = False,
) -> CostBreakdown:
    """Cost one leg of one trade, at the rates in force on `trade_date`.

    For options, `price` is the **premium**, not the strike or the underlying
    — every statutory charge on an option trade is levied on premium turnover.
    Exercise is a different event with a different base; see `cost_of_exercise`.

    `fund_unit` marks a unit of an equity-oriented fund (an ETF), which pays a
    different STT from a share.
    """
    fees = brokerage or Brokerage()
    rates = rates_on(trade_date)
    turnover = price * Decimal(quantity)

    broker = fees.charge(segment, turnover)
    exchange = _exchange(rates, segment, turnover)
    # GST falls on brokerage plus transaction charges, never on turnover.
    # Applying 18% to turnover overstates the cost by three orders of
    # magnitude, which is the single easiest way to build a cost model that
    # rejects every strategy.
    gst = (broker + exchange) * Decimal(str(rates.gst))

    return CostBreakdown(
        brokerage=_round(broker),
        stt=_round(_stt(rates, segment, side, turnover, fund_unit=fund_unit)),
        stamp_duty=_round(_stamp(rates, segment, side, turnover)),
        exchange_txn=_round(exchange),
        sebi_fee=_round(turnover * Decimal(str(rates.sebi_turnover_fee))),
        gst=_round(gst),
        turnover=turnover,
    )


def cost_of_exercise(
    *,
    trade_date: date,
    settlement_price: Decimal,
    strike: Decimal,
    quantity: int,
    is_call: bool = True,
) -> CostBreakdown:
    """STT on an exercised option — the charge that has bankrupted expiries.

    The base is time-versioned and the difference is enormous. Until
    2019-08-31 the charge fell on the **full notional** settlement value; from
    2019-09-01 it falls on **intrinsic value** only. On Zerodha's worked
    example — 50 units, strike 17,300, settlement 17,350 — the intrinsic rule
    costs ₹4 and the notional rule ₹1,301, a factor of 325.

    That is why an in-the-money option was often worth *abandoning* before
    2019: exercising it cost more than the money it was in by. A backtest of a
    2015-2019 options strategy that ignores this overstates returns on every
    expiry it holds through.
    """
    rates = rates_on(trade_date)
    intrinsic_per_unit = (
        max(settlement_price - strike, Decimal(0))
        if is_call
        else max(strike - settlement_price, Decimal(0))
    )
    base = (
        settlement_price * Decimal(quantity)
        if rates.exercise_basis is ExerciseBasis.NOTIONAL
        else intrinsic_per_unit * Decimal(quantity)
    )
    stt = base * Decimal(str(rates.stt_options_exercise))

    return CostBreakdown(
        brokerage=Decimal(0),
        stt=_round(stt),
        stamp_duty=Decimal(0),
        exchange_txn=Decimal(0),
        sebi_fee=Decimal(0),
        gst=Decimal(0),
        turnover=base,
    )


def round_trip(
    *,
    trade_date: date,
    segment: Segment,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: int,
    brokerage: Brokerage | None = None,
) -> CostBreakdown:
    """Both legs of a position, summed.

    The number a strategy actually pays. Kept separate from `cost_of_trade`
    rather than doubling it, because the two legs are not symmetric: the buy
    pays stamp duty and the sell pays STT.
    """
    buy = cost_of_trade(
        trade_date=trade_date,
        segment=segment,
        side=Side.BUY,
        price=entry_price,
        quantity=quantity,
        brokerage=brokerage,
    )
    sell = cost_of_trade(
        trade_date=trade_date,
        segment=segment,
        side=Side.SELL,
        price=exit_price,
        quantity=quantity,
        brokerage=brokerage,
    )
    return CostBreakdown(
        brokerage=buy.brokerage + sell.brokerage,
        stt=buy.stt + sell.stt,
        stamp_duty=buy.stamp_duty + sell.stamp_duty,
        exchange_txn=buy.exchange_txn + sell.exchange_txn,
        sebi_fee=buy.sebi_fee + sell.sebi_fee,
        gst=buy.gst + sell.gst,
        turnover=buy.turnover + sell.turnover,
    )
