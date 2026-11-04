"""Next-session forecast for Nifty 50: range, close band, odds of a higher open and close (ADR-133).

What the brief says about the next session, as numbers that are checked the
day after. Every run refits three models on data known before the session they
forecast (research 147):

1. **Range.** The session's high-low range, on a log scale, from the last
   day's, the last week's and the last month's ranges and India VIX: Corsi's
   (2009) HAR cascade applied to the range, which Parkinson (1980) and Chou
   (2005) show measures volatility well. Baseline: the range VIX alone implies.
2. **Close band.** The next close's log return divided by the forecast range,
   as past sessions spread: the 10th and 90th percentiles of that ratio give
   the 80% band.
3. **Odds of a higher open and a higher close.** Ridge logistic regressions on
   the last session's move, the last week's move, VIX's change and the
   distance from the 200-day average, fitted on all history; then a second
   stage on FII cash over five sessions and the US session that closed
   overnight, fitted where both are known (NSE research paper 39: the US
   session moves India's overnight return). Baseline: the base rate. The
   penalty is large on purpose: next-day direction is close to a coin flip
   (T-4042), so the odds stay near the base rate unless the data insists.

**Scored every day.** Each forecast is appended to `LOG` before the session it
forecasts. Once that session is held it is scored: the Brier score of the odds
against the base rate's, whether the close landed in the band, and the range
error against VIX's. When the direction model scores worse than the base rate
(live, or in the walk-forward check until there are `min_live` live scores),
the brief shows the base rate and says why.

**Updating.** Every run refits on everything known, recent sessions weighted
more (`half_life`). The settings in `config/next_session.yaml` are fixed, not
tuned to the score (A-102).

A forecast, not a signal: nothing in `deploy/`, `backtest/` or the gate reads
it, it logs no trial, and it reads daily index data only, never the minute-data
holdout.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import yaml
from pydantic import BaseModel, ConfigDict

from eulerlab.config import CONFIG_DIR

VERSION = "ns-1"
LABEL = "A forecast, scored every day. Nothing trades on it."
LOG = Path("data/derived/forecasts/next_session.jsonl")
INDEX_HISTORY = Path("data/derived/index_history.jsonl")
US_PANEL = Path("data/derived/us_panel.jsonl")
IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
# Expected high-low range over sigma for a driftless random walk (Parkinson 1980).
RANGE_PER_SIGMA = math.sqrt(8 / math.pi)

BASE = ("last_day", "last_week", "vix_change", "trend")
EXTRA = ("fii_week", "us_session")
SAY = {
    "last_day": "the last session's move",
    "last_week": "the last five sessions' move",
    "vix_change": "India VIX's change in the last session",
    "trend": "Nifty's distance from its 200-day average",
    "fii_week": "FII cash over five sessions",
    "us_session": "the US session that closed overnight",
    "recent": "the last year's sessions, which went this way",
}

Vector = npt.NDArray[np.float64]


class Setup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: str
    half_life: float
    ridge: float
    band: float
    check_sessions: int
    refit_every: int
    min_live: int
    live_window: int
    min_overlap: int


def setup(config_dir: Path | None = None) -> Setup:
    path = (config_dir or CONFIG_DIR) / "next_session.yaml"
    return Setup.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


# --- data -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    vix: float | None


def bars(path: Path = INDEX_HISTORY, *, as_of: datetime, start: str = "2015-01-01") -> list[Bar]:
    """Nifty 50's daily bars and India VIX's close, known at or before `as_of`."""
    out: dict[date, Bar] = {}
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            known = row.get("knowledge_time")
            if not known or datetime.fromisoformat(str(known)) > as_of or row["d"] < start:
                continue
            cells = row.get("indices") or {}
            n = cells.get("Nifty 50") or {}
            values = [n.get(k) for k in ("o", "h", "l", "c")]
            if not all(isinstance(v, int | float) and v > 0 for v in values):
                continue
            o, h, low, c = (float(v) for v in values)  # type: ignore[arg-type]
            vix = (cells.get("India VIX") or {}).get("c")
            day = date.fromisoformat(row["d"])
            # One row per day: the first known wins, as a reader at the time saw it.
            out.setdefault(
                day,
                Bar(day, o, max(h, o, c), min(low, o, c), c, float(vix) if vix else None),
            )
    return [out[d] for d in sorted(out)]


def fii_nets(as_of: datetime) -> dict[date, float]:
    """FII net cash per day, in crore, known at or before `as_of`."""
    from eulerlab.ingest import fii_dii_cash

    return {
        date.fromisoformat(str(r["day"])): float(r["fii_net"])
        for r in fii_dii_cash.rows(as_of=as_of)
    }


def spy_closes(path: Path = US_PANEL) -> dict[date, float]:
    """SPY's daily closes from the US panel. A US session's close is known before India opens."""
    out: dict[date, float] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if '"SPY"' not in line:
                continue
            row = json.loads(line)
            if row.get("s") == "SPY" and isinstance(row.get("c"), int | float):
                out[date.fromisoformat(row["d"])] = float(row["c"])
    return out


# --- features -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """What was known at the close of `day`, and what followed on `target` (None if not yet)."""

    day: date
    target: date | None
    close: float
    x: dict[str, float | None]
    rx: tuple[float, ...] | None
    up: float | None = None
    gap_up: float | None = None
    ret: float | None = None
    gap: float | None = None
    log_range: float | None = None


def _log_range(b: Bar) -> float | None:
    return math.log(math.log(b.high / b.low)) if b.high > b.low else None


def fii_week(fii: Mapping[date, float], days: Sequence[date], day: date) -> float | None:
    """FII net over the five sessions to `day`, when `day` itself is captured."""
    if day not in fii:
        return None
    i = bisect.bisect_right(days, day)
    picked = days[max(0, i - 5) : i]
    return sum(fii[d] for d in picked) if len(picked) == 5 else None


def us_session(
    spy: Mapping[date, float], days: Sequence[date], last: date, target: date
) -> float | None:
    """The log return of the last US session that closed after India's `last` close and before `target`.

    0.0 when the US held no session in between and its data runs past it;
    None when the US data does not reach that far.
    """
    i = bisect.bisect_left(days, target) - 1
    if i < 1:
        return None
    if days[i] >= last:
        return math.log(spy[days[i]] / spy[days[i - 1]])
    return 0.0 if days[-1] >= target else None


def table(
    history: Sequence[Bar],
    fii: Mapping[date, float],
    spy: Mapping[date, float],
    *,
    next_target: date | None = None,
) -> list[Row]:
    """One row per session with 200 sessions behind it. The last row's target is `next_target`."""
    closes = [b.close for b in history]
    ranges = [_log_range(b) for b in history]
    fii_days = sorted(fii)
    spy_days = sorted(spy)
    rows: list[Row] = []
    for i in range(200, len(history)):
        b, before = history[i], history[i - 1]
        target = history[i + 1].day if i + 1 < len(history) else next_target
        sma = sum(closes[i - 199 : i + 1]) / 200
        x: dict[str, float | None] = {
            "last_day": math.log(b.close / before.close),
            "last_week": math.log(b.close / closes[i - 5]),
            "vix_change": math.log(b.vix / before.vix) if b.vix and before.vix else None,
            "trend": b.close / sma - 1,
            "fii_week": fii_week(fii, fii_days, b.day),
            "us_session": us_session(spy, spy_days, b.day, target) if target else None,
        }
        week = [r for r in ranges[i - 4 : i + 1] if r is not None]
        month = [r for r in ranges[i - 21 : i + 1] if r is not None]
        today = ranges[i]
        rx = (
            (1.0, today, sum(week) / len(week), sum(month) / len(month), math.log(b.vix))
            if today is not None and week and month and b.vix
            else None
        )
        row = Row(b.day, target, b.close, x, rx)
        if i + 1 < len(history):
            n = history[i + 1]
            row = Row(
                b.day,
                target,
                b.close,
                x,
                rx,
                up=float(n.close > b.close),
                gap_up=float(n.open > b.close),
                ret=math.log(n.close / b.close),
                gap=math.log(n.open / b.close),
                log_range=_log_range(n),
            )
        rows.append(row)
    return rows


