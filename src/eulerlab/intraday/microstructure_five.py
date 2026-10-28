"""Fixed microstructure strategy rules and a no-download data readiness audit.

The five rules are deliberately separated from their source-data adapters. The
NSE order/trade archive is not a candle feed: event-time replay must be built
from its full CM order and trade records, and the trial files are not present
in this checkout. The audit therefore refuses to print pretend backtest
results. Signal builders below accept normalized frames once lawful data is
available; all joins are on EulerLab instrument IDs.

Run the readiness audit with ``uv run python -m
eulerlab.intraday.microstructure_five``. It does not download market data.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from eulerlab.costs.router import fill_cost
from eulerlab.costs.schedule import Segment, Side

IST = ZoneInfo("Asia/Kolkata")
DATA_ROOT = Path("data/landing")
DEFAULT_INPUT = DATA_ROOT / "microstructure_normalized"
CAPITAL = 1_000_000.0
NOTIONAL = 100_000.0
SLIPPAGE_BPS = 2.0
ENTRY_DELAY = timedelta(seconds=1)


class RuleSpec(BaseModel):
    """A frozen rule, including whether it is a source replication or proxy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    source_url: str
    rule: str
    input_files: tuple[str, ...]
    adaptation: bool


RULES: tuple[RuleSpec, ...] = (
    RuleSpec(
        id="micro-01",
        name="Repeated institutional half-hour flow",
        source_url="https://onlinelibrary.wiley.com/doi/10.1111/jfir.12131",
        rule=(
            "For each instrument and half-hour, follow the same stable institution's net order-"
            "submission direction when it repeats on at least two of the previous three sessions; "
            "enter at the next session's first executable quote in that half-hour and exit at its end."
        ),
        input_files=("orders.parquet", "quotes.parquet", "instrument_map.parquet"),
        adaptation=False,
    ),
    RuleSpec(
        id="micro-02",
        name="Algorithm-side timing proxy",
        source_url="https://doi.org/10.1016/j.ribaf.2020.101283",
        rule=(
            "For trailing 1- and 5-minute windows, compute algorithm-tagged buyer notional minus "
            "algorithm-tagged seller notional divided by total notional; trade the sign above 0.20 "
            "at the next quote and exit after the matching 1- or 5-minute horizon."
        ),
        input_files=("trades.parquet", "quotes.parquet", "instrument_map.parquet"),
        adaptation=True,
    ),
    RuleSpec(
        id="micro-03",
        name="Aggressor-signed order-flow imbalance",
        source_url="https://www.sciencedirect.com/science/article/pii/S1544612320316779",
        rule=(
            "Over the trailing five minutes, compute signed aggressor volume divided by total volume; "
            "trade in its direction when absolute imbalance is at least 0.20, enter at the next quote, "
            "and exit one minute later."
        ),
        input_files=(
            "orders.parquet",
            "trades.parquet",
            "quotes.parquet",
            "instrument_map.parquet",
        ),
        adaptation=True,
    ),
    RuleSpec(
        id="micro-04",
        name="Five-level limit-book pressure",
        source_url="https://doaj.org/article/f889de21e919474daf8c846021452ece",
        rule=(
            "Compute top-five-level size imbalance with level weights 1/k; trade when its absolute "
            "value is at least 0.20, cross the next observed best quote, and exit one minute later."
        ),
        input_files=("orders.parquet", "quotes.parquet", "instrument_map.parquet"),
        adaptation=True,
    ),
    RuleSpec(
        id="micro-05",
        name="Single-stock futures lead cash",
        source_url="https://irgu.unigoa.ac.in/drs/handle/unigoa/6287",
        rule=(
            "When the front contract's completed one-minute return is at least 5 bp in absolute "
            "value and its strictly prior 60-session one-minute lead correlation with the cash "
            "share is positive, enter cash at the next minute open and exit five minutes later; "
            "use date-valid contract-to-underlying IDs and do not stitch expiries."
        ),
        input_files=("bars.parquet", "instrument_map.parquet"),
        adaptation=True,
    ),
)


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str
    instrument_id: str = Field(min_length=1)
    signal_time: datetime
    exit_time: datetime
    side: Literal[-1, 1]

    @field_validator("signal_time", "exit_time")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value


