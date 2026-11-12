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
from functools import lru_cache
from pathlib import Path

from eulerlab.paths import data_path
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

    minute = data_path("landing/kite_minute")

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
        # `_has_files`, not `FX_LANDING.exists()`. A prune moves the bytes to B2
        # and leaves the directory tree behind, so the raw existence check kept
        # reporting FX supported against an empty tree — the matrix said yes
        # while the instrument picker, which reads real paths, offered nothing.
        # The same "a directory entry is not data" mistake as T-3727, one tree
        # over.
        Capability(
            AssetClass.FX,
            Timeframe.MINUTE,
            _has_files("fx", "*/*/*.jsonl.gz"),
            _fx_detail(),
        ),
        Capability(
            AssetClass.FX,
            Timeframe.DAILY,
            _has_files("fx", "*/*/*.jsonl.gz"),
            "resampled from minute bars",
        ),
        # US arrives last and was missing entirely: 36,000 daily bars and 71
        # million minute bars sat in the bucket while the matrix said the
        # platform had no US data, so the picker offered none and a US backtest
        # could not be started from the interface at all.
        # Tree names are `us/bars` and `us/minute`, which is how the manifest
        # records them. Asking for tree `"us"` with a `bars/...` pattern missed
        # the census every time and fell through to a bucket enumeration of the
        # whole US minute prefix — tens of thousands of objects, which does not
        # return inside a web request. The instrument picker then showed an
        # empty table and US looked like data the platform did not have.
        #
        # The same shape as the `root.name` bug in `_has_files`'s own docstring:
        # a tree name that does not match what the manifest wrote down.
        Capability(
            AssetClass.US,
            Timeframe.DAILY,
            _has_files("us/bars", "*.jsonl.gz"),
            _us_detail(),
        ),
        Capability(
            AssetClass.US,
            Timeframe.MINUTE,
            _has_files("us/minute", "*/*.jsonl.gz"),
            "1-minute bars, Alpaca IEX feed — prices track the tape, volume does not",
        ),
    ]


def _us_detail() -> str:
    """Counted from the manifest, like every other row.

    Reads `us/bars` and `us/minute` separately because that is how the manifest
    keys them — there is no tree called `us`.
    """
    bars = _census("us/bars")
    minute = _census("us/minute")
    if bars is None and minute is None:
        return "US bars landed — count unmeasured (run `make manifest`)"
    daily_files = getattr(bars, "files", 0) if bars is not None else 0
    minute_files = getattr(minute, "files", 0) if minute is not None else 0
    if not daily_files and not minute_files:
        return "no US bars landed — run `make us-bars`"
    return f"{daily_files:,} daily and {minute_files:,} minute objects (Alpaca)"


def _census(tree: str) -> object | None:
    """The counted size of a tree, from the local manifest.

    Returns None when the manifest has never been built, which the callers
    treat as "measure it live and say so" rather than as zero.

    Also None when the bucket is unreachable, and that is the subtler case.
    The manifest counts what lives in **B2**, most of which is not on this
    disk after a prune — so offline it would report 34,773 FX files that
    nothing here can open. The capability matrix would call FX supported while
    the instrument picker, which reads real paths, offered none of it. A count
    of unreachable data is not an answer about what is usable.
    """
    from eulerlab.ingest import landing_reader, manifest

    if not landing_reader.cloud_enabled():
        return None

    loaded = manifest.load()
    return loaded.census(tree) if loaded else None


def _fx_detail() -> str:
    """Counted from disk, like every other row."""
    census = _census("fx")
    if census is None:
        return "FX bars landed — count unmeasured (run `make manifest`)"
    if not census.files:  # type: ignore[attr-defined]
        return "no FX bars landed — run `make fx-bulk`"
    return (
        f"{census.groups} pairs, {census.files:,} pair-days "  # type: ignore[attr-defined]
        "of 1m bars (FXCM, bid and ask)"
    )


def fx_instruments(query: str = "", limit: int = 60) -> list[Instrument]:
    """The landed FX universe, read from disk.

    Ranked by BIS turnover order rather than by anything measured here: spot FX
    has no consolidated volume, so a liquidity ranking derived from our own data
    would be an artefact of one broker's quote frequency.
    """
    from eulerlab.ingest.fx import PAIRS

    needle = query.strip().upper()
    out: list[Instrument] = []
    landed_fx = _fx_months()

    for rank, pair in enumerate(PAIRS, start=1):
        if needle and needle not in pair:
            continue
        months = landed_fx.get(pair, 0)
        if months == 0:
            # Pruned to B2 or never landed. Either way it cannot be read here.
            continue
        out.append(
            Instrument(
                symbol=pair,
                asset_class=AssetClass.FX,
                has_daily=months > 0,
                has_minute=months > 0,
                rank=rank,
                name=f"{pair[:3]}/{pair[3:]}",
                detail=f"{months:,} months landed, BIS turnover rank {rank}",
            )
        )
        if len(out) >= limit:
            break
    return out


