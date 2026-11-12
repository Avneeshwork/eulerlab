"""Running many backtests, with a cache that cannot launder a trial.

ADR-036 decision 5. Two facts have to hold at once, and they pull in opposite
directions:

**A batch of backtests spends no trial.** Only `make validate` and `make gate`
write to the hash-chained ledger. That is a deliberate property of the web
interface (T-3007) — an interface makes running things cheap, and an interface
that could also spend trials would let someone burn fifty in an afternoon by
clicking.

**But screening is still searching.** Fifty configurations screened here is
fifty configurations you looked at, and the ledger does not record any of it.
That is the laundering ADR-036 named: *skip new configurations and the search
is laundered — invisibly, by construction.* The gap is real and this module
does not close it; what it does is refuse to hide it. `Batch.unrecorded` counts
exactly how much search a run performed without paying for it, and the console
reports that number rather than a reassuring silence.

The cache is content-addressed on everything that could change an answer: the
strategy, its parameters, the data version, and the cost model. Miss any of
those and a stale result gets served as a fresh one — which is worse than no
cache at all, because it is a wrong number wearing a right number's clothes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from eulerlab.paths import data_path

CACHE_DIR = data_path("derived/backtest_cache")


def data_version() -> str:
    """A stamp that changes whenever the panel changes.

    Size and mtime rather than a content hash of 540 MB: hashing the panel on
    every cache lookup would cost more than the backtest it is meant to save.
    The failure this risks is a panel edited without changing size *or* mtime,
    which no ordinary rebuild produces.
    """
    from eulerlab.features.panel import PANEL_PATH

    if not PANEL_PATH.exists():
        return "no-panel"
    stat = PANEL_PATH.stat()
    return hashlib.sha256(f"{PANEL_PATH}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[
        :16
    ]


def cost_model_version() -> str:
    """A stamp over the cost schedule.

    Costs move results, so a re-run under changed costs is a different answer
    and must not be served from cache. Hashing the source is crude but it
    cannot silently miss a rate change the way a hand-maintained version
    constant can.
    """
    from eulerlab.costs import schedule

    source = Path(str(schedule.__file__))
    if not source.exists():
        return "unknown"
    return hashlib.sha256(source.read_bytes()).hexdigest()[:16]


OUTCOME_SCHEMA = 3
"""Bumped whenever a run starts producing a field it did not produce before.

The cache key covers everything that could change the *answer*. It does not
cover what the answer *contains*, and that gap is not theoretical: equity
curves were added to the stored outcome, and every strategy with a cached entry
kept being served the older, curve-less version. Re-running looked like it did
nothing, because a cache hit is indistinguishable from a fast run.

Bumping this retires those entries. The cost is recomputation the numbers did
not strictly need; the alternative is an interface that silently cannot show a
field the code demonstrably produces.

1 -> 2: added `curve`, the downsampled equity path.
2 -> 3: added `asset_class` and `cost_mode`, once crypto and funds became
runnable — a cached equity outcome reported `cost_mode: null`, which reads as
"unknown" for a run that certainly paid realistic costs.
2 -> 3: added `universe`, `universe_size` and `symbols`.
"""


def cache_key(strategy_id: str, params: dict[str, object]) -> str:
    """Everything that could change the answer, and nothing that cannot.

    `sort_keys` for the same reason the ledger hashes that way: dict ordering
    must not change the key, or a harmless refactor silently empties the cache.
    """
    material = json.dumps(
        {
            "strategy": strategy_id,
            "params": params,
            "data": data_version(),
            "costs": cost_model_version(),
            "schema": OUTCOME_SCHEMA,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Item:
    """One configuration to evaluate."""

    strategy_id: str
    params: dict[str, object] = field(default_factory=dict)

    def key(self) -> str:
        return cache_key(self.strategy_id, self.params)


@dataclass
class Outcome:
    item: Item
    cached: bool
    result: dict[str, object] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class Batch:
    """What a run did, including what it did without paying for it."""

    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def cached(self) -> int:
        return sum(1 for o in self.outcomes if o.cached)

    @property
    def computed(self) -> int:
        return sum(1 for o in self.outcomes if not o.cached and o.ok)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if not o.ok)

    @property
    def unrecorded(self) -> int:
        """Configurations evaluated that the trial ledger will never know about.

        Equal to `computed`, and named separately because the two mean
        different things. `computed` is a performance fact. `unrecorded` is an
        honesty fact: this much search happened and the bar did not move.
        """
        return self.computed


def read_cached(key: str, *, directory: Path = CACHE_DIR) -> dict[str, object] | None:
    path = directory / f"{key}.json"
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt cache entry is a miss, never an error. The result can
        # always be recomputed, and refusing to run because a cache file is
        # damaged would make an optimisation into a dependency.
        return None
    return dict(loaded) if isinstance(loaded, dict) else None


def write_cached(key: str, result: dict[str, object], *, directory: Path = CACHE_DIR) -> None:
    """Cache one result, minus anything the run wants to hand on but not store.

    **Keys beginning with an underscore are dropped.** They carry live objects
    for the caller to consume once — the intraday runner passes report material
    this way, holding `date`s and dataclass instances, and `json.dumps` refused
    it: `TypeError: Object of type date is not JSON serializable`, which failed
    the whole backtest rather than just the caching of it.

    Dropping them is not a workaround for the serialiser, it is what the cache
    means. A cache hit says *this run did not happen again*, so there is no new
    report to write and nothing for that material to be used for. Storing it
    would preserve a side effect that is only correct the first time.

    Anything else that will not serialise is a real defect and still raises
    here. The rule is about privacy, not about convenience.
    """
    directory.mkdir(parents=True, exist_ok=True)
    storable = {key_: value for key_, value in result.items() if not key_.startswith("_")}
    (directory / f"{key}.json").write_text(json.dumps(storable, sort_keys=True), encoding="utf-8")