# --- models ---------------------------------------------------------------------------------------


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def weights(n: int, half_life: float) -> Vector:
    return np.asarray(0.5 ** ((n - 1 - np.arange(n)) / half_life), dtype=np.float64)


def _wls(x: Vector, y: Vector, w: Vector) -> Vector:
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(x * sw[:, None], y * sw, rcond=None)
    return np.asarray(beta, dtype=np.float64)


def weighted_quantile(values: Vector, w: Vector, q: float) -> float:
    order = np.argsort(values, kind="stable")
    v, cw = values[order], np.cumsum(w[order])
    return float(v[min(len(v) - 1, int(np.searchsorted(cw, q * cw[-1])))])


@dataclass(frozen=True)
class Logit:
    """A ridge logistic regression on standardised features; the intercept is not penalised."""

    names: tuple[str, ...]
    mean: tuple[float, ...]
    sd: tuple[float, ...]
    beta: tuple[float, ...]

    def parts(self, x: Mapping[str, float | None]) -> dict[str, float]:
        return {
            n: b * (float(x[n] or 0.0) - m) / s
            for n, m, s, b in zip(self.names, self.mean, self.sd, self.beta[1:], strict=True)
        }

    def eta(self, x: Mapping[str, float | None]) -> float:
        return self.beta[0] + sum(self.parts(x).values())

    def usable(self, x: Mapping[str, float | None]) -> bool:
        return all(x.get(n) is not None for n in self.names)


