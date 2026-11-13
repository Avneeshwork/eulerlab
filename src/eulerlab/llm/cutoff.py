"""What a language model may have memorised: cutoffs, stamps on judged values, a recall probe (ADR-176).

A model trained on text up to some day can recall what the market did before
that day. Telling it "use only data before X" does not stop it (research 190).
So a number a model *judged* (the direction of a news story, a forecast) is
not a fair signal on any session the model may have read about. Three controls:

1. **Stamp.** `stamp` records each judged value with the model that judged it
   and that model's published training cutoff (`config/model_cutoffs.yaml`).
2. **Refuse.** `require_after` raises `BeforeCutoff` when a backtest window
   starts on or before the cutoff. A model with no published cutoff cannot be
   backtested at all. `research/fast_eval.py` calls this for every rule that
   reads a model-judged field.
3. **Probe.** `probe` asks a model for index closes on past days and scores
   its recall by month, so the published cutoff can be checked against what
   the model in fact remembers. `make llm-probe PROVIDER=groq`.

Rule-writing prompts are a separate matter: they carry earlier rules and
their screen results, never prices (`agents/workers/autopilot.py`), and an
idea taken from a paper is counted in its family by the firewall like any other.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from eulerlab.db.stream import add_row, read_rows
from eulerlab.filecache import read_yaml
from eulerlab.paths import data_path

CONFIG = Path("config/model_cutoffs.yaml")
KIND = "llm_values"
TOLERANCE = 0.005
"""A recalled close within half a percent of the true one counts as recalled."""
ASKS = 24
"""Days asked per probe, spread over the months given."""


def values_path() -> Path:
    return data_path("derived/llm_values.jsonl")


def probe_dir() -> Path:
    return data_path("derived/llm_probe")


class BeforeCutoff(PermissionError):
    """A model-judged signal was asked for on sessions the model may have read about."""


def cutoffs(path: Path | None = None) -> dict[str, date]:
    path = path or CONFIG
    if not path.exists():
        return {}
    found = (read_yaml(path) or {}).get("models") or {}
    return {
        str(k): v if isinstance(v, date) else date.fromisoformat(str(v)) for k, v in found.items()
    }


def cutoff(model: str, path: Path | None = None) -> date | None:
    """The model's training cutoff, or None when none is published."""
    return cutoffs(path).get(model)


def require_after(
    model: str, first: date, *, what: str = "signal", path: Path | None = None
) -> None:
    """Raise unless a window starting `first` lies wholly after the model's cutoff."""
    known = cutoff(model, path)
    if known is None:
        msg = (
            f"{what}: {model or 'an unnamed model'} has no published training cutoff, "
            "so its judgements cannot be backtested, only used going forward"
        )
        raise BeforeCutoff(msg)
    if first <= known:
        msg = (
            f"{what}: the window starts {first}, but {model} was trained on data up to "
            f"{known}; test it only on sessions after that"
        )
        raise BeforeCutoff(msg)


def stamp(
    signal: str,
    value: float,
    model: str,
    *,
    about: date,
    now: datetime | None = None,
    path: Path | None = None,
) -> None:
    """Record one model-judged value: what, for which day, by which model, with its cutoff."""
    known = cutoff(model)
    add_row(
        path or values_path(),
        KIND,
        {
            "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
            "signal": signal,
            "about": about.isoformat(),
            "value": value,
            "model": model,
            "cutoff": known.isoformat() if known else None,
        },
    )


def stamped(signal: str, path: Path | None = None) -> list[dict[str, Any]]:
    return [r for r in read_rows(path or values_path(), KIND) if r.get("signal") == signal]


def series(signal: str, path: Path | None = None) -> tuple[dict[date, float], set[str]]:
    """A stamped signal as {day: latest value}, and every model that judged it."""
    out: dict[date, float] = {}
    models: set[str] = set()
    for row in stamped(signal, path):
        out[date.fromisoformat(row["about"])] = float(row["value"])
        models.add(str(row["model"]))
    return out, models


# --- the recall probe --------------------------------------------------------------------

QUESTION = (
    "What was the closing value of the Nifty 50 index on {day}? Answer with the number "
    "only, to the nearest point. If you do not know, answer exactly: unknown"
)
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def _pick(truth: Mapping[date, float], count: int) -> list[date]:
    """About `count` days spread evenly through the months of `truth`, the same each run."""
    by_month: dict[str, list[date]] = {}
    for day in sorted(truth):
        by_month.setdefault(day.isoformat()[:7], []).append(day)
    months = sorted(by_month)
    step = max(1, len(months) // max(1, count))
    return [by_month[m][len(by_month[m]) // 2] for m in months[::step]][:count]


def probe(
    model: str,
    ask: Callable[[str], str],
    truth: Mapping[date, float],
    *,
    count: int = ASKS,
    now: datetime | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Ask for past closes; report recall by month beside the published cutoff."""
    months: dict[str, dict[str, int]] = {}
    for day in _pick(truth, count):
        answer = ask(QUESTION.format(day=day.strftime("%d %B %Y")))
        found = _NUMBER.search(answer.replace("unknown", ""))
        said = float(found.group().replace(",", "")) if found else None
        row = months.setdefault(day.isoformat()[:7], {"asked": 0, "recalled": 0})
        row["asked"] += 1
        row["recalled"] += bool(said and abs(said / truth[day] - 1.0) <= TOLERANCE)
    known = cutoff(model)
    recalled = [m for m, r in months.items() if r["recalled"]]
    report = {
        "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "model": model,
        "published_cutoff": known.isoformat() if known else None,
        "last_month_recalled": max(recalled) if recalled else None,
        "recalled_after_cutoff": sorted(
            m for m in recalled if known is not None and m > known.isoformat()[:7]
        ),
        "months": dict(sorted(months.items())),
    }
    folder = out_dir or probe_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", model) + ".json"
    (folder / name).write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return report


def render(report: Mapping[str, Any]) -> str:
    lines = [
        f"{report['model']}: published cutoff {report['published_cutoff'] or 'none'}, "
        f"last month recalled {report['last_month_recalled'] or 'none'}"
    ]
    if report["recalled_after_cutoff"]:
        lines.append(
            "  RECALLS MONTHS AFTER ITS PUBLISHED CUTOFF: "
            + ", ".join(report["recalled_after_cutoff"])
        )
    lines += [f"  {m}  {r['recalled']} of {r['asked']}" for m, r in report["months"].items()]
    return "\n".join(lines)


def _nifty() -> dict[date, float]:
    from eulerlab import market_history as mh

    want = mh.canonical_index("Nifty 50")
    out: dict[date, float] = {}
    if mh.INDEX_HISTORY.exists():
        for line in mh.INDEX_HISTORY.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("index") == want:
                out[date.fromisoformat(row["d"])] = float(row["c"])
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.assistant import chat
    from eulerlab.llm import client, spend

    parser = argparse.ArgumentParser(prog="llm-probe", description=__doc__)
    parser.add_argument("--provider", required=True, help="a provider name from config/llm.yaml")
    args = parser.parse_args(argv)
    truth = _nifty()
    if not truth:
        print("no index history on file (make market-history); nothing to compare answers with")
        return 2
    model = client.load_config().get(args.provider).model
    spend.refuse_if_spent(args.provider)

    def ask(question: str) -> str:
        return chat.complete_any("Answer briefly.", question, name=args.provider).text

    print(render(probe(model, ask, truth)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