def us_instruments(query: str = "", limit: int = 60) -> list[Instrument]:
    """The landed US universe, read from the bucket and disk together.

    Ranked alphabetically rather than by turnover, and that is a deliberate
    refusal. The only volume this platform holds for US names is the IEX feed,
    one venue with a low single-digit share of the consolidated tape (A-031).
    Ranking by it would produce a confident ordering of *IEX participation* and
    present it as liquidity — the same class of artefact the FX ranking avoids
    by using BIS order instead of measured quote frequency.
    """
    needle = query.strip().upper()
    minute, daily = _us_symbols()

    out: list[Instrument] = []
    for rank, symbol in enumerate(sorted(minute | daily), start=1):
        if needle and needle not in symbol:
            continue
        out.append(
            Instrument(
                symbol=symbol,
                asset_class=AssetClass.US,
                has_daily=symbol in daily,
                has_minute=symbol in minute,
                rank=rank,
                name=symbol,
                detail=("daily and 1-minute bars" if symbol in minute else "daily bars"),
            )
        )
        if len(out) >= limit:
            break
    return out


@lru_cache(maxsize=1)
def _us_symbols() -> tuple[frozenset[str], frozenset[str]]:
    """(minute, daily) symbol sets, read cheaply.

    The obvious implementation — glob the landing tree — makes one request per
    search that enumerates the whole US minute prefix. That is 71 million bars
    across tens of thousands of objects, and it does not return: the instrument
    search timed out at ninety seconds and the picker showed nothing, which is
    what "US stock search not working" looked like from the outside.

    So symbols come from **directory names**, not from object listings. A prune
    moves the bytes to B2 and leaves the tree behind, so `us/minute/AAPL/` still
    exists locally with nothing in it — normally a trap (T-3727 is about exactly
    that mistake) and here the cheap answer, because the question is which
    symbols exist rather than which bytes are present.

    Cached for the process. The universe changes when a batch is landed, which
    is not something that happens between two keystrokes in a search box.
    """
    from eulerlab.ingest.alpaca import LANDING
    from eulerlab.intraday.us_store import symbols as minute_symbols

    # One implementation, in `us_store`, so the picker and the intraday scanner
    # cannot disagree about which symbols exist.
    minute: set[str] = set(minute_symbols())

    daily: set[str] = set()
    bars = LANDING / "bars"
    if bars.exists():
        daily = {p.name.split(".")[0].upper() for p in bars.iterdir() if p.is_file()}

    # The daily panel is the authority on what can actually be backtested, and
    # it is local and already parsed elsewhere. Used only to fill gaps, so a
    # symbol with minute data but no daily row is still offered.
    if not daily:
        try:
            from eulerlab.features import us_panel

            daily = {row.symbol.upper() for row in us_panel.read()}
        except (OSError, ValueError):
            daily = set()

    return frozenset(minute), frozenset(daily or minute)


@lru_cache(maxsize=1)
def _fx_months() -> dict[str, int]:
    """Months landed per FX pair, counted without enumerating the bucket.

    The direct form globbed `fx/*/*/*.jsonl.gz`, which is 34,051 keys over 35
    paginated requests and **21.7 seconds** — on a call the instrument picker
    makes on every page load, and inside a mixed-class search that also pays for
    crypto and mutual funds. That is most of why the picker appeared to hang.

    `_has_files` learned this lesson one layer up and its docstring says so:
    "that enumerates the tree to answer a boolean... 62 seconds per call". The
    builder underneath it kept doing exactly that to answer a count.

    Counted from local directory names instead. A prune moves bytes to B2 and
    leaves `fx/EURUSD/2015-01/` behind, so the month directories still say how
    many months landed. Falls back to the listing only when there is no local
    tree at all, which is a fresh clone rather than a pruned one.
    """
    from eulerlab.ingest.fx import LANDING

    counts: dict[str, int] = {}
    if LANDING.exists():
        for pair_dir in LANDING.iterdir():
            if not pair_dir.is_dir():
                continue
            # **Months**, not days. The day files are pruned to B2, so a local
            # glob for them finds nothing and falls through to the enumeration
            # this function exists to avoid — 23 seconds to learn a number the
            # month directories already imply.
            #
            # Counting the months and calling them days would understate by
            # twenty-five-fold while looking right, so the caller is told which
            # unit it received.
            months = sum(1 for month in pair_dir.iterdir() if month.is_dir())
            if months:
                counts[pair_dir.name.upper()] = months
    if counts:
        return counts

    # Fresh clone with no local tree at all. Slow, correct, and counting days
    # rather than months — so the two branches disagree about the unit, which
    # is why the detail line says which one it got.
    for relative in _tree_files("fx", "*/*/*.jsonl.gz"):
        parts = relative.split("/")
        if len(parts) >= 2:
            counts[parts[1]] = counts.get(parts[1], 0) + 1
    return counts


