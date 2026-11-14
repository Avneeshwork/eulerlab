"""Every screened rule, pass or fail, scored forward: the research process's own haircut (#156, ADR-193).

The platform did not know how much its backtests shrink out of sample, so a
screen Sharpe of 2 meant nothing measurable. Forward evidence came only from
the few books the operator starts. Here every rule the experiment store can
rebuild is re-scored each evening on the sessions since the forward period
began (`constitution.periods.forward_start`), compute only, no capital, into a
table of its own (`data/derived/forward_shadow.jsonl`). Nothing that finds or
tunes a rule reads it: the agents' tools read the experiment store only.

    the population   every fingerprint in the experiment store with a figure
                     (screen or sweep), rebuilt from the row's own `spec`
                     (recorded since 2026-11-14), its card, or research 176's
                     reference rules; cards first, then a sample stable by hash
    each evening     one shadow row per rule: forward Sharpe, trades, net bps,
                     and the same since the rule was first recorded
    the report       forward Sharpe on backtest Sharpe across the population:
                     the slope is the haircut, with a bootstrap 95% interval;
                     rank correlation (does a higher screen score predict more?);
                     by idea source, family, holding period, score bucket

`expected_live(sharpe)` turns a backtest Sharpe into the measured forward one,
once the report has 200 rules with 60 forward sessions each. Until then it
says so and returns None.
"""

from __future__ import annotations

import argparse
import hashlib
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from eulerlab.db.stream import add_row, read_rows
from eulerlab.intraday import rule_engine
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path
from eulerlab.research import experiments

PATH = "derived/forward_shadow.jsonl"
KIND = "forward_shadow"
REPORT = "derived/forward_haircut.md"
MAX_RULES = 400
"""Rules scored an evening: cards first, then a sample stable by fingerprint hash."""
WARMUP_DAYS = 400
"""Calendar days of history loaded before the forward start, for windows such as a 250-session high."""
MIN_SESSIONS = 60
MIN_RULES = 200
BOOTSTRAP = 1000
SCORED = ("screen", "sweep")
"""Purposes whose figure is a rule's backtest score."""

# ASSUMPTION: A-153 — 200 rules with 60 forward sessions each are enough to read a haircut.


def _path(path: Path | None) -> Path:
    return path if path is not None else data_path(PATH)


@dataclass(frozen=True)
class Candidate:
    fingerprint: str
    spec: rule_engine.Rule
    hypothesis: str
    source: str
    family: str
    backtest_sharpe: float
    recorded: date


def spec_from(body: Mapping[str, Any]) -> rule_engine.Rule | None:
    """A rule from its model dump: language v2 when it has a `shape`, else the engine's own."""
    try:
        if "shape" in body:
            if body.get("shape") == "combined":
                return None  # a combined book is refitted, not replayed (S-072)
            from eulerlab.research import lang

            return lang.Spec.model_validate(dict(body))
        return rule_engine.RuleSpec.model_validate(dict(body))
    except ValueError:
        return None


def population(
    rows: Iterable[Mapping[str, Any]] | None = None, root: Path = rule_engine.HYPOTHESES
) -> list[Candidate]:
    """Every rule the store has a backtest figure for and can rebuild, by fingerprint."""
    found = list(experiments.rows() if rows is None else rows)
    references = {s.fingerprint(): (h, s) for h, s in rule_engine.reference_specs().items()}
    first: dict[str, date] = {}
    latest: dict[str, Mapping[str, Any]] = {}
    specs: dict[str, rule_engine.Rule] = {}
    for row in found:
        fp = str(row.get("fingerprint") or "")
        if not fp or row.get("purpose") not in SCORED:
            continue
        at = datetime.fromisoformat(str(row["at"])).date()
        first[fp] = min(first.get(fp, at), at)
        if (row.get("metrics") or {}).get("net_sharpe") is not None:
            latest[fp] = row
        if fp not in specs and isinstance(row.get("spec"), dict):
            spec = spec_from(row["spec"])
            if spec is not None and spec.fingerprint() == fp:
                specs[fp] = spec
    out: list[Candidate] = []
    for fp, row in latest.items():
        h = str(row.get("hypothesis") or "")
        spec = specs.get(fp)
        if spec is None and h:
            try:
                spec = rule_engine.card_spec(h, root)
            except ValueError:
                spec = None
        if spec is None and fp in references:
            h, spec = references[fp]
        if spec is None or spec.fingerprint() != fp:
            continue
        out.append(
            Candidate(
                fp,
                spec,
                h,
                str(row.get("asked_by") or "unknown"),
                str(row.get("family") or ""),
                float(row["metrics"]["net_sharpe"]),
                first[fp],
            )
        )
    return out


def sample(candidates: Sequence[Candidate], limit: int = MAX_RULES) -> list[Candidate]:
    """Cards first, then the rest in an order fixed by each fingerprint's hash.

    The same rules are tracked every evening, and a new rule joins only by its
    own hash, not by when it arrived."""

    def order(c: Candidate) -> tuple[int, str]:
        return (0 if c.hypothesis else 1, hashlib.sha256(c.fingerprint.encode()).hexdigest())

    return sorted(candidates, key=order)[:limit]