def fit_logit(
    names: Sequence[str],
    xs: Sequence[Mapping[str, float | None]],
    y: Vector,
    w: Vector,
    ridge: float,
    offset: Vector | None = None,
) -> Logit:
    raw = np.array([[float(x[n] or 0.0) for n in names] for x in xs], dtype=np.float64)
    total = float(w.sum())
    mean = (raw * w[:, None]).sum(axis=0) / total
    sd = np.sqrt(((raw - mean) ** 2 * w[:, None]).sum(axis=0) / total)
    sd = np.where(sd > 0, sd, 1.0)
    design = np.column_stack([np.ones(len(raw)), (raw - mean) / sd])
    off = offset if offset is not None else np.zeros(len(raw))
    penalty = np.diag([0.0] + [ridge] * len(names))
    beta = np.zeros(design.shape[1])
    for _ in range(100):
        p = 1 / (1 + np.exp(-(design @ beta + off)))
        hess = design.T @ (design * (w * p * (1 - p))[:, None]) + penalty
        step = np.linalg.solve(hess, design.T @ (w * (y - p)) - penalty @ beta)
        beta = beta + step
        if float(np.abs(step).max()) < 1e-10:
            break
    return Logit(
        tuple(names),
        tuple(float(v) for v in mean),
        tuple(float(v) for v in sd),
        tuple(float(v) for v in beta),
    )


@dataclass(frozen=True)
class Odds:
    """A first stage on all history and an optional second stage on flows and the US session."""

    first: Logit
    second: Logit | None
    base: float

    def predict(self, x: Mapping[str, float | None]) -> tuple[float, dict[str, float], bool]:
        """Probability, each feature's effect in probability points, and whether stage two ran."""
        parts = self.first.parts(x)
        eta = self.first.eta(x)
        both = self.second is not None and self.second.usable(x)
        if both and self.second is not None:
            parts |= self.second.parts(x) | {"recent": self.second.beta[0]}
            eta += self.second.eta(x)
        p = _sigmoid(eta)
        return p, {k: (p - _sigmoid(eta - v)) * 100 for k, v in parts.items()}, both


def _odds(rows: Sequence[Row], outcome: str, s: Setup) -> Odds:
    known = [
        r for r in rows if getattr(r, outcome) is not None and all(r.x[n] is not None for n in BASE)
    ]
    y = np.array([float(getattr(r, outcome)) for r in known])
    w = weights(len(known), s.half_life)
    first = fit_logit(BASE, [r.x for r in known], y, w, s.ridge)
    both = [i for i, r in enumerate(known) if all(r.x[n] is not None for n in EXTRA)]
    second = None
    if len(both) >= s.min_overlap:
        offset = np.array([first.eta(known[i].x) for i in both])
        second = fit_logit(EXTRA, [known[i].x for i in both], y[both], w[both], s.ridge, offset)
    return Odds(first, second, float((y * w).sum() / w.sum()))


@dataclass(frozen=True)
class Model:
    through: date
    rows: int
    range_beta: tuple[float, ...]
    range_sd: float
    z_low: float
    z_high: float
    up: Odds
    gap_up: Odds
    gap_size: tuple[float, float] | None
    gap_median: float