@dataclass(frozen=True)
class BacktestFill:
    strategy_id: str
    instrument_id: str
    session: date
    entry_time: datetime
    exit_time: datetime
    side: int
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    fees: float
    net_pnl: float


def _require(frame: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required fields: {', '.join(missing)}")


def _aware_times(frame: pd.DataFrame, column: str, name: str) -> pd.Series:
    parsed = pd.to_datetime(frame[column], errors="raise")
    if parsed.dt.tz is None:
        raise ValueError(f"{name}.{column} must contain timezone-aware timestamps")
    return parsed.dt.tz_convert(IST)


def _calendar_slot(stamp: datetime, minutes: int = 30) -> tuple[date, int, datetime, datetime]:
    local = stamp.astimezone(IST)
    market_open = datetime.combine(local.date(), time(9, 15), IST)
    offset = int((local - market_open).total_seconds() // (60 * minutes))
    start = market_open + timedelta(minutes=offset * minutes)
    return local.date(), offset, start, start + timedelta(minutes=minutes)


def repeated_institution_signals(
    orders: pd.DataFrame, *, repetition: int = 2, lookback_sessions: int = 3
) -> list[Signal]:
    """Build the exact-identity rule; NSE's published file has no institution ID.

    Expected order columns: event_time, instrument_id, institution_id, side,
    action, quantity. Missing IDs are a hard blocker, never replaced with a
    symbol or client-category guess.
    """
    _require(
        orders,
        ("event_time", "instrument_id", "institution_id", "side", "action", "quantity"),
        "orders",
    )
    if orders["institution_id"].isna().any():
        raise ValueError("micro-01 requires a stable institution_id absent from the NSE schema")
    rows = orders.copy()
    rows["event_time"] = _aware_times(rows, "event_time", "orders")
    rows = rows.loc[rows["action"].eq("entry")].copy()
    slots = rows["event_time"].map(lambda x: _calendar_slot(x.to_pydatetime()))
    rows["session"] = slots.map(lambda values: values[0])
    rows["slot"] = slots.map(lambda values: values[1])
    rows["bucket_start"] = slots.map(lambda values: values[2])
    rows["bucket_end"] = slots.map(lambda values: values[3])
    rows["signed_qty"] = rows["quantity"].astype(float) * rows["side"].map({"B": 1, "S": -1})
    flow = (
        rows.groupby(["instrument_id", "institution_id", "session", "slot"], sort=True)
        .agg(
            signed_qty=("signed_qty", "sum"),
            bucket_start=("bucket_start", "first"),
            bucket_end=("bucket_end", "first"),
        )
        .reset_index()
    )
    signals: list[Signal] = []
    sessions = sorted(flow["session"].unique())
    for position in range(lookback_sessions, len(sessions)):
        session = sessions[position]
        previous = sessions[position - lookback_sessions : position]
        prior = flow.loc[flow["session"].isin(previous)]
        prior = prior.loc[prior["signed_qty"].ne(0)]
        keys = ("instrument_id", "institution_id", "slot")
        for key, group in prior.groupby(list(keys), sort=True):
            counts = group["signed_qty"].map(lambda value: 1 if value > 0 else -1).value_counts()
            if not len(counts) or int(counts.max()) < repetition:
                continue
            direction = 1 if counts.get(1, 0) >= counts.get(-1, 0) else -1
            instrument_id, institution_id, slot = cast(tuple[Any, Any, Any], key)
            current = flow.loc[
                flow["session"].eq(session)
                & flow["instrument_id"].eq(instrument_id)
                & flow["institution_id"].eq(institution_id)
                & flow["slot"].eq(slot)
            ]
            if current.empty:
                continue
            start = current.iloc[0]["bucket_start"].to_pydatetime()
            end = current.iloc[0]["bucket_end"].to_pydatetime()
            signals.append(
                Signal(
                    strategy_id="micro-01",
                    instrument_id=str(instrument_id),
                    signal_time=start,
                    exit_time=end,
                    side=direction,
                )
            )
    return signals


def signed_trade_signals(
    trades: pd.DataFrame,
    *,
    strategy_id: str,
    window: timedelta,
    hold: timedelta,
    signal_column: str,
    threshold: float = 0.20,
) -> list[Signal]:
    """Make a non-overlapping-window flow signal from a causal event window."""
    _require(
        trades,
        ("event_time", "instrument_id", "trade_qty"),
        "trades",
    )
    rows = trades.copy()
    rows["event_time"] = _aware_times(rows, "event_time", "trades")
    if signal_column == "algo_signed_notional":
        _require(rows, ("buyer_algo", "seller_algo"), "trades")
        buy_algo = rows["buyer_algo"].isin((0, 2))
        sell_algo = rows["seller_algo"].isin((0, 2))
        _require(rows, ("trade_price",), "trades")
        weight = rows["trade_qty"].astype(float) * rows["trade_price"].astype(float)
        rows["signed_qty"] = weight * (buy_algo.astype(int) - sell_algo.astype(int))
        rows["total_weight"] = weight
    elif signal_column == "aggressor_signed_qty":
        _require(rows, ("aggressor_side",), "trades")
        rows["signed_qty"] = rows["trade_qty"].astype(float) * rows["aggressor_side"].map(
            {"B": 1, "S": -1}
        )
        rows["total_weight"] = rows["trade_qty"].astype(float)
    else:
        raise ValueError(f"unknown signed flow {signal_column!r}")
    rows["signed_qty"] = rows["signed_qty"].fillna(0.0)
    rows["total_weight"] = rows["total_weight"].fillna(0.0)
    rows = rows.sort_values(["instrument_id", "event_time"], kind="stable")
    signals: list[Signal] = []
    for instrument_id, group in rows.groupby("instrument_id", sort=True):
        times = group["event_time"].tolist()
        signed = group["signed_qty"].tolist()
        volume = group["total_weight"].astype(float).tolist()
        left = 0
        last_signal: datetime | None = None
        for index, stamp in enumerate(times):
            while left < index and stamp - times[left] > window:
                left += 1
            total = sum(volume[left:index])
            if total <= 0:
                continue
            imbalance = sum(signed[left:index]) / total
            signal_time = stamp.to_pydatetime()
            if last_signal is not None and signal_time < last_signal + hold:
                continue
            if abs(imbalance) < threshold:
                continue
            signals.append(
                Signal(
                    strategy_id=strategy_id,
                    instrument_id=str(instrument_id),
                    signal_time=signal_time,
                    exit_time=signal_time + hold,
                    side=1 if imbalance > 0 else -1,
                )
            )
            last_signal = signal_time
    return signals


def book_pressure_signals(
    quotes: pd.DataFrame,
    *,
    threshold: float = 0.20,
    hold: timedelta = timedelta(minutes=1),
) -> list[Signal]:
    """Trade weighted top-five displayed size imbalance at sampled snapshots."""
    fields = ["event_time", "instrument_id"]
    for level in range(1, 6):
        fields.extend((f"bid_qty_{level}", f"ask_qty_{level}"))
    _require(quotes, fields, "quotes")
    rows = quotes.copy()
    rows["event_time"] = _aware_times(rows, "event_time", "quotes")
    weights = [1 / level for level in range(1, 6)]
    bid_pressure = pd.Series(0.0, index=rows.index)
    ask_pressure = pd.Series(0.0, index=rows.index)
    for level, weight in enumerate(weights, start=1):
        bid_pressure = bid_pressure.add(rows[f"bid_qty_{level}"].astype(float) * weight)
        ask_pressure = ask_pressure.add(rows[f"ask_qty_{level}"].astype(float) * weight)
    total = bid_pressure.add(ask_pressure)
    rows["imbalance"] = bid_pressure.sub(ask_pressure).div(total.mask(total.eq(0)))
    signals: list[Signal] = []
    found = cast(
        list[dict[str, Any]],
        rows.loc[
            rows["imbalance"].abs().ge(threshold), ["event_time", "instrument_id", "imbalance"]
        ].to_dict(orient="records"),
    )
    for row in found:
        stamp = pd.Timestamp(row["event_time"])
        imbalance = float(row["imbalance"])
        signals.append(
            Signal(
                strategy_id="micro-04",
                instrument_id=str(row["instrument_id"]),
                signal_time=stamp.to_pydatetime(),
                exit_time=(stamp + hold).to_pydatetime(),
                side=1 if imbalance > 0 else -1,
            )
        )
    return signals


def futures_cash_signals(
    bars: pd.DataFrame,
    *,
    min_return: float = 0.0005,
    hold_minutes: int = 5,
) -> list[Signal]:
    """Use front-future returns and strictly prior 60-session lead correlation.

    Futures returns are calculated within contract and session, so overnight
    gaps and expiry rolls never enter the one-minute return. At each timestamp
    the nearest-expiry contract is selected. The correlation uses paired
    future/cash minute returns only from the previous 60 cash sessions, never
    from the current session.
    """
    _require(
        bars,
        (
            "event_time",
            "instrument_id",
            "instrument_kind",
            "underlying_instrument_id",
            "contract_id",
            "expiry",
            "open",
            "close",
        ),
        "bars",
    )
    rows = bars.copy()
    rows["event_time"] = _aware_times(rows, "event_time", "bars")
    rows["session"] = rows["event_time"].dt.date
    rows["expiry_date"] = pd.to_datetime(rows["expiry"], errors="raise").dt.date
    futures = rows.loc[rows["instrument_kind"].eq("stock_future")].copy()
    cash = rows.loc[rows["instrument_kind"].eq("cash")].copy()
    signals: list[Signal] = []
    if futures.empty or cash.empty:
        return signals

    futures = futures.drop_duplicates(["contract_id", "event_time"], keep="last")
    futures = futures.sort_values(["contract_id", "event_time"], kind="stable")
    futures["previous_close"] = futures.groupby(["contract_id", "session"], sort=False)[
        "close"
    ].shift()
    futures["previous_event_time"] = futures.groupby(["contract_id", "session"], sort=False)[
        "event_time"
    ].shift()
    futures["future_return"] = (
        futures["close"].astype(float).div(futures["previous_close"].astype(float)).sub(1)
    )
    futures["future_return"] = futures["future_return"].where(
        futures["event_time"].sub(futures["previous_event_time"]).eq(pd.Timedelta(minutes=1))
    )
    futures = futures.loc[futures["expiry_date"].ge(futures["session"])].copy()
    cash_groups = {
        str(instrument_id): group.sort_values("event_time", kind="stable").copy()
        for instrument_id, group in cash.groupby("instrument_id", sort=True)
    }

    for underlying_id, contracts in futures.groupby("underlying_instrument_id", sort=True):
        underlying = cash_groups.get(str(underlying_id))
        if underlying is None:
            continue
        underlying["previous_cash_close"] = underlying.groupby("session", sort=False)[
            "close"
        ].shift()
        underlying["previous_cash_time"] = underlying.groupby("session", sort=False)[
            "event_time"
        ].shift()
        underlying["cash_return"] = (
            underlying["close"]
            .astype(float)
            .div(underlying["previous_cash_close"].astype(float))
            .sub(1)
        )
        underlying["cash_return"] = underlying["cash_return"].where(
            underlying["event_time"]
            .sub(underlying["previous_cash_time"])
            .eq(pd.Timedelta(minutes=1))
        )
        cash_returns: dict[pd.Timestamp, float] = {}
        cash_times_by_session: dict[date, list[pd.Timestamp]] = defaultdict(list)
        for stamp_value, session, return_value in zip(
            underlying["event_time"].tolist(),
            underlying["session"].tolist(),
            underlying["cash_return"].tolist(),
            strict=True,
        ):
            stamp = pd.Timestamp(stamp_value)
            cash_times_by_session[session].append(stamp)
            if pd.notna(return_value):
                cash_returns[stamp] = float(return_value)

        # The returns are first calculated in each dated contract. Select the
        # nearest expiry at every minute without calculating a roll return.
        front = contracts.sort_values(["event_time", "expiry_date"], kind="stable")
        front = front.drop_duplicates("event_time", keep="first")
        paired_by_session: dict[date, list[tuple[float, float]]] = defaultdict(list)
        for stamp_value, session, future_return in zip(
            front["event_time"].tolist(),
            front["session"].tolist(),
            front["future_return"].tolist(),
            strict=True,
        ):
            next_cash_return = cash_returns.get(pd.Timestamp(stamp_value) + pd.Timedelta(minutes=1))
            if pd.notna(future_return) and next_cash_return is not None:
                paired_by_session[session].append((float(future_return), next_cash_return))

        sessions = sorted(cash_times_by_session)
        front_by_session = dict(front.groupby("session", sort=True))
        for position in range(60, len(sessions)):
            session = sessions[position]
            prior_sessions = sessions[position - 60 : position]
            paired = [
                pair
                for prior_session in prior_sessions
                for pair in paired_by_session.get(prior_session, [])
            ]
            if len(paired) < 500:
                continue
            lead_correlation = pd.Series([pair[0] for pair in paired]).corr(
                pd.Series([pair[1] for pair in paired])
            )
            if pd.isna(lead_correlation) or float(lead_correlation) <= 0:
                continue

            current = front_by_session.get(session)
            if current is None:
                continue
            cash_times = cash_times_by_session[session]
            for row in cast(list[dict[str, Any]], current.to_dict(orient="records")):
                future_return = row["future_return"]
                if pd.isna(future_return) or abs(float(future_return)) < min_return:
                    continue
                stamp = pd.Timestamp(row["event_time"])
                signal_time = stamp.to_pydatetime() + timedelta(minutes=1)
                exit_time = signal_time + timedelta(minutes=hold_minutes)
                if not any(value.to_pydatetime() >= signal_time for value in cash_times) or not any(
                    value.to_pydatetime() >= exit_time for value in cash_times
                ):
                    continue
                signals.append(
                    Signal(
                        strategy_id="micro-05",
                        instrument_id=str(underlying_id),
                        signal_time=signal_time,
                        exit_time=exit_time,
                        side=1 if float(future_return) > 0 else -1,
                    )
                )
    return signals


def backtest_bar_signals(
    signals: Sequence[Signal],
    bars: pd.DataFrame,
    *,
    notional: float = NOTIONAL,
    slippage_bps: float = SLIPPAGE_BPS,
) -> list[BacktestFill]:
    """Use next cash-bar open and the first close at/after the fixed exit time."""
    _require(bars, ("event_time", "instrument_id", "instrument_kind", "open", "close"), "bars")
    rows = bars.loc[bars["instrument_kind"].eq("cash")].copy()
    rows["event_time"] = _aware_times(rows, "event_time", "bars")
    groups = {
        str(instrument_id): group.sort_values("event_time", kind="stable")
        for instrument_id, group in rows.groupby("instrument_id", sort=True)
    }
    fills: list[BacktestFill] = []
    available_after: dict[str, datetime] = {}
    for signal in sorted(signals, key=lambda item: (item.signal_time, item.instrument_id)):
        last_exit = available_after.get(signal.instrument_id)
        if last_exit is not None and signal.signal_time <= last_exit:
            continue
        group = groups.get(signal.instrument_id)
        if group is None:
            continue
        entry_rows = group.loc[group["event_time"].ge(pd.Timestamp(signal.signal_time))]
        exit_rows = group.loc[group["event_time"].ge(pd.Timestamp(signal.exit_time))]
        if entry_rows.empty or exit_rows.empty:
            continue
        entry, exit_ = entry_rows.iloc[0], exit_rows.iloc[0]
        entry_time, exit_time = (
            entry["event_time"].to_pydatetime(),
            exit_["event_time"].to_pydatetime(),
        )
        if (
            entry_time.astimezone(IST).date() != signal.signal_time.astimezone(IST).date()
            or exit_time.astimezone(IST).date() != entry_time.astimezone(IST).date()
        ):
            continue
        entry_price, exit_price = float(entry["open"]), float(exit_["close"])
        if min(entry_price, exit_price) <= 0:
            continue
        quantity = int(notional // entry_price)
        if quantity <= 0:
            continue
        entry_price *= 1 + slippage_bps * signal.side / 10_000
        exit_price *= 1 - slippage_bps * signal.side / 10_000
        gross = signal.side * (exit_price - entry_price) * quantity
        entry_side = Side.BUY if signal.side > 0 else Side.SELL
        exit_side = Side.SELL if signal.side > 0 else Side.BUY
        day = entry_time.astimezone(IST).date()
        fees = fill_cost(
            venue="equity",
            price=entry_price,
            quantity=quantity,
            side=entry_side,
            day=day,
            segment=Segment.EQUITY_INTRADAY,
        ) + fill_cost(
            venue="equity",
            price=exit_price,
            quantity=quantity,
            side=exit_side,
            day=day,
            segment=Segment.EQUITY_INTRADAY,
        )
        fills.append(
            BacktestFill(
                strategy_id=signal.strategy_id,
                instrument_id=signal.instrument_id,
                session=day,
                entry_time=entry_time,
                exit_time=exit_time,
                side=signal.side,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                gross_pnl=gross,
                fees=fees,
                net_pnl=gross - fees,
            )
        )
        available_after[signal.instrument_id] = exit_time
    return fills


def _quote_at_or_after(
    quote_groups: Mapping[str, pd.DataFrame], instrument_id: str, when: datetime
) -> pd.Series | None:
    group = quote_groups.get(instrument_id)
    if group is None:
        return None
    later = group.loc[group["event_time"].ge(pd.Timestamp(when))]
    return None if later.empty else later.iloc[0]


def backtest_quote_signals(
    signals: Sequence[Signal],
    quotes: pd.DataFrame,
    *,
    notional: float = NOTIONAL,
    slippage_bps: float = 0.0,
) -> list[BacktestFill]:
    """Cross recorded BBO at the next observable quote and include NSE charges."""
    _require(
        quotes,
        ("event_time", "instrument_id", "bid_px_1", "ask_px_1"),
        "quotes",
    )
    rows = quotes.copy()
    rows["event_time"] = _aware_times(rows, "event_time", "quotes")
    groups = {
        str(instrument_id): group.sort_values("event_time", kind="stable")
        for instrument_id, group in rows.groupby("instrument_id", sort=True)
    }
    fills: list[BacktestFill] = []
    available_after: dict[str, datetime] = {}
    for signal in sorted(signals, key=lambda item: (item.signal_time, item.instrument_id)):
        earliest = signal.signal_time + ENTRY_DELAY
        if earliest < available_after.get(signal.instrument_id, earliest):
            continue
        entry = _quote_at_or_after(groups, signal.instrument_id, earliest)
        exit_quote = _quote_at_or_after(groups, signal.instrument_id, signal.exit_time)
        if entry is None or exit_quote is None:
            continue
        entry_stamp = entry["event_time"].to_pydatetime()
        exit_stamp = exit_quote["event_time"].to_pydatetime()
        if (
            entry_stamp.astimezone(IST).date() != signal.signal_time.astimezone(IST).date()
            or exit_stamp.astimezone(IST).date() != entry_stamp.astimezone(IST).date()
        ):
            continue
        entry_price = float(entry["ask_px_1"] if signal.side > 0 else entry["bid_px_1"])
        exit_price = float(exit_quote["bid_px_1"] if signal.side > 0 else exit_quote["ask_px_1"])
        if not math.isfinite(entry_price + exit_price) or min(entry_price, exit_price) <= 0:
            continue
        quantity = int(notional // entry_price)
        if quantity <= 0:
            continue
        # A touch-only simulation is conservative about crossing the spread but
        # optimistic about depth/impact; the explicit slippage parameter remains.
        entry_price *= 1 + (slippage_bps / 10_000) * signal.side
        exit_price *= 1 - (slippage_bps / 10_000) * signal.side
        gross = signal.side * (exit_price - entry_price) * quantity
        entry_side = Side.BUY if signal.side > 0 else Side.SELL
        exit_side = Side.SELL if signal.side > 0 else Side.BUY
        day = entry_stamp.astimezone(IST).date()
        fees = fill_cost(
            venue="equity",
            price=entry_price,
            quantity=quantity,
            side=entry_side,
            day=day,
            segment=Segment.EQUITY_INTRADAY,
        ) + fill_cost(
            venue="equity",
            price=exit_price,
            quantity=quantity,
            side=exit_side,
            day=day,
            segment=Segment.EQUITY_INTRADAY,
        )
        fills.append(
            BacktestFill(
                strategy_id=signal.strategy_id,
                instrument_id=signal.instrument_id,
                session=day,
                entry_time=entry_stamp,
                exit_time=exit_stamp,
                side=signal.side,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                gross_pnl=gross,
                fees=fees,
                net_pnl=gross - fees,
            )
        )
        available_after[signal.instrument_id] = exit_stamp
    return fills


def summarize(fills: Sequence[BacktestFill], calendar: Iterable[date]) -> dict[str, Any]:
    by_day: dict[date, float] = defaultdict(float)
    gross_by_day: dict[date, float] = defaultdict(float)
    for fill in fills:
        by_day[fill.session] += fill.net_pnl / CAPITAL
        gross_by_day[fill.session] += fill.gross_pnl / CAPITAL
    sessions = sorted(set(calendar))
    returns = [by_day[day] for day in sessions]
    gross_returns = [gross_by_day[day] for day in sessions]
    mean = statistics.fmean(returns) if returns else 0.0
    deviation = statistics.stdev(returns) if len(returns) > 1 else 0.0
    gross_mean = statistics.fmean(gross_returns) if gross_returns else 0.0
    gross_deviation = statistics.stdev(gross_returns) if len(gross_returns) > 1 else 0.0
    equity = peak = 1.0
    gross_equity = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    for value in gross_returns:
        gross_equity *= 1 + value
    return {
        "trades": len(fills),
        "sessions": len(returns),
        "total_return_gross": round(gross_equity - 1, 6),
        "sharpe_gross": round(gross_mean / gross_deviation * math.sqrt(252), 3)
        if gross_deviation
        else None,
        "total_return_net": round(equity - 1, 6),
        "sharpe_net": round(mean / deviation * math.sqrt(252), 3) if deviation else None,
        "max_drawdown_net": round(max_drawdown, 6),
        "fees_inr": round(sum(fill.fees for fill in fills), 2),
        "calendar_days_include_zero_trade_sessions": True,
        "capital_inr": CAPITAL,
    }


def _local_inventory(root: Path) -> dict[str, Any]:
    nse = root / "nse"
    kite = root / "kite_minute"
    normalized = root / "microstructure_normalized"
    order_files = sorted(nse.rglob("*.DAT.gz")) if nse.exists() else []
    order_files += sorted(nse.rglob("*.dat.gz")) if nse.exists() else []
    cash_minute_files = sorted(kite.glob("*/*.parquet")) if kite.exists() else []
    normalized_files = sorted(normalized.glob("*.parquet")) if normalized.exists() else []
    future_files = [
        path
        for path in cash_minute_files
        if any(token in path.parent.name.upper() for token in ("FUT", "FUTURE"))
    ]
    return {
        "nse_historical_order_trade_files": len(order_files),
        "kite_minute_files": len(cash_minute_files),
        "kite_minute_futures_named_files": len(future_files),
        "normalized_microstructure_files": [path.name for path in normalized_files],
    }


def readiness_report(*, root: Path = DATA_ROOT) -> dict[str, Any]:
    """Report data blockers from landing files without importing or fabricating signals."""
    inventory = _local_inventory(root)
    rules: list[dict[str, Any]] = []
    for spec in RULES:
        reason = "normalized trial data not present"
        if spec.id == "micro-01":
            reason = (
                "no NSE full order/trade files landed; additionally the published NSE schema has "
                "client-category fields but no stable institution/trader identifier"
            )
        elif spec.id in ("micro-02", "micro-03", "micro-04"):
            reason = (
                "no NSE full CM order/trade event files or replayable book snapshots are landed"
            )
        elif spec.id == "micro-05":
            reason = (
                "cash minute bars exist in the archive, but no dated single-stock futures minute "
                "bars or date-valid contract-to-underlying map are landed"
            )
        rules.append(
            {
                **spec.model_dump(),
                "status": "blocked_missing_data",
                "trials_spent": 0,
                "backtest": None,
                "blocker": reason,
            }
        )
    return {
        "as_of": datetime.now(IST).isoformat(timespec="seconds"),
        "data_root": str(root),
        "market_data_downloaded": False,
        "pnl_backtests_run": False,
        "inventory": inventory,
        "strategies": rules,
        "note": (
            "No performance result is reported without the required licensed event or futures data. "
            "The signals are fixed; do not replace missing signed flow or book depth with OHLCV."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="microstructure-five")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = readiness_report(root=args.data_root)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