# --- scoring -------------------------------------------------------------------------------


def forward_engine(data: rule_engine.Data, start: date, store: Any = None) -> Any:
    """A fast engine on `data` that enters nothing before `start` and counts no session before it."""
    from eulerlab.research import fast_eval

    class From(fast_eval.FastEngine):
        def events(self, spec: rule_engine.Rule) -> list[rule_engine.Event]:
            return [e for e in super().events(spec) if e[0] >= start]

        def window(self, spec: rule_engine.Rule) -> list[date]:
            return [d for d in super().window(spec) if d >= start]

    return From(data, store)


def _stats(values: Sequence[float]) -> dict[str, Any]:
    found = sc.daily_stats(list(values)) if values else {"days": 0, "sharpe": None}
    return {
        "sessions": found["days"],
        "sharpe": found["sharpe"],
        "total": found.get("total_return"),
    }


def score(candidates: Sequence[Candidate], engine: Any, start: date) -> list[dict[str, Any]]:
    """One shadow row per rule. A rule the engine cannot score says why, and is not dropped."""
    out: list[dict[str, Any]] = []
    for c in candidates:
        base = {
            "fingerprint": c.fingerprint,
            "hypothesis": c.hypothesis,
            "source": c.source,
            "family": c.family,
            "kind": c.spec.kind,
            "hold": c.spec.hold,
            "rule": c.spec.describe()[:200],
            "backtest_sharpe": c.backtest_sharpe,
            "recorded": c.recorded.isoformat(),
            "forward_start": start.isoformat(),
        }
        try:
            screen = engine.screen(c.spec)
        except Exception as exc:  # one broken rule must not stop the evening
            out.append({**base, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            continue
        daily = engine.returns.pop(c.spec.fingerprint(), {})
        days = sorted(d for d in daily if d >= start)
        whole = _stats([daily[d] for d in days])
        since = _stats([daily[d] for d in days if d > c.recorded])
        out.append(
            {
                **base,
                "through": days[-1].isoformat() if days else None,
                "trades": screen.get("count"),
                "net_bps_each": (screen.get("per_bps") or {}).get("net_mean"),
                "forward_sessions": whole["sessions"],
                "forward_sharpe": whole["sharpe"],
                "forward_total": whole["total"],
                "since_recorded": since,
            }
        )
    return out


def run(
    *,
    through: date | None = None,
    limit: int = MAX_RULES,
    engine: Any = None,
    candidates: Sequence[Candidate] | None = None,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """The evening's shadow: score the sample and append one row per rule."""
    from eulerlab import constitution

    start = constitution.load().periods.forward_start
    stamp = now or datetime.now(UTC)
    if engine is None:
        day = through or stamp.date()
        data = rule_engine.LiveData(since=start - timedelta(days=WARMUP_DAYS), through=day)
        engine = forward_engine(data, start)
    chosen = sample(population() if candidates is None else candidates, limit)
    found = score(chosen, engine, start)
    at = stamp.isoformat(timespec="seconds")
    for row in found:
        add_row(_path(path), KIND, {"at": at, **row})
    return {
        "rules": len(found),
        "errors": sum(1 for r in found if "error" in r),
        "forward_start": start.isoformat(),
    }


# --- the report ----------------------------------------------------------------------------


def latest(path: Path | None = None) -> list[dict[str, Any]]:
    """Each rule's newest shadow row."""
    out: dict[str, dict[str, Any]] = {}
    for row in read_rows(_path(path), KIND):
        out[str(row["fingerprint"])] = row
    return list(out.values())


def _usable(rows: Iterable[Mapping[str, Any]], min_sessions: int) -> list[Mapping[str, Any]]:
    return [
        r
        for r in rows
        if r.get("forward_sharpe") is not None
        and r.get("backtest_sharpe") is not None
        and (r.get("forward_sessions") or 0) >= min_sessions
    ]


def _rank(x: np.ndarray[Any, np.dtype[np.float64]]) -> np.ndarray[Any, np.dtype[np.float64]]:
    order = np.argsort(x, kind="stable")
    out = np.empty(len(x))
    out[order] = np.arange(len(x))
    return out


def haircut(
    rows: Iterable[Mapping[str, Any]], *, min_sessions: int = MIN_SESSIONS, seed: int = 0
) -> dict[str, Any]:
    """Forward Sharpe on backtest Sharpe across rules: slope (the haircut) with a bootstrap 95%
    interval, intercept, rank correlation, and the median share of a good backtest kept."""
    used = _usable(rows, min_sessions)
    n = len(used)
    out: dict[str, Any] = {"rules": n, "min_sessions": min_sessions, "enough": n >= MIN_RULES}
    if n < 3:
        return out
    bt = np.array([float(r["backtest_sharpe"]) for r in used])
    fw = np.array([float(r["forward_sharpe"]) for r in used])
    if bt.std() == 0:
        return out
    slope, intercept = (float(v) for v in np.polyfit(bt, fw, 1))
    rng = np.random.default_rng(seed)
    slopes = []
    for _ in range(BOOTSTRAP):
        pick = rng.integers(0, n, n)
        if bt[pick].std() > 0:
            slopes.append(float(np.polyfit(bt[pick], fw[pick], 1)[0]))
    good = bt > 0.5
    rho = float(np.corrcoef(_rank(bt), _rank(fw))[0, 1]) if fw.std() > 0 else None
    out |= {
        "slope": round(slope, 3),
        "slope_ci": [round(float(np.percentile(slopes, q)), 3) for q in (2.5, 97.5)],
        "intercept": round(intercept, 3),
        "rank_correlation": round(rho, 3) if rho is not None else None,
        "median_kept_share": round(float(np.median(fw[good] / bt[good])), 3)
        if good.any()
        else None,
        "mean_backtest": round(float(bt.mean()), 3),
        "mean_forward": round(float(fw.mean()), 3),
    }
    return out


def _hold_bucket(row: Mapping[str, Any]) -> str:
    hold = int(row.get("hold") or 0)
    if row.get("kind") == "intraday":
        return "intraday"
    return "swing 2-5" if hold <= 5 else "swing 6-20" if hold <= 20 else "swing 21-60"


def breakdown(
    rows: Iterable[Mapping[str, Any]], key: str, *, min_sessions: int = MIN_SESSIONS
) -> list[dict[str, Any]]:
    """Mean backtest and forward Sharpe for each value of `key`: source, family, hold or score."""
    used = _usable(rows, min_sessions)
    scores = [float(r["backtest_sharpe"]) for r in used]
    cuts = np.quantile(scores, [0.2, 0.4, 0.6, 0.8]) if scores else np.array([])

    def of(r: Mapping[str, Any]) -> str:
        if key == "score":
            return f"quintile {1 + int(np.searchsorted(cuts, float(r['backtest_sharpe'])))}"
        if key == "hold":
            return _hold_bucket(r)
        return str(r.get(key) or "unknown")

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in used:
        groups[of(r)].append(r)
    return [
        {
            key: name,
            "rules": len(g),
            "backtest": round(statistics.fmean(float(r["backtest_sharpe"]) for r in g), 3),
            "forward": round(statistics.fmean(float(r["forward_sharpe"]) for r in g), 3),
        }
        for name, g in sorted(groups.items())
    ]


def expected_live(backtest_sharpe: float, found: Mapping[str, Any] | None = None) -> float | None:
    """The forward Sharpe the measured haircut predicts, or None before the report is enough."""
    report = haircut(latest()) if found is None else found
    if not report.get("enough") or report.get("slope") is None:
        return None
    return round(float(report["intercept"]) + float(report["slope"]) * backtest_sharpe, 3)


def markdown(rows: Sequence[Mapping[str, Any]], *, min_sessions: int = MIN_SESSIONS) -> str:
    h = haircut(rows, min_sessions=min_sessions)
    lines = [
        "# Forward haircut (#156, ADR-193)",
        "",
        f"Rules with at least {min_sessions} forward sessions: {h['rules']} "
        f"(the report is read once there are {MIN_RULES}). Shadow rows: {len(rows)}.",
        "",
    ]
    if h.get("slope") is None:
        lines.append("Not enough rules with forward sessions yet to fit a line.")
        return "\n".join(lines) + "\n"
    lines += [
        f"- Haircut (slope of forward on backtest Sharpe): **{h['slope']}**, "
        f"95% interval {h['slope_ci'][0]} to {h['slope_ci'][1]}; intercept {h['intercept']}.",
        f"- Rank correlation of screen score and forward Sharpe: {h['rank_correlation']}. "
        "Near zero means the screen does not select.",
        f"- Median share of a backtest Sharpe above 0.5 kept forward: {h['median_kept_share']}.",
        f"- Mean backtest {h['mean_backtest']}, mean forward {h['mean_forward']}.",
        "",
    ]
    for key in ("source", "family", "hold", "score"):
        part = breakdown(rows, key, min_sessions=min_sessions)
        lines += [
            f"## By {key}",
            "",
            f"| {key} | rules | backtest | forward |",
            "|---|---|---|---|",
        ]
        lines += [f"| {r[key]} | {r['rules']} | {r['backtest']} | {r['forward']} |" for r in part]
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, runner: Callable[..., dict[str, Any]] = run) -> int:
    parser = argparse.ArgumentParser(prog="make forward-shadow", description=__doc__)
    parser.add_argument("--report", action="store_true", help="write the haircut report only")
    parser.add_argument("--limit", type=int, default=MAX_RULES)
    args = parser.parse_args(argv)
    if not args.report:
        print(runner(limit=args.limit))
    text = markdown(latest())
    target = data_path(REPORT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
