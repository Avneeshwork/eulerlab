"""The fast evaluator: one table of point-in-time fields, many rules scored in one pass (ADR-175).

`rule_engine.Engine` works out every signal again for every rule: a Python
call per stock per session per condition. A search that tries a thousand
rules a night cannot afford that. Here each field is worked out once into a
table (sessions down, stocks across), a rule's entries come from array
arithmetic on those tables (`research/lang.py`), and the entries then go
through the engine's own books, costs and checks. So the numbers are the
engine's numbers:

    Store(engine)        the tables, each cell `engine.value(...)` at lag 0
    FastEngine(data)     an Engine whose `events` reads the tables
    evaluate(specs, ..)  screens a batch, records each in the experiment store

**The tables are filled by the engine's own `value`**, one field at a time,
so a field can never mean something different here. A lag is a shift of the
table by that many sessions, which is what `Data.prev` does.

**Kept on disk** as Parquet, one file per field, under
`data/derived/feature_store/<version>/`: session, symbol, value, event_time
and knowledge_time. `version` names the data the tables were built from.

    uv run python -m eulerlab.research.fast_eval --count 1000     how fast is it here
"""

from __future__ import annotations

import argparse
import hashlib
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from datetime import time as clock
from functools import cached_property
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import NDArray

from eulerlab.intraday import rule_engine
from eulerlab.llm import cutoff
from eulerlab.paths import data_path
from eulerlab.research import experiments, lang

IST = ZoneInfo("Asia/Kolkata")
OPEN, CLOSE = clock(9, 15), clock(15, 30)


def store_dir() -> Path:
    return data_path("derived/feature_store")


