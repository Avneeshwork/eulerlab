"""The Trader's read: the top of the market brief, answered in one fixed order (ADR-100).

1. **Bottom line**: one sentence that says what the numbers add up to.
2. **Scorecard**: one row per signal, each with its value, what is normal for
   it, and a word: supportive, neutral or weak.
3. **Today's map**: the levels a trader looks at: last close, its averages,
   the expected range, max pain.
4. **What would change the read**: the conditions, in numbers, under which a
   weak or supportive word would flip.
5. **Your books**: each paper book's day, drawdown and how much is invested.

Every number comes from the inputs the brief already gathered. The words come
from the thresholds in `config/trader_read.yaml`, never from a model. The
words are counted for the bottom line but not added into a score, and nothing
here feeds a strategy: it is context for the operator, not a signal.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from eulerlab.config import CONFIG_DIR

Word = Literal["supportive", "neutral", "weak", "missing"]


class ReadLevels(BaseModel):
    """`config/trader_read.yaml`. A missing or malformed file stops the brief."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    breadth_weak_below: float
    breadth_supportive_above: float
    vix_weak_above: float
    vix_supportive_below: float
    positioning_weak_below: float
    positioning_supportive_above: float
    flows_weak_below: float
    flows_supportive_above: float
    valuation_supportive_below: float
    valuation_weak_above: float
    pcr_weak_below: float
    pcr_supportive_above: float
    divergence_points: float
    options_max_age_days: int


def levels(config_dir: Path | None = None) -> ReadLevels:
    path = (config_dir or CONFIG_DIR) / "trader_read.yaml"
    return ReadLevels.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@dataclass(frozen=True)
class Row:
    signal: str
    value: str
    normal: str
    word: Word
    why: str


@dataclass(frozen=True)
class Read:
    bottom_line: str
    rows: list[Row]
    map: list[str]
    triggers: list[str]
    books: list[str]
    gaps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and math.isfinite(value) else None


def _band(
    value: float | None, low: float, high: float, *, high_is_good: bool
) -> Literal["supportive", "neutral", "weak", "missing"]:
    if value is None:
        return "missing"
    if value < low:
        return "weak" if high_is_good else "supportive"
    if value > high:
        return "supportive" if high_is_good else "weak"
    return "neutral"


def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:+.{digits}f}%"


def _crore(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}₹{abs(value):,.0f} cr"


