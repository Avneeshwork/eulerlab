"""Score the agents against fixed test sets, and switch off one that makes things up (ADR-088).

    make agent-eval                 # skeptic (no model) + knowledge (uses its budget)
    make agent-eval ONLY=skeptic    # the free part only

**Skeptic.** Ten equity curves made fake on purpose, each with one known flaw:
a single lucky year, a handful of huge days, a strategy that loses at twice
its costs. A pass is the skeptic marking it critical. No model, no network.

**Knowledge.** The questions in `config/agent_eval/knowledge.yaml`. A case
passes when every expected string is in the answer, or, for a question the
platform cannot answer, when the answer says "not held". Every answer is
also run through the grounding check, and its count of made-up figures is the
number that matters most.

**What happens on a made-up figure.** If any answer the operator would have
been shown carries a figure no tool returned, the knowledge agent is switched
off (`spec.write_setting(enabled=False)`, which only narrows) and the log says
why. Switching it back on is the operator's, on the AI tab, after the model or
prompt is fixed. Scores go to `data/agents/eval/<stamp>.json` and the log.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from eulerlab.agents import log, runtime
from eulerlab.agents.spec import home, write_setting

CASES = Path("config/agent_eval/knowledge.yaml")


@dataclass
class Score:
    agent: str
    cases: int = 0
    passed: int = 0
    made_up: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def share(self) -> float:
        return self.passed / self.cases if self.cases else 0.0


# --- skeptic: curves with one known flaw each ---


def _days(n: int, start: date = date(2018, 1, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def _from_returns(rets: list[float]) -> list[float]:
    values = [100.0]
    for r in rets:
        values.append(values[-1] * (1 + r))
    return values


def fake_curves() -> list[tuple[str, list[date], list[float], dict[str, Any]]]:
    out: list[tuple[str, list[date], list[float], dict[str, Any]]] = []
    n = 1500
    noise = [0.006 * math.sin(i * 1.7) + 0.004 * math.cos(i * 0.31) for i in range(n - 1)]
    for k, year in enumerate((2019, 2020, 2021, 2022)):
        days = _days(n)
        rets = [r + (0.004 if days[i + 1].year == year else 0.0) for i, r in enumerate(noise)]
        out.append((f"lucky year {year} (#{k + 1})", days, _from_returns(rets), {}))
    for k, size in enumerate((0.25, 0.35, 0.5)):
        rets = list(noise)
        for i in range(0, n - 1, 300):
            rets[i] = size
        out.append((f"a few huge days at {size:.0%} (#{k + 1})", _days(n), _from_returns(rets), {}))
    for k, cost in enumerate((4000.0, 6000.0, 9000.0)):
        rets = [r + 0.0002 for r in noise]
        out.append(
            (
                f"gone at 2x costs (#{k + 1})",
                _days(n),
                _from_returns(rets),
                {"summary": {"costs": cost}},
            )
        )
    return out


def score_skeptic() -> Score:
    from eulerlab.agents.workers import skeptic

    score = Score("skeptic")
    for name, days, values, report in fake_curves():
        score.cases += 1
        found = skeptic.attacks(days, values, report)
        if any(i.severity == "critical" for i in skeptic.verdicts(found)):
            score.passed += 1
        else:
            score.failures.append(f"missed: {name}")
    return score


# --- knowledge ---

Ask = Callable[[str], runtime.Output]


def _default_ask(question: str) -> runtime.Output:
    return runtime.run("knowledge", args={"question": question})


def score_knowledge(cases_path: Path = CASES, ask: Ask | None = None) -> Score:
    ask = ask or _default_ask
    spec = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or {}
    score = Score("knowledge")
    for case in spec.get("cases") or []:
        score.cases += 1
        out = ask(str(case["question"]))
        if out.status != "ok":
            score.failures.append(f"{case['id']}: {out.status}: {out.summary[:120]}")
            if out.status in ("over_budget", "skipped"):
                break
            continue
        answer = str(out.data.get("answer", ""))
        g = out.data.get("grounding") or {}
        if g.get("unsupported") and not g.get("withheld"):
            score.made_up += len(g["unsupported"])
        lowered = answer.lower()
        if case.get("not_held"):
            ok = "not held" in lowered
        else:
            ok = all(str(x).lower() in lowered for x in case.get("expect") or [])
        if ok:
            score.passed += 1
        else:
            score.failures.append(f"{case['id']}: {answer[:160]!r}")
    return score


def enforce(score: Score, root: Path | None = None) -> str:
    """Switch an agent off when it showed the operator a made-up figure."""
    if score.made_up == 0:
        return ""
    write_setting(score.agent, enabled=False, root=root)
    log.append(
        "setting",
        score.agent,
        {"enabled": False, "why": f"{score.made_up} made-up figures in agent-eval"},
        root=root,
    )
    return f"{score.agent} switched off: {score.made_up} made-up figure(s). Fix the model or prompt, then switch it on."


def save(scores: list[Score], root: Path | None = None, now: datetime | None = None) -> Path:
    root = home(root)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    path = root / "eval" / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([{**asdict(s), "share": round(s.share, 3)} for s in scores], indent=2),
        encoding="utf-8",
    )
    for s in scores:
        log.append(
            "eval",
            s.agent,
            {"cases": s.cases, "passed": s.passed, "made_up": s.made_up, "file": path.name},
            root=root,
        )
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-eval", description=__doc__)
    parser.add_argument("--only", choices=["skeptic", "knowledge"], default=None)
    args = parser.parse_args(argv)
    scores: list[Score] = []
    if args.only in (None, "skeptic"):
        scores.append(score_skeptic())
    if args.only in (None, "knowledge"):
        scores.append(score_knowledge())
    status = 0
    for s in scores:
        print(f"{s.agent:<10} {s.passed}/{s.cases} passed, {s.made_up} made-up figures")
        for line in s.failures:
            print(f"   {line}")
        said = enforce(s)
        if said:
            print(f"   {said}")
            status = 1
    print(f"  saved: {save(scores)}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