class Store:
    """Every field as a table over the engine's sessions and its liquid stocks."""

    def __init__(
        self,
        engine: rule_engine.Engine,
        *,
        cache: Path | None = None,
        market: dict[str, dict[date, float]] | None = None,
        sectors: dict[str, str] | None = None,
        judged_by: dict[str, set[str]] | None = None,
    ) -> None:
        self.engine = engine
        data = engine.data
        self.days: Sequence[date] = list(data.sessions)
        names: set[str] = set()
        for members in data.liquid.values():
            names |= members
        self.symbols: Sequence[str] = sorted(names)
        self._cache = cache
        self._market = market or {}
        self._sectors = sectors or {}
        self.judged_by = judged_by or {}
        """For each model-judged field, the models whose judgements fill it (ADR-176)."""
        self._tables: dict[tuple[str, int], lang.Matrix] = {}

    @cached_property
    def version(self) -> str:
        """Names the data: its sessions, its stocks, where the window ends and, for tables
        kept on disk, the content hash of the input files (#154, S-064), so a restated
        history with the same shape builds new tables instead of reusing stale ones."""
        from eulerlab.research import data_manifest

        d = self.engine.data
        body = f"{self.days[0]}|{self.days[-1]}|{len(self.days)}|{len(self.symbols)}|{d.end}"
        if self._cache is not None:
            body += f"|{data_manifest.version()}"
        return hashlib.sha256(body.encode()).hexdigest()[:12]

    @cached_property
    def tradable(self) -> NDArray[np.bool_]:
        d = self.engine.data
        col = {s: j for j, s in enumerate(self.symbols)}
        out = np.zeros((len(self.days), len(self.symbols)), dtype=np.bool_)
        for t, day in enumerate(self.days):
            for symbol in d.liquid.get(day, frozenset()):
                if d.tradable(symbol, day):
                    out[t, col[symbol]] = True
        return out

    @cached_property
    def ok_day(self) -> NDArray[np.bool_]:
        d = self.engine.data
        short = self.engine.short
        return np.array(
            [day <= d.end and d.prev(day) is not None and day not in short for day in self.days]
        )

    def groups(self) -> NDArray[np.int64]:
        codes = {name: i for i, name in enumerate(sorted(set(self._sectors.values())))}
        return np.array([codes.get(self._sectors.get(s, ""), -1) for s in self.symbols])

    def _file(self, name: str, n: int) -> Path | None:
        if self._cache is None:
            return None
        return self._cache / self.version / f"{name}{'_' + str(n) if n != 1 else ''}.parquet"

    def field(self, name: str, n: int = 1) -> lang.Matrix:
        key = (name, n)
        if key not in self._tables:
            path = self._file(name, n)
            if path is not None and path.exists():
                self._tables[key] = self._read(path)
            else:
                self._tables[key] = self._build(name, n)
                if path is not None:
                    self._write(path, name, self._tables[key])
        return self._tables[key]

    def _build(self, name: str, n: int) -> lang.Matrix:
        out = np.full((len(self.days), len(self.symbols)), np.nan)
        if name in self._market or lang.FIELDS[name].market_wide:
            series = self._market.get(name, {})
            for t, day in enumerate(self.days):
                if day in series:
                    out[t, :] = series[day]
            return out
        if name in lang.RAW_FIELDS:
            attr = {"open_price": "open", "close_price": "close", "traded_value": "value"}[name]
            panel = self.engine.data.panel
            for j, symbol in enumerate(self.symbols):
                bars = panel.get(symbol, {})
                for t, day in enumerate(self.days):
                    bar = bars.get(day)
                    if bar is not None:
                        out[t, j] = float(getattr(bar, attr))
            return out
        # Lag 0 on purpose: the table holds each session's own value, and a rule
        # reads it through `delay`, which `lang.check_lookahead` has already checked.
        signal = rule_engine.Signal.model_construct(
            signal=cast(rule_engine.SignalName, name), lag=0, n=n, absolute=False
        )
        value = self.engine.value
        for j, symbol in enumerate(self.symbols):
            for t, day in enumerate(self.days):
                v = value(signal, symbol, day)
                if v is not None:
                    out[t, j] = v
        return out

    def _write(self, path: Path, name: str, table: lang.Matrix) -> None:
        where = np.nonzero(~np.isnan(table))
        rows, cols = where[0].tolist(), where[1].tolist()
        at_close = lang.FIELDS[name].min_lag > 0
        stamp = [
            datetime.combine(self.days[t], CLOSE if at_close else OPEN, IST).astimezone(UTC)
            for t in rows
        ]
        found = pa.table(
            {
                "session": [self.days[t] for t in rows],
                "symbol": [self.symbols[j] for j in cols],
                "value": table[rows, cols].tolist(),
                "event_time": stamp,
                "knowledge_time": stamp,
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(found, path)

    def _read(self, path: Path) -> lang.Matrix:
        found = pq.read_table(path).to_pydict()
        row = {d: t for t, d in enumerate(self.days)}
        col = {s: j for j, s in enumerate(self.symbols)}
        out = np.full((len(self.days), len(self.symbols)), np.nan)
        for day, symbol, v in zip(found["session"], found["symbol"], found["value"], strict=True):
            out[row[day], col[symbol]] = v
        return out


def market_series(sessions: Sequence[date]) -> dict[str, dict[date, float]]:
    """The market-wide fields, each value on the first session it was known by.

    FII and DII cash flows carry a knowledge time and are placed by it. The
    participant positions file has only its report date.
    """
    import bisect

    from eulerlab.ingest import fii_dii_cash
    from eulerlab.strategies.studies import fii_participant_oi as oi

    out: dict[str, dict[date, float]] = {
        name: {} for name, f in lang.FIELDS.items() if f.market_wide
    }
    if not sessions:
        return out
    for row in fii_dii_cash.rows():
        known = datetime.fromisoformat(str(row["knowledge_time"])).astimezone(IST).date()
        i = bisect.bisect_left(sessions, max(known, date.fromisoformat(str(row["day"]))))
        if i < len(sessions):
            for name in ("fii_net", "dii_net"):
                if row.get(name) is not None:
                    out[name][sessions[i]] = float(row[name])
    # ASSUMPTION: A-137 — NSE publishes participant open interest the evening of its date.
    for day, nets in oi.load_positions(start=sessions[0], end=sessions[-1]).items():
        out["fii_futures_net"][day] = float(nets["FII"])
        out["dii_futures_net"][day] = float(nets["DII"])
    return out


def real_store(engine: rule_engine.Engine) -> Store:
    """The store on the platform's own data: market fields, sectors, and tables kept on disk.

    Only the research data's tables are kept on disk. A paper book's engine
    reads a window that moves every day, and would leave a new set each time.
    """
    from eulerlab.fundamentals import sectors

    impact, models = cutoff.series("news_impact")
    return Store(
        engine,
        cache=store_dir() if type(engine.data) is rule_engine.Data else None,
        market={**market_series(engine.data.sessions), "news_impact": impact},
        judged_by={"news_impact": models},
        sectors={symbol: tag.sector for symbol, tag in sectors.load().items()},
    )


class FastEngine(rule_engine.Engine):
    """An engine whose entries come from the tables. Books, costs and checks are inherited."""

    def __init__(
        self,
        data: rule_engine.Data,
        store: Store | None = None,
        prices: Any = None,
    ) -> None:
        super().__init__(data, prices)
        self.store = store or real_store(self)
        self.evaluator = lang.Evaluator(self.store)

    def events(self, spec: rule_engine.Rule) -> list[rule_engine.Event]:
        v2 = lang.from_rule(spec) if isinstance(spec, rule_engine.RuleSpec) else spec
        assert isinstance(v2, lang.Spec)
        return _events(v2, self.store, self.evaluator)


def _events(spec: lang.Spec, store: Store, evaluator: lang.Evaluator) -> list[rule_engine.Event]:
    for name in spec.complexity["fields"]:
        if lang.FIELDS[name].judged:
            # A model's judgement is no signal on sessions it may have read about.
            for model in sorted(store.judged_by.get(name) or {""}):
                cutoff.require_after(model, spec.first, what=name)
    return lang.events(spec, evaluator, store.tradable, store.ok_day)


def events_for(engine: rule_engine.Engine, spec: rule_engine.Rule) -> list[rule_engine.Event]:
    """A v2 rule's entries on any engine: its tables are built once and kept on the engine."""
    assert isinstance(spec, lang.Spec)
    kept = engine.__dict__.get("_tables")
    if kept is None:
        store = real_store(engine)
        kept = engine.__dict__["_tables"] = (store, lang.Evaluator(store))
    return _events(spec, *kept)


def _dump(spec: rule_engine.Rule) -> dict[str, Any] | None:
    dump = getattr(spec, "model_dump", None)
    return dump(mode="json") if callable(dump) else None


# --- many rules across cores, with the slow engine as referee (#167, ADR-195) ---------------

_SHARED: dict[str, Any] = {}
"""The engine a worker screens with: inherited by a forked worker, sent once to a spawned one."""


def _share(engine: rule_engine.Engine) -> None:
    _SHARED["engine"] = engine


def _screen_chunk(
    chunk: Sequence[rule_engine.Rule],
) -> list[tuple[dict[str, Any], dict[date, float]]]:
    engine = _SHARED["engine"]
    out = []
    for spec in chunk:
        found = engine.screen(spec)
        out.append((found, engine.returns.pop(spec.fingerprint(), {})))
    return out


def _context() -> Any:
    import multiprocessing as mp
    import sys

    # macOS's system libraries are not fork-safe, which is why Python spawns there.
    method = "fork" if sys.platform == "linux" else "spawn"
    return mp.get_context(method)


def screen_many(
    specs: Sequence[rule_engine.Rule], engine: rule_engine.Engine, *, workers: int = 1
) -> list[tuple[dict[str, Any], dict[date, float]]]:
    """(screen, daily returns) for every spec, in the order given, across `workers` processes.

    Each worker screens contiguous chunks with its own copy of the engine, so the
    figures are byte-identical to one process's. A pool that cannot start (an
    engine that cannot be sent to a spawned worker) falls back to one process."""
    if workers <= 1 or len(specs) < 2 * workers:
        _share(engine)
        return _screen_chunk(specs)
    from concurrent.futures import ProcessPoolExecutor

    size = max(1, -(-len(specs) // (workers * 4)))
    chunks = [list(specs[i : i + size]) for i in range(0, len(specs), size)]
    _share(engine)
    try:
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=_context(), initializer=_share, initargs=(engine,)
        ) as pool:
            parts = list(pool.map(_screen_chunk, chunks))
    except Exception:
        return _screen_chunk(specs)
    return [x for part in parts for x in part]


PARITY = "derived/parity.jsonl"
PARITY_KIND = "parity"
COMPARED = ("count", "per_bps", "passes_screen", "clean")


def referee(
    specs: Sequence[rule_engine.Rule],
    found: Sequence[Mapping[str, Any]],
    data: rule_engine.Data,
    *,
    share: float = 0.01,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Re-screen a sample of the engine rules with the slow engine; any difference is a row.

    The sample is fixed by each fingerprint's hash, so a rule is always in it or
    never. Language-v2 rules have no slow path of their own and are not refereed."""
    from eulerlab.db.stream import add_row

    slow = rule_engine.Engine(data)
    cut = int(share * 0xFFFF)
    checked = mismatched = 0
    for spec, fast in zip(specs, found, strict=True):
        fp = spec.fingerprint()
        if not isinstance(spec, rule_engine.RuleSpec) or int(fp[:4], 16) > cut:
            continue
        checked += 1
        ref = slow.screen(spec)
        slow.returns.pop(fp, None)
        diff = {k: (fast.get(k), ref.get(k)) for k in COMPARED if fast.get(k) != ref.get(k)}
        net = ((fast.get("net") or {}).get("sharpe"), (ref.get("net") or {}).get("sharpe"))
        if net[0] != net[1]:
            diff["net_sharpe"] = net
        if diff:
            mismatched += 1
            add_row(
                path or data_path(PARITY),
                PARITY_KIND,
                {
                    "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
                    "fingerprint": fp,
                    "rule": spec.describe()[:200],
                    "diff": {k: list(v) for k, v in diff.items()},
                },
            )
    return {"checked": checked, "mismatched": mismatched}


def evaluate(
    specs: Sequence[rule_engine.Rule],
    engine: rule_engine.Engine,
    *,
    asked_by: str,
    family: str = "",
    parents: dict[str, Sequence[str]] | None = None,
    record: bool = True,
    now: datetime | None = None,
    workers: int = 1,
) -> list[dict[str, Any]]:
    """Screen every spec. Each result carries its `daily` returns and, when recorded, its `id`."""
    out: list[dict[str, Any]] = []
    for spec, (found, daily) in zip(
        specs, screen_many(specs, engine, workers=workers), strict=True
    ):
        found["daily"] = daily
        if record:
            found["id"] = experiments.record(
                purpose="sweep",
                fingerprint=spec.fingerprint(),
                family=family,
                first=spec.first,
                end=min(engine.data.end, engine.data.sessions[-1]),
                metrics={
                    "count": found.get("count"),
                    "net_sharpe": (found.get("net") or {}).get("sharpe"),
                    "passes_screen": found.get("passes_screen"),
                    "clean": found.get("clean"),
                },
                daily=daily or None,
                parents=tuple((parents or {}).get(spec.fingerprint(), ())),
                asked_by=asked_by,
                now=now,
                spec=_dump(spec),
            )
        out.append(found)
    return out


def bench(count: int, data: rule_engine.Data | None = None, workers: int = 1) -> dict[str, Any]:
    """Seconds to build the tables and to screen `count` fixed-rule candidates, unrecorded."""
    from eulerlab.agents.workers import autopilot as writer

    began = time.monotonic()
    engine = FastEngine(data or rule_engine.Data())
    specs: list[rule_engine.RuleSpec] = []
    known: dict[str, str] = {}
    for seed in range(50):
        if len(specs) >= count:
            break
        for card in writer.fallback(count - len(specs), seed, known):
            specs.append(card["spec"])
            known[card["spec"].fingerprint()] = "bench"
    evaluate(specs[:1], engine, asked_by="bench", record=False)
    built = time.monotonic() - began
    began = time.monotonic()
    evaluate(specs, engine, asked_by="bench", record=False, workers=workers)
    took = time.monotonic() - began
    return {
        "candidates": len(specs),
        "workers": workers,
        "first_seconds": round(built, 1),
        "seconds": round(took, 1),
        "per_hour": round(len(specs) / took * 3600) if took else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fast-eval", description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=1, help="processes; 0 for every core")
    args = parser.parse_args(argv)
    import os

    found = bench(args.count, workers=args.workers or os.cpu_count() or 1)
    print(
        f"{found['candidates']} candidates on {found['workers']} process(es) in {found['seconds']} s "
        f"({found['per_hour']} an hour); the first one, with its tables, took "
        f"{found['first_seconds']} s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