def fit(rows: Sequence[Row], s: Setup) -> Model:
    """Every model from `rows` that have outcomes. Deterministic: same rows, same model."""
    done = [r for r in rows if r.ret is not None]
    ranged = [r for r in done if r.rx is not None and r.log_range is not None]
    w = weights(len(ranged), s.half_life)
    x = np.array([r.rx for r in ranged], dtype=np.float64)
    y = np.array([r.log_range for r in ranged], dtype=np.float64)
    beta = _wls(x, y, w)
    fitted = x @ beta
    resid = y - fitted
    sd = math.sqrt(float((resid**2 * w).sum() / w.sum()))
    z = np.array([float(r.ret or 0.0) for r in ranged]) / np.exp(fitted)
    tail = (1 - s.band) / 2
    with_us = [r for r in done if r.x["us_session"] is not None and r.gap is not None]
    gap_size = None
    if len(with_us) >= s.min_overlap:
        g = _wls(
            np.array([[1.0, float(r.x["us_session"] or 0.0)] for r in with_us]),
            np.array([float(r.gap or 0.0) for r in with_us]),
            weights(len(with_us), s.half_life),
        )
        gap_size = (float(g[0]), float(g[1]))
    gaps = np.array([float(r.gap or 0.0) for r in done])
    return Model(
        through=done[-1].target or done[-1].day,
        rows=len(done),
        range_beta=tuple(float(b) for b in beta),
        range_sd=sd,
        z_low=weighted_quantile(z, w, tail),
        z_high=weighted_quantile(z, w, 1 - tail),
        up=_odds(done, "up", s),
        gap_up=_odds(done, "gap_up", s),
        gap_size=gap_size,
        gap_median=float(np.median(gaps)),
    )


# --- forecast -------------------------------------------------------------------------------------


@dataclass
class Forecast:
    target: str
    made_at: str
    last_day: str
    last_close: float
    range_pct: float
    vix_range_pct: float | None
    band_low: float
    band_high: float
    p_up: float
    base_up: float
    p_gap_up: float
    base_gap_up: float
    expected_open: float
    gap_pct: float
    up_reasons: dict[str, float]
    gap_reasons: dict[str, float]
    features: dict[str, float | None]
    second_stage: bool
    us_source: str
    version: str = VERSION
    trained_through: str = ""
    rows: int = 0
    range_percentile: float | None = None

    def key(self) -> str:
        body = {k: v for k, v in asdict(self).items() if k != "made_at"}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def predict(
    model: Model, row: Row, vix: float | None, made_at: datetime, us_source: str = ""
) -> Forecast:
    if row.rx is None or row.target is None:
        msg = "today's row lacks the range inputs or a target session"
        raise ValueError(msg)
    log_range = float(np.dot(model.range_beta, row.rx))
    scale = math.exp(log_range)
    p_up, up_why, both = model.up.predict(row.x)
    p_gap, gap_why, _ = model.gap_up.predict(row.x)
    us = row.x["us_session"]
    gap = (
        model.gap_size[0] + model.gap_size[1] * us
        if model.gap_size and us is not None
        else model.gap_median
    )
    return Forecast(
        target=row.target.isoformat(),
        made_at=made_at.isoformat(),
        last_day=row.day.isoformat(),
        last_close=row.close,
        range_pct=round(math.exp(log_range + model.range_sd**2 / 2) * 100, 3),
        vix_range_pct=round(vix / 100 / math.sqrt(252) * RANGE_PER_SIGMA * 100, 3) if vix else None,
        band_low=round(row.close * math.exp(model.z_low * scale), 1),
        band_high=round(row.close * math.exp(model.z_high * scale), 1),
        p_up=round(p_up, 4),
        base_up=round(model.up.base, 4),
        p_gap_up=round(p_gap, 4),
        base_gap_up=round(model.gap_up.base, 4),
        expected_open=round(row.close * math.exp(gap), 1),
        gap_pct=round(gap * 100, 3),
        up_reasons={k: round(v, 2) for k, v in up_why.items()},
        gap_reasons={k: round(v, 2) for k, v in gap_why.items()},
        features={k: (round(v, 6) if v is not None else None) for k, v in row.x.items()},
        second_stage=both,
        us_source=us_source,
        trained_through=model.through.isoformat(),
        rows=model.rows,
    )


# --- scoring --------------------------------------------------------------------------------------


