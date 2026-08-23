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
            _has_files("crypto", "*/*.jsonl.gz"),
            _crypto_detail(),
        ),
        Capability(
            AssetClass.CRYPTO,
            Timeframe.DAILY,
            _has_files("crypto", "*/*.jsonl.gz"),
            "resampled from the minute archive",
        ),
        Capability(
            AssetClass.MUTUAL_FUND,
            Timeframe.DAILY,
            _has_files("mf", "history/*.jsonl.gz"),
            _fund_detail(),
        ),
        Capability(AssetClass.FX, Timeframe.MINUTE, FX_LANDING.exists(), _fx_detail()),
        Capability(
            AssetClass.FX, Timeframe.DAILY, FX_LANDING.exists(), "resampled from minute bars"
        ),
    ]


def _fx_detail() -> str:
    """Counted from disk, like every other row."""
    found = _tree_files("fx", "*/*/*.jsonl.gz")
    if not found:
        return "no FX bars landed — run `make fx-bulk`"
    pairs = {r.split("/")[1] for r in found if len(r.split("/")) >= 2}
    return f"{len(pairs)} pairs, {len(found):,} pair-days of 1m bars (FXCM, bid and ask)"


def fx_instruments(query: str = "", limit: int = 60) -> list[Instrument]:
    """The landed FX universe, read from disk.

    Ranked by BIS turnover order rather than by anything measured here: spot FX
    has no consolidated volume, so a liquidity ranking derived from our own data
    would be an artefact of one broker's quote frequency.
    """
    from eulerlab.ingest.fx import PAIRS

    needle = query.strip().upper()
    out: list[Instrument] = []
    landed_fx: dict[str, int] = {}
    for relative in _tree_files("fx", "*/*/*.jsonl.gz"):
        parts = relative.split("/")
        if len(parts) >= 2:
            landed_fx[parts[1]] = landed_fx.get(parts[1], 0) + 1

    for rank, pair in enumerate(PAIRS, start=1):
        if needle and needle not in pair:
            continue
        days = landed_fx.get(pair, 0)
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
    history = _tree_files("mf", "history/*.jsonl.gz")
    if not history:
        return "no NAV history landed — run `make mf`"
    landed = len(history)
    snapshot = _latest_enriched_relative()
    stamp = snapshot.split("/")[-1].split(".")[0] if snapshot else "no snapshot"
    return f"{landed:,} schemes with landed NAV history (AMFI, snapshot {stamp})"


def _tree_files(tree: str, pattern: str) -> list[str]:
    """Landing-relative paths under a tree, from disk **and the bucket**.

    Local-only was the first fix and was half of one. `prune-local` moves data
    to B2 rather than deleting it, so a local glob reports an emptied tree as
    absent — the snapshot said "4 crypto instruments" against twenty landed,
    and "0 mutual funds" against 14,280. Asking only the disk is as wrong as
    asking only the directory entry, one layer up.
    """
    from eulerlab.ingest import landing_reader

    return landing_reader.available(tree, pattern)


def _has_files(tree: str, pattern: str) -> bool:
    """Whether a tree holds data anywhere — disk or bucket.

    Takes the tree name explicitly rather than deriving it from a `Path`. The
    derived version used `root.name`, which for `data/landing/mf/history` gives
    `history` and looked for a landing tree of that name — so mutual funds
    reported unsupported while 14,280 NAV files sat in the bucket, and the
    instrument picker and the capability matrix disagreed about the same data.
    """
    from eulerlab.ingest import landing_reader

    # Not `_tree_files(...)`: that enumerates the tree to answer a boolean, and
    # for fx that was 34,051 keys over 35 paginated requests — 62 seconds per
    # call, on a matrix the snapshot renders every time.
    return landing_reader.has_any(tree, pattern)


