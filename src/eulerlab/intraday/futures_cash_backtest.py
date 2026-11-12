"""Fetch, normalize, and backtest the fixed single-stock-future lead rule.

This runner only handles strategy micro-05. The other four strategies need
event-level NSE order, trade, or book data and are not approximated from bars.
Raw FYERS responses stay immutable under ``data/landing``; this module writes
only derived Parquet and JSON under ``data/derived``.

Example bounded pilot (the instrument master currently ends on 2026-08-03)::

    make microstructure-five-futures UNDERLYING=NSE:RELIANCE-EQ \\
      CASH_SYMBOL=RELIANCE FROM=2026-03-01 EVAL_FROM=2026-06-01 TO=2026-08-03
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config, sync_directory
from eulerlab.ingest.fyers_expired_fo import (
    EXPIRED_PREFIX,
    FyersAPIError,
    FyersExpiredFO,
    RawLanding,
    credentials,
)
from eulerlab.intraday.microstructure_five import (
    BacktestFill,
    backtest_bar_signals,
    futures_cash_signals,
    summarize,
)
from eulerlab.intraday.store import fetch as fetch_cash
from eulerlab.paths import data_path

IST = ZoneInfo("Asia/Kolkata")
MASTER_PATH = data_path("master/instruments.jsonl")
DEFAULT_RAW = data_path("landing/fyers_expired_fo")
DEFAULT_OUTPUT = data_path("derived/microstructure_five/micro-05")
DERIVED_ROOT = data_path("derived")


class BacktestConfig(BaseModel):
    """One frozen, no-search evaluation configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    underlying: str = Field(min_length=1)
    cash_symbol: str = Field(min_length=1)
    start: date
    evaluation_start: date
    end: date
    minimum_future_return: float = 0.0005
    correlation_sessions: int = 60
    minimum_paired_returns: int = 500
    hold_minutes: int = 5

    @model_validator(mode="after")
    def validate_dates(self) -> BacktestConfig:
        if self.start >= self.evaluation_start:
            raise ValueError("start must precede evaluation_start to provide warmup data")
        if self.evaluation_start > self.end:
            raise ValueError("evaluation_start must not be after end")
        return self


def _issuer_id(ticker: str, start: date, end: date, master_path: Path) -> str:
    """Resolve one ticker valid for the full range and reject stale masters."""
    if not master_path.is_file():
        raise ValueError(f"Missing point-in-time instrument master: {master_path}")
    lines = master_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("Instrument master is empty")
    stamp = json.loads(lines[0]).get("_stamp", {})
    master_end = date.fromisoformat(str(stamp.get("last_date", "1900-01-01"))[:10])
    if end > master_end:
        raise ValueError(f"Instrument master ends {master_end}; requested end {end} is later")

    matches: list[str] = []
    for line in lines[1:]:
        row = json.loads(line)
        for span in row.get("tickers", []):
            if span.get("value") != ticker:
                continue
            valid_from = date.fromisoformat(str(span["from"])[:10])
            valid_to_value = span.get("to")
            valid_to = date.fromisoformat(str(valid_to_value)[:10]) if valid_to_value else None
            if valid_from <= start and (valid_to is None or valid_to >= end):
                matches.append(str(row["id"]))
    ids = sorted(set(matches))
    if len(ids) != 1:
        raise ValueError(
            f"Expected one master ID for {ticker} valid {start}..{end}; found {len(ids)}"
        )
    return ids[0]


def _timestamp(raw: object) -> datetime:
    if isinstance(raw, (int, float)):
        unit = "ms" if abs(float(raw)) >= 1_000_000_000_000 else "s"
        stamp = pd.Timestamp(raw, unit=unit, tz="UTC")
    else:
        stamp = pd.Timestamp(str(raw))
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize(IST)
    return stamp.tz_convert(IST).to_pydatetime()


def _ohlcv(raw: object) -> tuple[datetime, float, float, float, float, float]:
    if isinstance(raw, dict):
        values = cast(dict[str, Any], raw)
        stamp = values.get("time", values.get("timestamp", values.get("date")))
        fields = cast(
            list[object], [values.get(key) for key in ("open", "high", "low", "close", "volume")]
        )
        if stamp is None or any(value is None for value in fields):
            raise ValueError("FYERS candle object is missing timestamp or OHLCV fields")
        open_, high, low, close, volume = fields
        return (
            _timestamp(stamp),
            float(cast(str | int | float, open_)),
            float(cast(str | int | float, high)),
            float(cast(str | int | float, low)),
            float(cast(str | int | float, close)),
            float(cast(str | int | float, volume)),
        )
    if isinstance(raw, list) and len(raw) >= 6:
        candle_values = cast(list[object], raw)
        stamp, open_, high, low, close, volume = candle_values[:6]
        return (
            _timestamp(stamp),
            float(cast(str | int | float, open_)),
            float(cast(str | int | float, high)),
            float(cast(str | int | float, low)),
            float(cast(str | int | float, close)),
            float(cast(str | int | float, volume)),
        )
    raise ValueError("FYERS returned a candle in an unknown format")