def outcome(
    f: Mapping[str, Any], opened: float, close: float, range_pct: float | None
) -> dict[str, Any]:
    """One forecast against the session it forecast: its open, close and high-low range in %."""
    last = float(f["last_close"])
    up, gap_up = float(close > last), float(opened > last)
    vix = f.get("vix_range_pct")
    return {
        "target": f["target"],
        "close": close,
        "open": opened,
        "change_pct": round((close / last - 1) * 100, 2),
        "gap_pct": round((opened / last - 1) * 100, 2),
        "range_pct": round(range_pct, 3) if range_pct else None,
        "up": bool(up),
        "gap_up": bool(gap_up),
        "in_band": float(f["band_low"]) <= close <= float(f["band_high"]),
        "hit_up": float((float(f["p_up"]) > 0.5) == bool(up)),
        "brier_up": (float(f["p_up"]) - up) ** 2,
        "brier_up_base": (float(f["base_up"]) - up) ** 2,
        "brier_gap": (float(f["p_gap_up"]) - gap_up) ** 2,
        "brier_gap_base": (float(f["base_gap_up"]) - gap_up) ** 2,
        "range_error": abs(math.log(range_pct / float(f["range_pct"]))) if range_pct else None,
        "range_error_vix": abs(math.log(range_pct / float(vix))) if range_pct and vix else None,
    }


def score(f: Mapping[str, Any], actual: Bar) -> dict[str, Any]:
    span = math.log(actual.high / actual.low) * 100 if actual.high > actual.low else None
    return outcome(f, actual.open, actual.close, span)