def _crypto_detail() -> str:
    """Measured from disk, like every other row in this table."""
    found = _tree_files("crypto", "*/*.jsonl.gz")
    if not found:
        return "no data — run `make crypto`"
    symbols = {r.split("/")[1] for r in found if len(r.split("/")) >= 2}
    return f"{len(symbols)} symbols, {len(found)} symbol-months of 1m bars (Binance archive)"


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
    needle = query.strip().upper()
    # Symbols with no landed months are skipped, not listed with a zero.
    # `make prune-local` empties the directories and leaves them behind, so a
    # symbol folder is not evidence of data — and a picker that offers an
    # instrument the engine cannot read is the exact defect this module exists
    # to prevent, pointed inward.
    counts: dict[str, int] = {}
    for relative in _tree_files("crypto", "*/*.jsonl.gz"):
        parts = relative.split("/")
        if len(parts) >= 2:
            counts[parts[1]] = counts.get(parts[1], 0) + 1
    landed = sorted(((n, sym) for sym, n in counts.items()), key=lambda x: (-x[0], x[1]))
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


def _latest_enriched_relative() -> str | None:
    """Newest enriched MF snapshot, wherever it lives."""
    found = _tree_files("mf", "enriched/*.jsonl.gz")
    return found[-1] if found else None


def fund_instruments(query: str = "", limit: int = 60) -> list[Instrument]:
    """Mutual fund schemes from the newest enriched snapshot.

    Matched on name, AMC, ISIN and scheme code, because a person looking for a
    fund knows its name and not its code. Only schemes with landed NAV history
    report `has_daily`: a scheme in the snapshot with no history file is
    listed but cannot be backtested, and saying so is better than offering it
    and returning nothing.
    """
    snapshot_rel = _latest_enriched_relative()
    if snapshot_rel is None:
        return []
    needle = query.strip().upper()
    have_history = {
        relative.split("/")[-1].split(".")[0]
        for relative in _tree_files("mf", "history/*.jsonl.gz")
    }
    # AMFI publishes one row per ISIN and a scheme has two — growth/payout and
    # reinvestment — so the snapshot lists every scheme_code twice. A picker
    # offers a *scheme* to backtest, not an ISIN variant, and showing 119551
    # twice would be a defect rather than a distinction.
    seen: set[str] = set()

    from eulerlab.ingest import landing_reader

    out: list[Instrument] = []
    text = gzip.decompress(landing_reader.read(snapshot_rel)).decode("utf-8", "replace")
    for rank, line in enumerate(text.splitlines(), start=1):
        if True:
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

    # Only classes the capability matrix calls supported, and every one of
    # them. Both directions are defects: offering an instrument that cannot be
    # backtested wastes the operator's time, and hiding one that can is how
    # crypto and mutual funds went unreachable in the first place.
    #
    # This used to be a fixed quarter-share over four hardcoded builders, which
    # silently disagreed with `capabilities()` whenever a class had a snapshot
    # but no history - mutual funds offered in the picker while the matrix
    # called them unsupported. Deriving the split from the matrix makes the two
    # incapable of drifting apart.
    builders = {
        AssetClass.EQUITY.value: lambda n: equity_instruments(query, limit=n),
        AssetClass.CRYPTO.value: lambda n: crypto_instruments(query, n),
        AssetClass.FX.value: lambda n: fx_instruments(query, n),
        AssetClass.MUTUAL_FUND.value: lambda n: fund_instruments(query, n),
    }
    usable = _supported_classes()
    supported = [name for name in builders if name in usable]
    if not supported:
        return []

    share = max(1, limit // len(supported))
    mixed: list[Instrument] = []
    for index, name in enumerate(supported):
        # The last class takes the remainder, so the limit is spent rather than
        # rounded away.
        take = limit - share * (len(supported) - 1) if index == len(supported) - 1 else share
        mixed.extend(builders[name](max(1, take)))
    return mixed[:limit]


def _supported_classes() -> set[str]:
    """Asset-class names the capability matrix reports as usable."""
    return {c.asset_class.value for c in capabilities() if c.supported}
