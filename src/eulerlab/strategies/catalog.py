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

import gzip
import json
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
            _has_files(CRYPTO_LANDING, "*/*.jsonl.gz"),
            _crypto_detail(),
        ),
        Capability(
            AssetClass.CRYPTO,
            Timeframe.DAILY,
            _has_files(CRYPTO_LANDING, "*/*.jsonl.gz"),
            "resampled from the minute archive",
        ),
        Capability(
            AssetClass.MUTUAL_FUND,
            Timeframe.DAILY,
            _has_files(MF_HISTORY, "*.jsonl.gz"),
            _fund_detail(),
        ),
        Capability(AssetClass.FX, Timeframe.MINUTE, FX_LANDING.exists(), _fx_detail()),
        Capability(
            AssetClass.FX, Timeframe.DAILY, FX_LANDING.exists(), "resampled from minute bars"
        ),
    ]


def _fx_detail() -> str:
    """Counted from disk, like every other row."""
    if not _has_files(FX_LANDING, "*/*/*.jsonl.gz"):
        return "no local FX bars — pruned to B2, or never run (`make fx-bulk`)"
    pairs = [p for p in FX_LANDING.iterdir() if p.is_dir()]
    days = sum(1 for _ in FX_LANDING.glob("*/*/*.jsonl.gz"))
    return f"{len(pairs)} pairs, {days:,} pair-days of 1m bars (FXCM, bid and ask)"


def fx_instruments(query: str = "", limit: int = 60) -> list[Instrument]:
    """The landed FX universe, read from disk.

    Ranked by BIS turnover order rather than by anything measured here: spot FX
    has no consolidated volume, so a liquidity ranking derived from our own data
    would be an artefact of one broker's quote frequency.
    """
    if not FX_LANDING.exists():
        return []
    from eulerlab.ingest.fx import PAIRS

    needle = query.strip().upper()
    out: list[Instrument] = []
    for rank, pair in enumerate(PAIRS, start=1):
        folder = FX_LANDING / pair
        if not folder.is_dir():
            continue
        if needle and needle not in pair:
            continue
        days = sum(1 for _ in folder.glob("*/*.jsonl.gz"))
        if days == 0:
            # Pruned to B2 or never landed. Either way it cannot be read here.
            continue
        out.append(
            Instrument(
                symbol=pair,
                asset_class=AssetClass.FX,
                has_daily=days > 0,
                has_minute=days > 0,
                rank=rank,
                name=f"{pair[:3]}/{pair[3:]}",
                detail=f"{days:,} days landed, BIS turnover rank {rank}",
            )
        )
        if len(out) >= limit:
            break
    return out


def _fund_detail() -> str:
    """Counted from disk, like every other row."""
    if not _has_files(MF_HISTORY, "*.jsonl.gz"):
        return "no local NAV history — pruned to B2, or never run (`make mf`)"
    landed = sum(1 for _ in MF_HISTORY.glob("*.jsonl.gz"))
    snapshot = _latest_enriched()
    stamp = snapshot.name.split(".")[0] if snapshot else "no snapshot"
    return f"{landed:,} schemes with landed NAV history (AMFI, snapshot {stamp})"


def _has_files(root: Path, pattern: str) -> bool:
    """Whether a tree holds any data *right now*.

    Not `root.exists()`. `make prune-local` deletes files that are verified
    present in B2 and leaves the directory behind, so existence stopped being
    evidence the moment pruning became a supported workflow. A matrix that says
    "supported" over an emptied directory is asserting rather than reading,
    which is the one thing this module exists not to do.
    """
    return any(root.glob(pattern))


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

    name: str = ""
    """A human-readable name, where the symbol alone is not one.

    Equities and crypto pairs are recognisable from the ticker. A mutual fund
    scheme code is not — `119551` tells nobody anything, and a picker that
    showed only the code would be unusable for the 14,280 schemes on disk.
    """

    detail: str = ""
    """What the row is, in a few words. AMC and plan for a fund, quote currency
    for a crypto pair."""


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


CRYPTO_LANDING = Path("data/landing/crypto")
FX_LANDING = Path("data/landing/fx")
MF_ENRICHED = Path("data/landing/mf/enriched")
MF_HISTORY = Path("data/landing/mf/history")