@dataclass
class Card:
    """How a set of scored forecasts did against their baselines."""

    n: int = 0
    brier_up: float | None = None
    brier_up_base: float | None = None
    brier_gap: float | None = None
    brier_gap_base: float | None = None
    in_band: float | None = None
    range_error: float | None = None
    range_error_vix: float | None = None
    hit_up: float | None = None
    since: str = ""
    to: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def card(scored: Sequence[Mapping[str, Any]]) -> Card:
    if not scored:
        return Card()

    def mean(key: str) -> float | None:
        vals = [float(s[key]) for s in scored if s.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return Card(
        n=len(scored),
        brier_up=mean("brier_up"),
        brier_up_base=mean("brier_up_base"),
        brier_gap=mean("brier_gap"),
        brier_gap_base=mean("brier_gap_base"),
        in_band=mean("in_band"),
        range_error=mean("range_error"),
        range_error_vix=mean("range_error_vix"),
        hit_up=mean("hit_up"),
        since=str(scored[0]["target"]),
        to=str(scored[-1]["target"]),
    )


def check(rows: Sequence[Row], s: Setup) -> Card:
    """Walk-forward: the last `check_sessions` sessions, each forecast from a model fitted before it."""
    done = [i for i, r in enumerate(rows) if r.ret is not None and r.rx is not None]
    picked = done[-s.check_sessions :]
    scored: list[dict[str, Any]] = []
    model: Model | None = None
    for k, i in enumerate(picked):
        if k % s.refit_every == 0:
            model = fit(rows[:i], s)
        r = rows[i]
        if model is None or r.rx is None or r.ret is None:
            continue
        f = asdict(predict(model, r, math.exp(r.rx[4]), datetime.min.replace(tzinfo=UTC)))
        span = math.exp(r.log_range) * 100 if r.log_range is not None else None
        scored.append(outcome(f, r.close * math.exp(r.gap or 0.0), r.close * math.exp(r.ret), span))
    out = card(scored)
    out.extra = {"refit_every": s.refit_every}
    return out


def trust(live: Card, walked: Card, s: Setup, kind: str) -> tuple[bool, str]:
    """Whether the `kind` odds ("up" or "gap") beat the base rate on the evidence that counts now."""
    use, where = (live, "live") if live.n >= s.min_live else (walked, "walk-forward check")
    model = getattr(use, f"brier_{kind}")
    base = getattr(use, f"brier_{kind}_base")
    if model is None or base is None:
        return False, "The model is not scored yet, so the base rate is shown."
    skill = (1 - model / base) * 100 if base else 0.0
    measured = (
        f"Brier {model:.4f} against the base rate's {base:.4f} over {use.n} sessions in the {where}"
    )
    if model > base:
        return (
            False,
            f"The model trails the base rate ({measured}), so the base rate is shown instead.",
        )
    if skill < 1:
        return (
            True,
            f"The model only matches the base rate ({measured}, skill {skill:+.1f}%): read it as close to a coin flip.",
        )
    return True, f"The model beats the base rate ({measured}, skill {skill:+.1f}%)."


# --- the log --------------------------------------------------------------------------------------


def logged(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or LOG
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def before_open(f: Mapping[str, Any]) -> bool:
    made = datetime.fromisoformat(str(f["made_at"])).astimezone(IST)
    return made < datetime.combine(date.fromisoformat(str(f["target"])), OPEN, IST)


def record(f: Forecast, path: Path | None = None) -> bool:
    """Append `f` when it was made before its session opened and differs from the last one for that session."""
    p = path or LOG
    row = asdict(f)
    if not before_open(row):
        return False
    same = [r for r in logged(p) if r.get("target") == f.target]
    if same and same[-1].get("key") == f.key():
        return False
    row |= {
        "key": f.key(),
        "event_time": datetime.combine(date.fromisoformat(f.target), time(15, 30), IST).isoformat(),
        "knowledge_time": f.made_at,
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return True


def live_scores(history: Sequence[Bar], path: Path | None = None) -> list[dict[str, Any]]:
    """The last forecast made before each session's open, scored, oldest first."""
    final: dict[str, dict[str, Any]] = {}
    for f in logged(path):
        if before_open(f):
            final[str(f["target"])] = f
    by_day = {b.day.isoformat(): b for b in history}
    out = []
    for target in sorted(final):
        if target in by_day:
            f = final[target]
            one = score(f, by_day[target])
            one["forecast"] = f
            out.append(one)
    return out


# --- what happened, in words ----------------------------------------------------------------------


def last_session(history: Sequence[Bar], fii: Mapping[date, float]) -> list[str]:
    """The last session told as a sequence: the open, the day, where it closed in its range, VIX, flows."""
    if len(history) < 22:
        return []
    b, prev = history[-1], history[-2]
    gap = (b.open / prev.close - 1) * 100
    day = (b.close / b.open - 1) * 100
    total = (b.close / prev.close - 1) * 100
    span = (b.high / b.low - 1) * 100
    usual = sorted((h.high / h.low - 1) * 100 for h in history[-21:-1])[10]
    where = (b.close - b.low) / (b.high - b.low) if b.high > b.low else 0.5
    out = [
        f"Nifty 50 closed at {b.close:,.1f} on {b.day}, {total:+.2f}% on the day. It opened "
        f"{'higher' if gap > 0 else 'lower' if gap < 0 else 'flat'} ({gap:+.2f}%) and then "
        f"{'gained' if day > 0 else 'lost'} {abs(day):.2f}% from the open to the close.",
        f"The day's range was {span:.2f}% ({b.low:,.0f} to {b.high:,.0f}), "
        + (
            "wider than"
            if span > usual * 1.25
            else "narrower than"
            if span < usual * 0.75
            else "close to"
        )
        + f" the median of the previous 20 sessions ({usual:.2f}%).",
        "It closed in the "
        + (
            "top quarter of its range: buyers held it into the close."
            if where >= 0.75
            else "bottom quarter of its range: sellers held it into the close."
            if where <= 0.25
            else "middle of its range: neither side held control into the close."
        )
        + f" ({where * 100:.0f}% of the way from low to high.)",
    ]
    if b.vix and prev.vix:
        change = (b.vix / prev.vix - 1) * 100
        both = (
            "fell with a rising market, the usual pairing"
            if change < 0 < total
            else (
                "rose with a falling market, the usual pairing"
                if change > 0 > total
                else (
                    "rose although the market rose: traders paid for protection into strength"
                    if change > 0
                    else "fell although the market fell: the drop did not spread fear"
                )
            )
        )
        out.append(f"India VIX {b.vix:.2f}, {change:+.1f}%; it {both}.")
    if b.day in fii:
        out.append(
            f"FIIs were net {'buyers' if fii[b.day] > 0 else 'sellers'} of ₹{abs(fii[b.day]):,.0f} cr in cash that day."
        )
    return out


def _say_points(name: str, value: float | None, points: float) -> str:
    way = "raises" if points > 0 else "lowers"
    if name == "recent":
        often = "less" if points < 0 else "more"
        return f"{SAY[name]} {often} often than the long run's, {way} the odds by {abs(points):.1f} points"
    shown = (
        "not known"
        if value is None
        else f"₹{value:+,.0f} cr"
        if name == "fii_week"
        else f"{value * 100:+.2f}%"
    )
    return f"{SAY[name]} ({shown}) {way} the odds by {abs(points):.1f} points"


def reasons(f: Mapping[str, Any], kind: str, limit: int = 4) -> list[str]:
    """The features that moved the `kind` odds most, in words, largest first."""
    parts: Mapping[str, float] = f["up_reasons"] if kind == "up" else f["gap_reasons"]
    ranked = sorted(parts.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return [_say_points(n, f["features"].get(n), p) for n, p in ranked[:limit] if abs(p) >= 0.1]


def scenarios(f: Mapping[str, Any], show_up: float, band: float) -> list[str]:
    """Three cases with their odds and levels: higher close, lower close, outside the band."""
    last, low, high = float(f["last_close"]), float(f["band_low"]), float(f["band_high"])
    tail = (1 - band) / 2 * 100
    return [
        f"Higher close ({show_up * 100:.0f}%): most such days close between {last:,.0f} and "
        f"{high:,.0f}. A close above {high:,.0f} has about a {tail:.0f}% chance on the range model.",
        f"Lower close ({(1 - show_up) * 100:.0f}%): most such days close between {low:,.0f} and "
        f"{last:,.0f}. A close below {low:,.0f} also has about a {tail:.0f}% chance.",
        f"A close outside {low:,.0f} to {high:,.0f} (about {tail * 2:.0f}%) needs news the data "
        "does not hold yet: an overnight shock, a policy surprise or a large block of orders. "
        f"The range model expects a {f['range_pct']:.2f}% high-to-low range.",
    ]


# --- the whole thing, for the brief ---------------------------------------------------------------


def next_target(last: date, after: date, closed: frozenset[date]) -> date:
    """The first session after both the last bar and `after - 1 day`."""
    from datetime import timedelta

    from eulerlab.ingest import holidays

    d = max(last + timedelta(days=1), after)
    while not holidays.is_session(d, closed):
        d += timedelta(days=1)
    return d


def build(
    *,
    now: datetime,
    closed: frozenset[date] = frozenset(),
    us_live: float | None = None,
    s: Setup | None = None,
    index_path: Path | None = None,
    us_path: Path | None = None,
    log_path: Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Fit, forecast the next session, log it, and score everything logged so far."""
    s = s or setup()
    history = bars(index_path or INDEX_HISTORY, as_of=now, start=s.start)
    if len(history) < 260:
        return {"available": False, "reason": "fewer than 260 Nifty sessions held"}
    fii = fii_nets(now)
    spy = spy_closes(us_path or US_PANEL)
    today = now.astimezone(IST).date()
    target = next_target(history[-1].day, today, closed)
    rows = table(history, fii, spy, next_target=target)
    us_source = "SPY close (US panel)"
    last = rows[-1]
    hour = now.astimezone(IST).time()
    if us_live is not None and not time(2, 30) <= hour < OPEN:
        us_live, us_source = None, "the US session before this open has not closed yet"
    if last.x["us_session"] is None and us_live is not None:
        last = replace(last, x=last.x | {"us_session": math.log(1 + us_live / 100)})
        us_source = "S&P 500 change, live"
    elif last.x["us_session"] is None and us_source.startswith("SPY"):
        us_source = "not known"
    model = fit(rows, s)
    f = predict(model, last, history[-1].vix, now, us_source)
    year = [math.log(b.high / b.low) * 100 for b in history[-252:] if b.high > b.low]
    f.range_percentile = (
        round(sum(v <= f.range_pct for v in year) / len(year) * 100) if year else None
    )
    if write:
        record(f, log_path)
    scored = live_scores(history, log_path)
    live = card(scored[-s.live_window :])
    walked = check(rows, s)
    up_ok, up_why = trust(live, walked, s, "up")
    gap_ok, gap_why = trust(live, walked, s, "gap")
    shown = asdict(f)
    return {
        "available": True,
        "label": LABEL,
        "forecast": shown,
        "show_up": f.p_up if up_ok else f.base_up,
        "show_gap_up": f.p_gap_up if gap_ok else f.base_gap_up,
        "up_trusted": up_ok,
        "up_why": up_why,
        "gap_trusted": gap_ok,
        "gap_why": gap_why,
        "up_reasons": reasons(shown, "up"),
        "gap_reasons": reasons(shown, "gap"),
        "scenarios": scenarios(shown, f.p_up if up_ok else f.base_up, s.band),
        "live": asdict(live),
        "check": asdict(walked),
        "last_scored": scored[-1] if scored else None,
        "story": last_session(history, fii),
        "late": not before_open(shown),
    }