def _index(ctx: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    for row in (ctx.get("strip") or {}).get("indices") or []:
        if row.get("name") == name:
            found: Mapping[str, Any] = row
            return found
    return None


def averages(closes: Sequence[float]) -> dict[int, float]:
    """Simple moving averages of the last 20, 50 and 200 closes, where held."""
    return {n: sum(closes[-n:]) / n for n in (20, 50, 200) if len(closes) >= n}


# --- scorecard -----------------------------------------------------------------------------------


def _trend(ctx: Mapping[str, Any], close: float | None, avg: Mapping[int, float]) -> Row:
    cards = (ctx.get("pulse") or {}).get("cards") or []
    faber = next((str(c.get("word")) for c in cards if c.get("key") == "trend"), None)
    above = {n: close > a for n, a in avg.items()} if close is not None else {}
    parts = [f"{'above' if up else 'below'} {n}-day" for n, up in sorted(above.items())]
    value = ", ".join(parts) or "averages not held"
    if faber:
        value = f"{faber} (monthly rule); {value}"
    if not above and faber is None:
        return Row("Trend", value, "", "missing", "no index history")
    long_up = above.get(200)
    if faber == "Uptrend" and long_up is not False:
        word: Word = "supportive"
    elif faber == "Downtrend" and long_up is not True:
        word = "weak"
    elif faber is None and long_up is not None and above.get(50) == long_up:
        word = "supportive" if long_up else "weak"
    else:
        word = "neutral"
    return Row("Trend", value, "uptrend above the 200-day", word, "Nifty 50 against its averages")


def _breadth(ctx: Mapping[str, Any], lv: ReadLevels) -> Row:
    b = ctx.get("breadth") or {}
    latest = b.get("latest") or {}
    share = _num(latest.get("above_50"))
    if not b.get("available") or share is None:
        return Row("Breadth", "no data", "", "missing", str(b.get("reason") or ""))
    highs, lows = latest.get("new_highs"), latest.get("new_lows")
    value = f"{share:.0f}% of stocks above their 50-day"
    if isinstance(highs, int) and isinstance(lows, int):
        value += f"; {highs} new highs vs {lows} new lows"
    word = _band(share, lv.breadth_weak_below, lv.breadth_supportive_above, high_is_good=True)
    return Row(
        "Breadth",
        value,
        f"{lv.breadth_weak_below:.0f}-{lv.breadth_supportive_above:.0f}%",
        word,
        f"{b.get('stocks', '?')} NSE stocks, {b.get('as_of', '?')}",
    )


def _volatility(ctx: Mapping[str, Any], lv: ReadLevels) -> Row:
    vix = (ctx.get("strip") or {}).get("vix") or {}
    level, pct = _num(vix.get("level")), _num(vix.get("percentile_1y"))
    if level is None:
        return Row("Volatility", "no data", "", "missing", "no India VIX")
    median = _num(vix.get("median_1y"))
    word = _band(pct, lv.vix_supportive_below, lv.vix_weak_above, high_is_good=False)
    return Row(
        "Volatility",
        f"India VIX {level:.1f}, percentile {pct:.0f} of the past year"
        if pct is not None
        else f"India VIX {level:.1f}",
        f"median {median:.1f}" if median is not None else "",
        word,
        "high VIX means option sellers want more for risk",
    )


def _positioning(ctx: Mapping[str, Any], lv: ReadLevels) -> Row:
    p = ctx.get("positioning") or {}
    fii = next((r for r in p.get("participants") or [] if r.get("participant") == "FII"), None)
    if not p.get("available") or fii is None:
        return Row("FII futures", "no data", "", "missing", str(p.get("reason") or ""))
    share, usual = _num(fii.get("index_futures_long_share")), _num(fii.get("usual"))
    pct = _num(fii.get("percentile"))
    value = f"{share * 100:.0f}% of FII index futures are long" if share is not None else "n/a"
    if pct is not None:
        value += f", percentile {pct:.0f}"
    word = _band(pct, lv.positioning_weak_below, lv.positioning_supportive_above, high_is_good=True)
    return Row(
        "FII futures",
        value,
        f"usual {usual * 100:.0f}% long" if usual is not None else "",
        word,
        f"NSE participant OI, {p.get('as_of', '?')}",
    )


def _flows(flows: Mapping[str, Any], lv: ReadLevels) -> Row:
    if not flows.get("available"):
        return Row("Cash flows", "no data", "", "missing", str(flows.get("reason") or ""))
    fii, dii = flows.get("fii") or {}, flows.get("dii") or {}
    five = _num(fii.get("net_5d"))
    value = f"FII {_crore(float(fii.get('net', 0)))} on the day, {_crore(five or 0)} over 5 days"
    dii5 = _num(dii.get("net_5d"))
    if dii5 is not None:
        value += f"; DII {_crore(dii5)} over 5 days"
    word = _band(five, lv.flows_weak_below, lv.flows_supportive_above, high_is_good=True)
    return Row(
        "Cash flows",
        value,
        f"FII 5-day between {_crore(lv.flows_weak_below)} and {_crore(lv.flows_supportive_above)}",
        word,
        f"NSE provisional, {flows.get('as_of', '?')}",
    )


def _valuation(ctx: Mapping[str, Any], lv: ReadLevels) -> Row:
    rows = (ctx.get("valuation") or {}).get("indices") or []
    nifty = next((r for r in rows if r.get("name") == "Nifty 50"), None)
    pe = (nifty or {}).get("pe") or {}
    value, pct = _num(pe.get("value")), _num(pe.get("percentile"))
    if value is None:
        return Row("Valuation", "no data", "", "missing", "no Nifty 50 P/E")
    word = _band(pct, lv.valuation_supportive_below, lv.valuation_weak_above, high_is_good=False)
    median = _num(pe.get("median"))
    return Row(
        "Valuation",
        f"Nifty 50 P/E {value:.1f}"
        + (f", percentile {pct:.0f} since {pe.get('since', '?')}" if pct is not None else ""),
        f"median {median:.1f}" if median is not None else "",
        word,
        "slow: it matters over months, not today",
    )


def _options(ctx: Mapping[str, Any], lv: ReadLevels) -> Row:
    o = ctx.get("options") or {}
    pcr = _num(o.get("pcr_oi"))
    if not o.get("available") or pcr is None:
        return Row("Options", "no data", "", "missing", str(o.get("reason") or ""))
    before, iv, iv_before = (
        _num(o.get("pcr_oi_before")),
        _num(o.get("atm_iv")),
        _num(o.get("atm_iv_before")),
    )
    value = f"PCR {pcr:.2f}" + (f" (was {before:.2f})" if before is not None else "")
    if iv is not None:
        value += f"; ATM IV {iv * 100:.1f}%" + (
            f" (was {iv_before * 100:.1f}%)" if iv_before is not None else ""
        )
    word = _band(pcr, lv.pcr_weak_below, lv.pcr_supportive_above, high_is_good=True)
    return Row(
        "Options",
        value,
        f"PCR {lv.pcr_weak_below:.1f}-{lv.pcr_supportive_above:.1f}",
        word,
        f"expiry {o.get('expiry', '?')}, data of {o.get('as_of', '?')}",
    )


# --- bottom line, map, triggers, books -----------------------------------------------------------


def _bottom_line(ctx: Mapping[str, Any], rows: Sequence[Row], lv: ReadLevels) -> str:
    held = [r for r in rows if r.word != "missing"]
    weak = sum(r.word == "weak" for r in held)
    good = sum(r.word == "supportive" for r in held)
    if not held:
        return f"Incomplete: {len(rows)} of {len(rows)} signals missing. No read."
    if weak >= good + 2:
        tone = "Risk-off"
    elif good >= weak + 2:
        tone = "Risk-on"
    elif weak > good:
        tone = "Mixed, leaning weak"
    elif good > weak:
        tone = "Mixed, leaning supportive"
    else:
        tone = "Mixed"
    phrases: list[str] = []
    large, small = _index(ctx, "Nifty 50"), _index(ctx, "Nifty Smallcap 250")
    if large and small:
        gap = (
            _num((large.get("change") or {}).get("1m")),
            _num((small.get("change") or {}).get("1m")),
        )
        if gap[0] is not None and gap[1] is not None:
            points = (gap[0] - gap[1]) * 100
            if points > lv.divergence_points:
                phrases.append("large caps holding while the broad market sells off")
            elif points < -lv.divergence_points:
                phrases.append("small caps leading large caps")
    vol = next((r for r in rows if r.signal == "Volatility"), None)
    if vol is not None and vol.word == "weak":
        phrases.append("volatility above normal")
    elif vol is not None and vol.word == "supportive":
        phrases.append("volatility below normal")
    head = tone + (": " + "; ".join(phrases) if phrases else "")
    line = f"{head}. {weak} of {len(held)} signals weak, {good} supportive."
    gone = missing(rows)
    if gone:
        line = f"Incomplete: {len(gone)} of {len(rows)} signals missing ({', '.join(gone)}). {line}"
    return line


def missing(rows: Sequence[Row]) -> list[str]:
    """The scorecard rows with no data behind them."""
    return [r.signal for r in rows if r.word == "missing"]


def _map(
    ctx: Mapping[str, Any], close: float | None, avg: Mapping[int, float], lv: ReadLevels, day: str
) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    gaps: list[str] = []
    nifty = _index(ctx, "Nifty 50")
    if close is None or nifty is None:
        return ["Nifty 50 not held"], ["no Nifty 50 close"]
    lines.append(f"Nifty 50 last close {close:,.1f} ({nifty.get('as_of')})")
    for n, a in sorted(avg.items()):
        lines.append(f"{n}-day average {a:,.0f} ({(a / close - 1) * 100:+.1f}% from the close)")
    vix = _num(((ctx.get("strip") or {}).get("vix") or {}).get("level"))
    if vix is not None:
        move = close * vix / 100 / math.sqrt(252)
        lines.append(
            f"One-day range from VIX (one standard deviation): {close - move:,.0f} to {close + move:,.0f} (±{move:,.0f})"
        )
    o = ctx.get("options") or {}
    em = o.get("expected_move") or {}
    if o.get("available") and _num(em.get("low")) is not None:
        try:
            age = (date.fromisoformat(day) - date.fromisoformat(str(o.get("as_of")))).days
        except ValueError:
            age = lv.options_max_age_days + 1
        if age <= lv.options_max_age_days:
            lines.append(
                f"Range to expiry {o.get('expiry')} from the ATM straddle: {em['low']:,.0f} to {em['high']:,.0f} (data of {o.get('as_of')})"
            )
        else:
            gaps.append(
                f"option data is {age} days old ({o.get('as_of')}): straddle range left out"
            )
        if _num(o.get("max_pain")) is not None:
            lines.append(
                f"Max pain {o['max_pain']:,.0f} for expiry {o.get('expiry')} (data of {o.get('as_of')})"
            )
    return lines, gaps


def _triggers(
    rows: Sequence[Row],
    ctx: Mapping[str, Any],
    close: float | None,
    avg: Mapping[int, float],
    flows: Mapping[str, Any],
    lv: ReadLevels,
) -> list[str]:
    word = {r.signal: r.word for r in rows}
    out: list[str] = []
    if close is not None and 50 in avg:
        a = avg[50]
        side = "above" if close < a else "below"
        out.append(
            f"Trend: Nifty 50 closes {side} its 50-day average ({a:,.0f}, {(a / close - 1) * 100:+.1f}% away)"
        )
    share = _num(((ctx.get("breadth") or {}).get("latest") or {}).get("above_50"))
    if share is not None:
        if word.get("Breadth") == "weak":
            out.append(
                f"Breadth: share above the 50-day rises past {lv.breadth_weak_below:.0f}% (now {share:.0f}%)"
            )
        elif word.get("Breadth") == "supportive":
            out.append(
                f"Breadth: share above the 50-day falls below {lv.breadth_supportive_above:.0f}% (now {share:.0f}%)"
            )
        else:
            out.append(
                f"Breadth: share above the 50-day leaves {lv.breadth_weak_below:.0f}-{lv.breadth_supportive_above:.0f}% (now {share:.0f}%)"
            )
    vix = (ctx.get("strip") or {}).get("vix") or {}
    pct = _num(vix.get("percentile_1y"))
    if word.get("Volatility") == "weak" and pct is not None:
        out.append(
            f"Volatility: India VIX drops below its {lv.vix_weak_above:.0f}th percentile of the past "
            f"year (now percentile {pct:.0f}, level {vix.get('level')}; median {vix.get('median_1y')})"
        )
    elif word.get("Volatility") in ("supportive", "neutral") and pct is not None:
        out.append(
            f"Volatility: India VIX rises above its {lv.vix_weak_above:.0f}th percentile of the past "
            f"year (now percentile {pct:.0f})"
        )
    five = _num((flows.get("fii") or {}).get("net_5d")) if flows.get("available") else None
    if five is not None:
        if word.get("Cash flows") == "weak":
            edge = f"rises above {_crore(lv.flows_weak_below)}"
        elif word.get("Cash flows") == "supportive":
            edge = f"falls below {_crore(lv.flows_supportive_above)}"
        else:
            edge = f"leaves {_crore(lv.flows_weak_below)} to {_crore(lv.flows_supportive_above)}"
        out.append(f"Flows: FII 5-day net cash {edge} (now {_crore(five)})")
    return out


def _books(books: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    active = [b for b in books if b.get("status") == "active"]
    for b in active:
        bits = [f"{b.get('strategy')} ({b.get('mode')})"]
        day, dd, inv = _num(b.get("day_change")), _num(b.get("drawdown")), _num(b.get("invested"))
        if day is not None:
            bits.append(f"day {_pct(day)}")
        if dd is not None:
            reduce_at = _num(b.get("reduce_at"))
            limit = f" (reduce-only at {reduce_at * 100:.0f}%)" if reduce_at is not None else ""
            bits.append(f"{dd * 100:.1f}% below its peak{limit}")
        if inv is not None:
            bits.append(f"{inv * 100:.0f}% invested")
        warnings = [str(w) for w in b.get("warnings") or []]
        if warnings:
            bits.append("warning: " + warnings[0][:80])
        out.append(", ".join(bits))
    halted = [str(b.get("strategy")) for b in books if b.get("status") != "active"]
    if halted:
        out.append(f"Not active: {', '.join(halted)}")
    return out or ["no deployment"]


def build(
    ctx: Mapping[str, Any],
    *,
    closes: Sequence[float],
    flows: Mapping[str, Any],
    books: Sequence[Mapping[str, Any]],
    day: str,
    lv: ReadLevels,
) -> Read:
    """The read, from what the brief gathered. Pure: same inputs, same words."""
    nifty = _index(ctx, "Nifty 50")
    close = _num(nifty.get("close")) if nifty else None
    avg = averages(closes)
    rows = [
        _trend(ctx, close, avg),
        _breadth(ctx, lv),
        _volatility(ctx, lv),
        _positioning(ctx, lv),
        _flows(flows, lv),
        _valuation(ctx, lv),
        _options(ctx, lv),
    ]
    lines, gaps = _map(ctx, close, avg, lv, day)
    gaps += [f"{r.signal}: {r.why}" for r in rows if r.word == "missing" and r.why]
    return Read(
        bottom_line=_bottom_line(ctx, rows, lv),
        rows=rows,
        map=lines,
        triggers=_triggers(rows, ctx, close, avg, flows, lv),
        books=_books(books),
        gaps=gaps,
    )


MARK = {"supportive": "+", "neutral": "=", "weak": "-", "missing": "?"}


def render(read: Read) -> str:
    """Plain text that reads the same in the workbench and on a phone."""
    lines = ["TRADER'S READ", read.bottom_line, "", "SCORECARD  (+ supportive, = neutral, - weak)"]
    for r in read.rows:
        normal = f" | normal: {r.normal}" if r.normal else ""
        lines.append(f"{MARK[r.word]} {r.signal}: {r.word.upper()}. {r.value}{normal}")
    lines += ["", "TODAY'S MAP", *[f"- {m}" for m in read.map]]
    lines += [
        "",
        "WHAT WOULD CHANGE THE READ",
        *[f"- {t}" for t in read.triggers or ["nothing held to test"]],
    ]
    lines += ["", "YOUR BOOKS", *[f"- {b}" for b in read.books]]
    if read.gaps:
        lines += ["", "LEFT OUT", *[f"- {g}" for g in read.gaps]]
    return "\n".join(lines)