def _fund_detail() -> str:
    """Counted from disk, like every other row."""
    census = _census("mf")
    if census is None:
        return "NAV history landed — count unmeasured (run `make manifest`)"
    if not census.files:  # type: ignore[attr-defined]
        return "no NAV history landed — run `make mf`"
    landed = census.files  # type: ignore[attr-defined]
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

    # A screen's counts: an old listing now beats a current one in a minute.
    return landing_reader.available(tree, pattern, stale_ok=True)


def _has_files(tree: str, pattern: str) -> bool:
    """Whether a tree holds data anywhere — disk or bucket.

    Takes the tree name explicitly rather than deriving it from a `Path`. The
    derived version used `root.name`, which for `data/landing/mf/history` gives
    `history` and looked for a landing tree of that name — so mutual funds
    reported unsupported while 14,280 NAV files sat in the bucket, and the
    instrument picker and the capability matrix disagreed about the same data.
    """
    # The manifest first, because it is a local file and already holds the
    # answer. Falling straight through to the bucket meant the matrix still
    # paid a network round trip per row to learn something `make daily` had
    # counted hours earlier.
    census = _census(tree)
    if census is not None:
        return bool(census.files)  # type: ignore[attr-defined]

    from eulerlab.ingest import landing_reader

    # No manifest yet. Not `_tree_files(...)`: that enumerates the tree to
    # answer a boolean, and for fx that was 34,051 keys over 35 paginated
    # requests — 62 seconds per call, on a matrix the snapshot renders every
    # time. One MaxKeys=1 probe answers the same question.
    return landing_reader.has_any(tree, pattern)


def _crypto_detail() -> str:
    """Measured from disk, like every other row in this table."""
    census = _census("crypto")
    if census is None:
        return "minute bars landed — count unmeasured (run `make manifest`)"
    if not census.files:  # type: ignore[attr-defined]
        return "no data — run `make crypto`"
    return (
        f"{census.groups} symbols, {census.files} symbol-months "  # type: ignore[attr-defined]
        "of 1m bars (Binance archive)"
    )


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
    root = data_path("landing/kite_minute")
    if not root.exists():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir()}


CRYPTO_LANDING = data_path("landing/crypto")
FX_LANDING = data_path("landing/fx")
MF_ENRICHED = data_path("landing/mf/enriched")
MF_HISTORY = data_path("landing/mf/history")


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
        base = symbol.removesuffix("USDT")
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
    """Newest enriched MF snapshot, wherever it lives.

    Asks the census first. Listing the `mf` tree to learn the name of one file
    means paginating 14,280 keys, and this is called while rendering a
    capability row — the manifest already records the newest name for exactly
    this reason.
    """
    # `mf/enriched`, not `mf`. They are separate census entries because the
    # tree holds two different things, and asking the wrong one returned a
    # scheme code where a dated snapshot belongs.
    census = _census("mf/enriched")
    newest = getattr(census, "newest", "") if census is not None else ""
    if newest:
        return f"mf/enriched/{newest}"

    found = _tree_files("mf", "enriched/*.jsonl.gz")
    return found[-1] if found else None


@lru_cache(maxsize=1)
def _fund_history_codes() -> frozenset[str]:
    """Scheme codes with landed NAV history, enumerated once per process.

    This is the one store that cannot be answered from local directory names.
    FX and US keep a directory per symbol, which survives a prune and says which
    symbols exist; mutual fund history is **flat** — `mf/history/119551.jsonl.gz`
    — so pruning leaves nothing behind and the only source is the bucket.

    That enumeration is 14,280 keys and **18.7 seconds**, and it was being paid
    on every keystroke in the instrument search: the mixed-class picker call
    took thirteen seconds, and eleven of them were this.

    Cached rather than made cheap, because it cannot be made cheap without
    recording the code list somewhere. The first search in a process still pays
    once. Recording the ids in the manifest would remove even that, and is the
    right fix if this ever matters again.
    """
    # The manifest records these ids explicitly, because they are the one set
    # that cannot be recovered from disk after a prune. Falls through to the
    # bucket only when the manifest has never been built.
    census = _census("mf")
    ids = getattr(census, "ids", ()) if census is not None else ()
    if ids:
        return frozenset(ids)

    return frozenset(
        relative.split("/")[-1].split(".")[0]
        for relative in _tree_files("mf", "history/*.jsonl.gz")
    )


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
    have_history = _fund_history_codes()
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
    if wanted == AssetClass.US.value:
        return us_instruments(query, limit)
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
        AssetClass.US.value: lambda n: us_instruments(query, n),
        AssetClass.MUTUAL_FUND.value: lambda n: fund_instruments(query, n),
    }
    from eulerlab.ingest import landing_reader

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
        # A class whose files are pruned locally and whose bucket cannot be
        # reached is left out, not allowed to fail the whole search: on
        # 2026-10-30 a missing fund snapshot turned every picker into a 500.
        try:
            mixed.extend(builders[name](max(1, take)))
        except (landing_reader.CloudUnavailable, FileNotFoundError):
            continue
    return mixed[:limit]


def _supported_classes() -> set[str]:
    """Asset-class names the capability matrix reports as usable."""
    return {c.asset_class.value for c in capabilities() if c.supported}
