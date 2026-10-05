"""Chain analytics: max pain, put-call ratio, the smile, the surface, gamma.

Every function here is a view over one `Chain` or a few of them. Nothing
fetches, nothing caches, and nothing decides what a number means — that is the
caller's job, and keeping it out of here is what lets the same code serve the
API, a notebook and a quality command without three versions drifting apart.

**What this module cannot do, and why it matters.** The chain it reads comes
from the F&O bhavcopy, which is end of day. There is no intraday chain
recorder (the capability matrix says so), so anything whose meaning depends on
*when* during the session it was measured — a live OI tracker, an intraday
straddle roll, a PnL simulator with a trade log — cannot be built on this data
and is not attempted here. A daily series of those is a different quantity
wearing the same name.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from eulerlab.master.derivatives import Right
from eulerlab.options.chain import Chain, Quote
from eulerlab.options.iv import Greeks, greeks, implied_vol


@dataclass(frozen=True)
class StrikeRow:
    """One strike, both rights, with everything derived from it."""

    strike: float
    call: Quote | None
    put: Quote | None
    call_iv: float | None
    put_iv: float | None
    call_greeks: Greeks | None
    put_greeks: Greeks | None

    @property
    def call_traded(self) -> bool:
        return bool(self.call and self.call.traded)

    @property
    def put_traded(self) -> bool:
        return bool(self.put and self.put.traded)


def enrich(chain: Chain, *, forward: float, discount: float, years: float) -> list[StrikeRow]:
    """Solve vol and Greeks for every strike in a chain.

    Done once and shared, because six of the tools below need the same
    per-strike vol and Greeks, and solving them six times would be six chances
    for one of them to use a different forward.
    """
    rows: list[StrikeRow] = []
    for strike in chain.strikes:
        call, put = chain.calls.get(strike), chain.puts.get(strike)
        at = float(strike)

        def solve(
            quote: Quote | None, right: Right, k: float = at
        ) -> tuple[float | None, Greeks | None]:
            if quote is None or quote.price <= 0 or years <= 0 or forward <= 0:
                return None, None
            vol = implied_vol(
                price=quote.price,
                forward=forward,
                strike=k,
                years=years,
                discount=discount,
                right=right,
            )
            if vol is None or vol <= 0:
                return None, None
            return vol, greeks(
                forward=forward,
                strike=k,
                years=years,
                vol=vol,
                discount=discount,
                right=right,
            )

        call_iv, call_greeks = solve(call, Right.CALL)
        put_iv, put_greeks = solve(put, Right.PUT)
        rows.append(
            StrikeRow(
                strike=at,
                call=call,
                put=put,
                call_iv=call_iv,
                put_iv=put_iv,
                call_greeks=call_greeks,
                put_greeks=put_greeks,
            )
        )
    return rows


# --- max pain ---------------------------------------------------------------


@dataclass(frozen=True)
class MaxPain:
    strike: float
    payout: float
    """Total intrinsic owed to option holders if settlement were at `strike`."""

    curve: list[tuple[float, float]]
    """(settlement, payout) across every listed strike, so the shape is
    visible. The minimum alone hides how flat or sharp it is, and a flat curve
    means the single number is close to meaningless."""


def max_pain(chain: Chain) -> MaxPain | None:
    """The settlement that would pay option holders least.

    A descriptive statistic about open interest, **not** a forecast. It is
    often presented as where price "will" settle, which requires believing
    writers can move spot and that current OI is their final position. Neither
    is established here, and the name is kept only because it is what everyone
    searches for.
    """
    # The union of call and put strikes, not `chain.strikes`, which is the
    # *paired* set. Pairing is right for parity and butterfly checks, which
    # need both legs — and wrong here: a call-only strike still carries open
    # interest its writers owe on, and dropping it understates the payout at
    # every settlement above it. A test with three call strikes and one put
    # caught this returning a one-point curve.
    strikes = sorted({*chain.calls, *chain.puts})
    if not strikes:
        return None

    curve: list[tuple[float, float]] = []
    for settle in strikes:
        total = 0.0
        for strike in strikes:
            call, put = chain.calls.get(strike), chain.puts.get(strike)
            if call is not None and settle > strike:
                total += call.open_interest * float(settle - strike)
            if put is not None and settle < strike:
                total += put.open_interest * float(strike - settle)
        curve.append((float(settle), total))

    best = min(curve, key=lambda point: point[1])
    return MaxPain(strike=best[0], payout=best[1], curve=curve)


# --- put-call ratio ---------------------------------------------------------


@dataclass(frozen=True)
class PutCallRatio:
    by_open_interest: float | None
    by_volume: float | None
    call_open_interest: float
    put_open_interest: float
    call_volume: float
    put_volume: float


def put_call_ratio(chain: Chain) -> PutCallRatio:
    """Put over call, by open interest and by volume, kept separate.

    They answer different questions — OI is positions held, volume is
    positions traded today — and averaging or quoting one as "the PCR" is how
    a quiet day with heavy existing positioning reads as a busy one.
    """
    call_oi = sum(q.open_interest for q in chain.calls.values())
    put_oi = sum(q.open_interest for q in chain.puts.values())
    call_vol = sum(q.volume for q in chain.calls.values())
    put_vol = sum(q.volume for q in chain.puts.values())
    return PutCallRatio(
        by_open_interest=(put_oi / call_oi) if call_oi > 0 else None,
        by_volume=(put_vol / call_vol) if call_vol > 0 else None,
        call_open_interest=call_oi,
        put_open_interest=put_oi,
        call_volume=call_vol,
        put_volume=put_vol,
    )


# --- gamma exposure ---------------------------------------------------------


@dataclass(frozen=True)
class GammaPoint:
    strike: float
    gamma_exposure: float
    call_gamma: float
    put_gamma: float


@dataclass(frozen=True)
class GammaProfile:
    points: list[GammaPoint]
    total: float
    flip: float | None
    """Where cumulative exposure crosses zero, if it does."""

    convention: str


def gamma_exposure(rows: list[StrikeRow], *, forward: float) -> GammaProfile:
    """Gamma times open interest, per strike.

    **The sign convention is an assumption, and it is not observable.** The
    usual construction assumes dealers are long calls and short puts, so call
    gamma adds and put gamma subtracts. Whether that holds on any given day is
    a claim about who is on the other side of the open interest, and the
    bhavcopy does not say. The number is reported with the assumption named
    rather than folded in silently, because a gamma profile whose sign is
    wrong points support and resistance at exactly the wrong strikes.
    """
    points: list[GammaPoint] = []
    for row in rows:
        call_gamma = (
            row.call_greeks.gamma * row.call.open_interest if row.call_greeks and row.call else 0.0
        )
        put_gamma = (
            row.put_greeks.gamma * row.put.open_interest if row.put_greeks and row.put else 0.0
        )
        scale = forward * forward * 0.01
        points.append(
            GammaPoint(
                strike=row.strike,
                gamma_exposure=(call_gamma - put_gamma) * scale,
                call_gamma=call_gamma * scale,
                put_gamma=put_gamma * scale,
            )
        )

    total = sum(p.gamma_exposure for p in points)

    flip: float | None = None
    running = 0.0
    for point in points:
        previous = running
        running += point.gamma_exposure
        if previous <= 0 < running or previous >= 0 > running:
            flip = point.strike
            break

    return GammaProfile(
        points=points,
        total=total,
        flip=flip,
        convention="dealers assumed long calls and short puts; not observable from bhavcopy",
    )


# --- the smile and the surface ---------------------------------------------


@dataclass(frozen=True)
class SmilePoint:
    strike: float
    moneyness: float
    """log(K/F). Zero at the money, so skew is read off the sign."""

    call_iv: float | None
    put_iv: float | None


def smile(rows: list[StrikeRow], *, forward: float) -> list[SmilePoint]:
    """Implied vol by strike, with both rights kept apart.

    Not blended into one curve. Call and put vol at the same strike should
    agree under parity, so the *gap between them* is a data-quality reading —
    averaging them throws away the one diagnostic the pair provides.
    """
    import math

    out: list[SmilePoint] = []
    for row in rows:
        if row.call_iv is None and row.put_iv is None:
            continue
        out.append(
            SmilePoint(
                strike=row.strike,
                moneyness=math.log(row.strike / forward) if forward > 0 else 0.0,
                call_iv=row.call_iv,
                put_iv=row.put_iv,
            )
        )
    return out


def atm_strike(strikes: list[Decimal] | list[float], forward: float) -> float | None:
    """The listed strike nearest the forward."""
    values = [float(s) for s in strikes]
    if not values or forward <= 0:
        return None
    return min(values, key=lambda s: abs(s - forward))
