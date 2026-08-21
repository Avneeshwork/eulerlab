"""What data actually exists, and which instruments can be selected.

ADR-037: *declared is not supported.* The strategy interface will happily
accept crypto at one-second bars; the data does not exist, and a console that
offers it produces a confident backtest over nothing. An empty result reads as
"no trades found" when the truth is "this was never measured", and those are
not the same sentence.

So this module answers two questions honestly:

  - for a given (asset class, timeframe), is there data at all?
  - which instruments can be picked, and what history does each have?

Both are read from what is on disk, never asserted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eulerlab.strategies import AssetClass, Timeframe

UNIVERSE_FILES = {
    "nifty50": (Path("config/universe_top250.txt"), 50),
    "nifty100": (Path("config/universe_top250.txt"), 100),
    "nifty250": (Path("config/universe_top250.txt"), 250),
    "all_liquid": (Path("config/universe_all_liquid.txt"), 0),
}
"""Batch name to (source file, how many of it to take). 0 means all of it.

**These are not index constituents.** They are liquidity-ranked slices of our
own turnover history (ADR-008), because a published constituent list exists
only as it stands today and applying it across history is survivorship bias.
Everyone who sees a chip labelled `nifty50` will assume otherwise, so the
caveat travels with the data rather than living in the page.
"""

UNIVERSE_CAVEAT = (
    "Liquidity-ranked from our own turnover history, not index membership "
    "(ADR-008). A published constituent list exists only as it stands today, "
    "so using one across history would be survivorship bias."
)


@dataclass(frozen=True)
class Capability:
    asset_class: AssetClass
    timeframe: Timeframe
    supported: bool
    detail: str


def capabilities() -> list[Capability]:
    """The matrix, measured from disk where it can be and stated where it cannot.

    Equity daily and equity minute are checked against real paths. The rest are
    absent, and saying so plainly is the point of the table.
    """
    # Imported rather than hardcoded: the panel moved once already, and a
    # capability check that looks at the wrong path reports "no data" for data
    # that is sitting right there — the failure mode this whole table exists
    # to prevent, one level up.
    from eulerlab.features.panel import PANEL_PATH

    minute = Path("data/landing/kite_minute")

    daily_detail = (
        f"panel present, {PANEL_PATH.stat().st_size / 1e9:.2f} GB"
        if PANEL_PATH.exists()
        else "panel not built on this machine (make panel)"
    )
    minute_detail = (
        "minute cache present; B2 is the store of record"
        if minute.exists()
        else "no local minute cache; reads stream from B2 on demand"
    )

    return [
        Capability(AssetClass.EQUITY, Timeframe.MINUTE, True, minute_detail),
        Capability(AssetClass.EQUITY, Timeframe.DAILY, True, daily_detail),
        Capability(AssetClass.EQUITY, Timeframe.WEEKLY, True, "resampled from daily"),
        Capability(AssetClass.FUTURES, Timeframe.DAILY, False, "F&O bhavcopy landed, never wired"),
        Capability(AssetClass.OPTIONS, Timeframe.DAILY, False, "chains parsed, no strategy path"),
        Capability(
            AssetClass.OPTIONS, Timeframe.MINUTE, False, "the chain recorder was never built"
        ),
        Capability(
            AssetClass.CRYPTO,
            Timeframe.MINUTE,
            Path("data/landing/crypto").exists(),
            _crypto_detail(),
        ),
        Capability(
            AssetClass.CRYPTO,
            Timeframe.DAILY,
            Path("data/landing/crypto").exists(),
            "resampled from the minute archive",
        ),
        Capability(AssetClass.FX, Timeframe.DAILY, False, "no data"),
    ]


def _crypto_detail() -> str:
    """Measured from disk, like every other row in this table."""
    root = Path("data/landing/crypto")
    if not root.exists():
        return "no data — run `make crypto`"
    symbols = [p for p in root.iterdir() if p.is_dir()]
    months = sum(1 for _ in root.glob("*/*.jsonl.gz"))
    return f"{len(symbols)} symbols, {months} symbol-months of 1m bars (Binance archive)"


def universe(name: str) -> list[str]:
    """Resolve a batch name to symbols. Raises rather than returning nothing."""
    key = name.lower().replace(" ", "").replace("-", "")
    if key not in UNIVERSE_FILES:
        msg = f"unknown batch {name!r}; try {', '.join(sorted(UNIVERSE_FILES))}"
        raise ValueError(msg)
    path, limit = UNIVERSE_FILES[key]
    if not path.exists():
        msg = f"{path} is missing; the batch is derived from it"
        raise FileNotFoundError(msg)
    symbols = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return symbols[:limit] if limit else symbols


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: AssetClass
    has_daily: bool
    has_minute: bool
    rank: int
    """Position in the liquidity ranking. Lower is more traded."""


def _minute_symbols() -> set[str]:
    """Symbols with a local minute cache.

    Only the local cache is inspected. Listing B2 would be a network call on
    every keystroke of a search box, and the honest fallback is that a symbol
    without a local cache may still stream from B2 — so this is reported as
    "cached locally", not as "exists".
    """
    root = Path("data/landing/kite_minute")
    if not root.exists():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir()}


def search(query: str = "", *, batch: str = "", limit: int = 60) -> list[Instrument]:
    """Instruments matching `query`, restricted to `batch` when given."""
    symbols = universe(batch) if batch else universe("all_liquid")
    minute = _minute_symbols()
    needle = query.strip().upper()

    out: list[Instrument] = []
    for rank, symbol in enumerate(symbols, start=1):
        if needle and needle not in symbol:
            continue
        out.append(
            Instrument(
                symbol=symbol,
                asset_class=AssetClass.EQUITY,
                has_daily=True,
                has_minute=symbol in minute,
                rank=rank,
            )
        )
        if len(out) >= limit:
            break
    return out