def crypto_instruments(query: str = "", limit: int = 60) -> list[Instrument]:
    """The landed crypto universe, read from the directories on disk.

    Ranked by how many months are landed rather than by turnover: the
    liquidity ranking that orders equities does not exist here, and inventing
    one would be worse than ordering by the thing actually measured.
    """
    if not CRYPTO_LANDING.exists():
        return []
    needle = query.strip().upper()
    # Symbols with no landed months are skipped, not listed with a zero.
    # `make prune-local` empties the directories and leaves them behind, so a
    # symbol folder is not evidence of data — and a picker that offers an
    # instrument the engine cannot read is the exact defect this module exists
    # to prevent, pointed inward.
    landed = [
        (months, path.name)
        for path in sorted(CRYPTO_LANDING.iterdir())
        if path.is_dir() and (months := len(list(path.glob("*.gz")))) > 0
    ]
    landed.sort(key=lambda item: (-item[0], item[1]))

    out: list[Instrument] = []
    for rank, (months, symbol) in enumerate(landed, start=1):
        if needle and needle not in symbol:
            continue
        base = symbol[:-4] if symbol.endswith("USDT") else symbol
        out.append(
            Instrument(
                symbol=symbol,
                asset_class=AssetClass.CRYPTO,
                # Minute bars are what was landed; the daily panel is resampled
                # from them (alt_panel), so both are true here.
                has_daily=months > 0,
                has_minute=months > 0,
                rank=rank,
                name=base,
                detail=f"{months} months landed, quoted in USDT",
            )
        )
        if len(out) >= limit:
            break
    return out


def _latest_enriched() -> Path | None:
    if not MF_ENRICHED.exists():
        return None
    snapshots = sorted(MF_ENRICHED.glob("*.jsonl.gz"))
    return snapshots[-1] if snapshots else None


def fund_instruments(query: str = "", limit: int = 60) -> list[Instrument]:
    """Mutual fund schemes from the newest enriched snapshot.

    Matched on name, AMC, ISIN and scheme code, because a person looking for a
    fund knows its name and not its code. Only schemes with landed NAV history
    report `has_daily`: a scheme in the snapshot with no history file is
    listed but cannot be backtested, and saying so is better than offering it
    and returning nothing.
    """
    snapshot = _latest_enriched()
    if snapshot is None:
        return []
    needle = query.strip().upper()
    have_history = {path.name.split(".")[0] for path in MF_HISTORY.glob("*.jsonl.gz")}
    # AMFI publishes one row per ISIN and a scheme has two — growth/payout and
    # reinvestment — so the snapshot lists every scheme_code twice. A picker
    # offers a *scheme* to backtest, not an ISIN variant, and showing 119551
    # twice would be a defect rather than a distinction.
    seen: set[str] = set()

    out: list[Instrument] = []
    with gzip.open(snapshot, "rt", encoding="utf-8") as handle:
        for rank, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = str(row.get("scheme_code", ""))
            if code in seen:
                continue
            name = str(row.get("name", ""))
            amc = str(row.get("amc", "") or "")
            isin = str(row.get("isin", "") or "")
            if needle and needle not in f"{code} {name} {amc} {isin}".upper():
                continue
            plan = str(row.get("plan", "") or "")
            option = str(row.get("option", "") or "")
            seen.add(code)
            out.append(
                Instrument(
                    symbol=code,
                    asset_class=AssetClass.MUTUAL_FUND,
                    has_daily=code in have_history,
                    has_minute=False,
                    rank=rank,
                    name=name,
                    detail=" · ".join(part for part in (amc, plan, option) if part),
                )
            )
            if len(out) >= limit:
                break
    return out


def equity_instruments(query: str = "", *, batch: str = "", limit: int = 60) -> list[Instrument]:
    """Equities from a liquidity-ranked batch."""
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


def search(
    query: str = "", *, batch: str = "", limit: int = 60, asset_class: str = ""
) -> list[Instrument]:
    """Instruments matching `query`, across every asset class that has data.

    Previously this returned equities and nothing else, which quietly meant the
    crypto and mutual fund data — 20 landed pairs and 14,280 schemes — could
    not be seen or selected at all. An asset class with data on disk and no way
    to reach it is the same defect as one offered without data, in the other
    direction.

    With no `asset_class` the classes are interleaved by share of the limit, so
    a bare search does not return sixty equities and imply the rest are absent.
    """
    wanted = asset_class.strip().lower()
    if wanted == AssetClass.CRYPTO.value:
        return crypto_instruments(query, limit)
    if wanted == AssetClass.MUTUAL_FUND.value:
        return fund_instruments(query, limit)
    if wanted == AssetClass.FX.value:
        return fx_instruments(query, limit)
    if wanted == AssetClass.EQUITY.value or batch:
        return equity_instruments(query, batch=batch, limit=limit)

    share = max(1, limit // 4)
    mixed = [
        *equity_instruments(query, limit=share),
        *crypto_instruments(query, limit=share),
        *fx_instruments(query, limit=share),
        *fund_instruments(query, limit=limit - 3 * share),
    ]
    return mixed[:limit]