def _contract_expiries(landing: RawLanding, underlying: str) -> dict[str, date]:
    mapping: dict[str, date] = {}
    for entry in landing._entries.values():
        if (
            entry.endpoint != f"{EXPIRED_PREFIX}underlying-symbols"
            or entry.params.get("symbol") != underlying
        ):
            continue
        expiry = date.fromisoformat(entry.params["expiry_date"][:10])
        response = landing.cached(entry.request_id)
        if response is None:
            raise FyersAPIError("A contract discovery response is missing from raw landing")
        contracts = response.get("data", {}).get("contracts", {}).get("futures", [])
        if not isinstance(contracts, list):
            raise FyersAPIError("FYERS contract discovery has an invalid futures list")
        for contract in contracts:
            if not isinstance(contract, str):
                raise FyersAPIError("FYERS returned a non-string future symbol")
            earlier = mapping.get(contract)
            if earlier is not None and earlier != expiry:
                raise FyersAPIError("One FYERS contract symbol maps to multiple expiries")
            mapping[contract] = expiry
    if not mapping:
        raise FyersAPIError("No cached FYERS contract discovery data; run the fetch command first")
    return mapping


def normalize_bars(
    config: BacktestConfig,
    *,
    issuer_id: str,
    landing: RawLanding,
    cash_knowledge_time: datetime,
) -> pd.DataFrame:
    """Build an internal-ID candle table from raw FYERS and archived cash bars."""
    contracts = _contract_expiries(landing, config.underlying)
    future_rows: list[dict[str, Any]] = []
    for entry in landing._entries.values():
        if (
            entry.endpoint != f"{EXPIRED_PREFIX}historical-data"
            or entry.params.get("symbol") not in contracts
        ):
            continue
        response = landing.cached(entry.request_id)
        if response is None:
            raise FyersAPIError("A fetched futures candle response is missing from raw landing")
        external_symbol = entry.params["symbol"]
        expiry = contracts[external_symbol]
        contract_id = hashlib.sha256(
            f"{issuer_id}|stock_future|{expiry.isoformat()}".encode()
        ).hexdigest()[:24]
        candle_rows = response.get("candles", [])
        if not isinstance(candle_rows, list):
            raise FyersAPIError("FYERS candle response has an invalid candles field")
        for raw in candle_rows:
            stamp, open_, high, low, close, volume = _ohlcv(raw)
            if not config.start <= stamp.date() <= config.end:
                continue
            future_rows.append(
                {
                    "event_time": stamp,
                    "knowledge_time": entry.knowledge_time,
                    "instrument_id": contract_id,
                    "instrument_kind": "stock_future",
                    "underlying_instrument_id": issuer_id,
                    "contract_id": contract_id,
                    "expiry": expiry,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )

    cash = fetch_cash(config.cash_symbol, start=config.start, end=config.end)
    cash_rows = [
        {
            "event_time": candle.ts,
            "knowledge_time": cash_knowledge_time,
            "instrument_id": issuer_id,
            "instrument_kind": "cash",
            "underlying_instrument_id": issuer_id,
            "contract_id": "",
            "expiry": pd.NaT,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in cash
    ]
    if not future_rows:
        raise ValueError("No FYERS one-minute candles landed in the requested date range")
    if not cash_rows:
        raise ValueError("No archived cash one-minute candles found for the requested range")
    bars = pd.DataFrame([*future_rows, *cash_rows])
    bars["event_time"] = pd.to_datetime(bars["event_time"], utc=True).dt.tz_convert(IST)
    bars["knowledge_time"] = pd.to_datetime(bars["knowledge_time"], utc=True)
    bars["expiry"] = pd.to_datetime(bars["expiry"], errors="coerce").dt.date
    bars = bars.sort_values(["instrument_kind", "contract_id", "event_time", "knowledge_time"])
    return bars.drop_duplicates(
        subset=["instrument_kind", "contract_id", "instrument_id", "event_time"],
        keep="last",
    ).reset_index(drop=True)


def _fill_dict(fill: BacktestFill) -> dict[str, Any]:
    return {
        "strategy_id": fill.strategy_id,
        "instrument_id": fill.instrument_id,
        "session": fill.session.isoformat(),
        "entry_time": fill.entry_time.isoformat(),
        "exit_time": fill.exit_time.isoformat(),
        "side": fill.side,
        "entry_price": round(fill.entry_price, 6),
        "exit_price": round(fill.exit_price, 6),
        "quantity": fill.quantity,
        "gross_pnl_inr": round(fill.gross_pnl, 2),
        "fees_inr": round(fill.fees, 2),
        "net_pnl_inr": round(fill.net_pnl, 2),
    }


def _mirror_derived_to_b2(output_root: Path) -> dict[str, int | str]:
    """Upload just this strategy's artifacts under the matching derived key."""
    derived_root = DERIVED_ROOT.resolve()
    try:
        relative = output_root.resolve().relative_to(derived_root)
    except ValueError as exc:
        raise ValueError(f"output root must be inside {DERIVED_ROOT} for B2 mirroring") from exc
    try:
        config = load_storage_config(Path("config/storage.yaml"))
        store = S3ObjectStore(config)
        relative_prefix = relative.as_posix().strip(".").strip("/")
        suffix = f"{relative_prefix}/" if relative_prefix else ""
        prefix = f"{config.prefix}derived/{suffix}"
        result = sync_directory(output_root, store, prefix=prefix, verify=True, workers=1)
    except Exception as exc:
        raise ValueError(
            f"B2 mirror could not run ({type(exc).__name__}); "
            "local backtest artifacts are retained for retry."
        ) from exc
    if result.failed:
        details = "; ".join(result.failed[:3])
        raise ValueError(
            f"B2 mirror failed for {len(result.failed)} derived file(s): {details}. "
            "Local backtest artifacts are retained; rerun the command to retry."
        )
    summary: dict[str, int | str] = {
        "uploaded": result.uploaded,
        "already_present": result.skipped,
        "prefix": f"{config.bucket}/{prefix}",
    }
    return summary


def run(config: BacktestConfig, *, raw_root: Path, output_root: Path) -> dict[str, Any]:
    issuer_id = _issuer_id(config.cash_symbol, config.start, config.end, MASTER_PATH)
    landing = RawLanding(raw_root)
    fetch_report = FyersExpiredFO(credentials(), landing).fetch_underlying(
        config.underlying, config.start, config.end
    )
    retrieval_time = datetime.now(UTC)
    bars = normalize_bars(
        config,
        issuer_id=issuer_id,
        landing=landing,
        cash_knowledge_time=retrieval_time,
    )
    normalized_path = output_root / (
        f"{config.cash_symbol}_{config.start}_{config.evaluation_start}_{config.end}_bars.parquet"
    )
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(normalized_path, index=False)

    signals = futures_cash_signals(
        bars,
        min_return=config.minimum_future_return,
        hold_minutes=config.hold_minutes,
    )
    signals = [
        signal
        for signal in signals
        if config.evaluation_start <= signal.signal_time.astimezone(IST).date() <= config.end
    ]
    cash_eval = bars.loc[
        bars["instrument_kind"].eq("cash")
        & bars["event_time"].dt.date.ge(config.evaluation_start)
        & bars["event_time"].dt.date.le(config.end)
    ]
    calendar = sorted(set(cast(list[date], cash_eval["event_time"].dt.date.tolist())))
    if len(sorted(set(bars.loc[bars["instrument_kind"].eq("cash"), "event_time"].dt.date))) < (
        config.correlation_sessions + 1
    ):
        raise ValueError(
            f"The loaded cash range has fewer than {config.correlation_sessions} warmup sessions"
        )
    fills = backtest_bar_signals(signals, bars)
    result: dict[str, Any] = {
        "strategy_id": "micro-05",
        "status": "backtest_completed",
        "config": config.model_dump(mode="json"),
        "internal_instrument_id": issuer_id,
        "fetch": fetch_report,
        "data": {
            "normalized_bars": str(normalized_path),
            "future_bar_count": int(bars["instrument_kind"].eq("stock_future").sum()),
            "cash_bar_count": int(bars["instrument_kind"].eq("cash").sum()),
            "future_contract_count": int(
                bars.loc[bars["instrument_kind"].eq("stock_future"), "contract_id"].nunique()
            ),
            "first_cash_session": min(
                bars.loc[bars["instrument_kind"].eq("cash"), "event_time"].dt.date
            ).isoformat(),
            "last_cash_session": max(
                bars.loc[bars["instrument_kind"].eq("cash"), "event_time"].dt.date
            ).isoformat(),
            "event_time_source": "vendor candle timestamp",
            "knowledge_time_source": "FYERS response landing time; cash archive retrieval time",
        },
        "signal_count_in_evaluation": len(signals),
        "performance": summarize(fills, calendar),
        "fills": [_fill_dict(fill) for fill in fills],
        "limits": [
            "single underlying pilot; no parameter search",
            "cash OHLCV is from EulerLab's archived Kite minute candles",
            "cash fills use next-bar open and five-minute close with 2 bp per-side slippage and NSE intraday fees",
            "no order-book queue, market impact, or partial fills are modeled",
            "this is exploratory research, not a deployment approval",
        ],
    }
    result_path = output_root / (
        f"{config.cash_symbol}_{config.start}_{config.evaluation_start}_{config.end}_result.json"
    )
    result["result_path"] = str(result_path)
    result_path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    result["b2_mirror"] = _mirror_derived_to_b2(output_root)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="futures-cash-backtest")
    parser.add_argument("--underlying", default="NSE:RELIANCE-EQ")
    parser.add_argument("--cash-symbol", default="RELIANCE")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument(
        "--evaluation-from",
        dest="evaluation_start",
        type=date.fromisoformat,
        default=date(2026, 6, 1),
    )
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=date(2026, 8, 3))
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        config = BacktestConfig(
            underlying=args.underlying,
            cash_symbol=args.cash_symbol,
            start=args.start,
            evaluation_start=args.evaluation_start,
            end=args.end,
        )
        report = run(config, raw_root=args.raw_root, output_root=args.output_root)
    except (FyersAPIError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
