"""The promotion gate. Operator-owned, written once in Sprint 14.

`CLAUDE.md`: *`gates.py` and `mandate.yaml` are operator-owned. You may propose
changes in a review; you may not edit them without an explicit instruction in
that session. A strategy that fails the gate is dead. Do not tune it and
resubmit. Do not argue with the gate.*

Two design rules follow from that, and both are structural rather than
aspirational.

**No thresholds live here.** Every number is read from `mandate.yaml`. This
file holds only the logic that applies them. The separation exists so a
threshold cannot be relaxed as a side effect of a refactor — changing what the
gate demands means editing a YAML file the operator owns, visibly, on its own.

**The default answer is no.** A check that cannot be evaluated fails; a
missing field fails; an unparseable evidence pack fails. The asymmetry is
deliberate and it is not a matter of taste: wrongly killing a good strategy
costs an opportunity, wrongly promoting a bad one costs money, and a gate that
treats those as equivalent is not a gate.

`decide()` returns a verdict and every reason behind it. It never returns
"pass with concerns", because a gate that can express reservations will be
overruled by whoever reads them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from eulerlab.paths import data_path
from eulerlab.validation import ledger

MANDATE_PATH = Path("mandate.yaml")
HOLDOUT_STATE = data_path("derived/holdout_reads.jsonl")


class Verdict(StrEnum):
    PROMOTE = "PROMOTE"
    PAPER = "PAPER"
    """Missed the promotion bar but cleared `paper:` in the mandate: forward paper
    trading for more evidence, no holdout read, no live money (ADR-141)."""
    KILL = "KILL"


@dataclass(frozen=True)
class Finding:
    """One check, and whether it passed."""

    rule: str
    passed: bool
    detail: str

    def line(self) -> str:
        return f"  {'pass' if self.passed else 'KILL'}  {self.rule:<38} {self.detail}"


@dataclass
class Decision:
    hypothesis: str
    findings: list[Finding] = field(default_factory=list)
    paper_findings: list[Finding] = field(default_factory=list)
    """The `paper:` bar, checked only when promotion failed (empty otherwise)."""
    process_failed: bool = False

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed]

    @property
    def verdict(self) -> Verdict:
        """All green promotes. Otherwise PAPER if the evidence is sound and clears
        the paper bar, else KILL. There is no override."""
        if not self.failures:
            return Verdict.PROMOTE
        if (
            not self.process_failed
            and self.paper_findings
            and all(f.passed for f in self.paper_findings)
        ):
            return Verdict.PAPER
        return Verdict.KILL

    def render(self) -> str:
        lines = [f"\ngate: {self.hypothesis}", ""]
        lines.extend(f.line() for f in self.findings)
        lines.append("")
        if self.verdict is Verdict.KILL:
            lines.append(
                f"VERDICT: KILL — {len(self.failures)} of {len(self.findings)} rules failed"
            )
            lines.append(
                "\nCLAUDE.md: a strategy the gate kills is dead. It is not tuned\n"
                "and resubmitted. Resubmitting it under a new hypothesis id is visible\n"
                "in the trial ledger, which is what that ledger is for."
            )
        elif self.verdict is Verdict.PAPER:
            lines.append("  -- the paper bar --")
            lines.extend(f.line() for f in self.paper_findings)
            lines.append("")
            lines.append(
                f"VERDICT: PAPER — {len(self.failures)} of {len(self.findings)} promotion rules "
                "failed; the paper bar passed"
            )
            lines.append(
                "\nForward paper trading only, for more evidence (ADR-141). It may not\n"
                "read the holdout and may not trade live. Re-gate it with paper results."
            )
        else:
            lines.append(f"VERDICT: PROMOTE — all {len(self.findings)} rules passed")
            lines.append(
                "\nThis authorises reading the holdout ONCE, by the operator's action.\n"
                "It does not authorise capital."
            )
        return "\n".join(lines)


def load_mandate(path: Path = MANDATE_PATH) -> dict[str, Any]:
    if not path.exists():
        msg = f"no mandate at {path}. The gate cannot run without one."
        raise FileNotFoundError(msg)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"{path} did not parse to a mapping"
        raise ValueError(msg)
    return loaded


def _get(pack: dict[str, Any], *path: str) -> Any:
    node: Any = pack
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _check_statistics(pack: dict[str, Any], rules: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []

    configs = _get(pack, "configurations") or []
    dsr_values: list[float] = [
        float(c["deflated_sharpe_probability"])
        for c in configs
        if isinstance(c, dict) and isinstance(c.get("deflated_sharpe_probability"), int | float)
    ]
    floor = rules["min_deflated_sharpe_probability"]
    if not dsr_values:
        out.append(Finding("deflated sharpe", False, "no deflated Sharpe in the evidence pack"))
    else:
        best = max(dsr_values)
        out.append(
            Finding(
                "deflated sharpe",
                best >= floor,
                f"best {best:.3f}, mandate requires >= {floor}",
            )
        )

    out.extend(_check_search(pack, rules["search_correction"]))

    pbo = _get(pack, "pbo", "value")
    ceiling = rules["max_pbo"]
    if not isinstance(pbo, int | float):
        out.append(Finding("probability of overfitting", False, "no PBO in the evidence pack"))
    else:
        out.append(
            Finding(
                "probability of overfitting",
                pbo <= ceiling,
                f"{pbo:.1%}, mandate allows <= {ceiling:.0%}",
            )
        )

    needed = _get(pack, "min_backtest_length_years")
    have = _get(pack, "available_years")
    ratio_floor = rules["min_backtest_length_ratio"]
    if not isinstance(needed, int | float) or not isinstance(have, int | float):
        out.append(Finding("backtest length", False, "length figures missing"))
    else:
        ratio = have / needed if needed > 0 else float("inf")
        out.append(
            Finding(
                "backtest length",
                ratio >= ratio_floor,
                f"{have:.1f}y available vs {needed:.1f}y needed ({ratio:.1f}x, "
                f"mandate requires {ratio_floor}x)",
            )
        )
    return out


def _check_search(pack: dict[str, Any], rules: dict[str, Any]) -> list[Finding]:
    """The deflated Sharpe must use the mandate's search correction (ADR-108).

    A pack built any other way (the old ledger count, or none) fails: its
    deflated Sharpe answers a different question. When Romano-Wolf is
    required, the candidate's return over Nifty must be rejected as no-edge
    at no looser a level than the mandate's.
    """
    out: list[Finding] = []
    method = _get(pack, "search", "method")
    family = _get(pack, "search", "families") or {}
    out.append(
        Finding(
            "search correction",
            method == rules["method"],
            (
                f"{method}: {family.get('families')} families of {family.get('strategies')} "
                f"strategies, sigma {family.get('sigma')}, bar Sharpe {family.get('bar')}"
                if method == rules["method"]
                else f"pack used {method!r}; mandate requires {rules['method']!r}"
            ),
        )
    )
    if rules["romano_wolf_required"]:
        test = _get(pack, "search", "romano_wolf")
        if not isinstance(test, dict):
            out.append(Finding("romano-wolf", False, "no Romano-Wolf test in the evidence pack"))
        else:
            level = test.get("alpha")
            strict_enough = isinstance(level, int | float) and level <= rules["romano_wolf_alpha"]
            out.append(
                Finding(
                    "romano-wolf",
                    bool(test.get("passed")) and strict_enough,
                    f"Sharpe over Nifty {test.get('candidate_sharpe')} vs critical "
                    f"{test.get('critical_sharpe')} across {test.get('strategies')} strategies, "
                    f"level {level}, mandate requires <= {rules['romano_wolf_alpha']}",
                )
            )
    return out


def _check_robustness(pack: dict[str, Any], rules: dict[str, Any]) -> list[Finding]:
    tests = _get(pack, "stress_tests") or []
    if not tests:
        return [Finding("stress tests", False, "no stress tests in the evidence pack")]

    out: list[Finding] = []
    by_name = {t.get("test", ""): t for t in tests if isinstance(t, dict)}

    def retained(entry: dict[str, Any]) -> float:
        base = entry.get("base_sharpe") or 0.0
        stressed = entry.get("stressed_sharpe") or 0.0
        return stressed / base if base > 0 else 0.0

    for label, key, rule in (
        ("2x costs", "costs x2", "min_sharpe_retained_at_2x_costs"),
        ("concentration", "drop best 5 names", "min_sharpe_retained_dropping_best_names"),
    ):
        entry = by_name.get(key)
        floor = rules[rule]
        if entry is None:
            out.append(Finding(f"stress: {label}", False, f"'{key}' was not run"))
            continue
        value = retained(entry)
        out.append(
            Finding(
                f"stress: {label}",
                value >= floor,
                f"{value:.0%} of Sharpe retained, mandate requires >= {floor:.0%}",
            )
        )

    regimes = [t for name, t in by_name.items() if name.startswith("regime:")]
    floor = rules["min_sharpe_retained_worst_regime"]
    if not regimes:
        out.append(Finding("stress: worst regime", False, "no regime split was run"))
    else:
        worst = min(retained(t) for t in regimes)
        out.append(
            Finding(
                "stress: worst regime",
                worst >= floor,
                f"weakest regime retains {worst:.0%}, mandate requires >= {floor:.0%}",
            )
        )

    if not rules["allow_any_negative_stress"]:
        negative = [t.get("test") for t in tests if not t.get("survives", True)]
        out.append(
            Finding(
                "stress: none negative",
                not negative,
                "all stresses stay positive"
                if not negative
                else f"negative: {', '.join(map(str, negative))}",
            )
        )
    return out


def _check_process(
    pack: dict[str, Any], rules: dict[str, Any], *, hypothesis_path: Path
) -> list[Finding]:
    out: list[Finding] = []

    if rules["require_pre_registration"]:
        if not hypothesis_path.exists():
            out.append(Finding("pre-registration", False, f"no {hypothesis_path}"))
        else:
            spec = yaml.safe_load(hypothesis_path.read_text(encoding="utf-8")) or {}
            flags = spec.get("red_flags") or []
            configured = spec.get("configurations") or []
            registered = bool(spec.get("claim")) and bool(flags) and bool(configured)
            out.append(
                Finding(
                    "pre-registration",
                    registered,
                    f"claim, {len(configured)} configurations and {len(flags)} red flags "
                    f"declared in advance"
                    if registered
                    else "hypothesis is missing a claim, configurations or red flags",
                )
            )

    if rules["require_signed_evidence"]:
        signature = pack.get("signature")
        body = json.dumps(
            {k: v for k, v in pack.items() if k != "signature"}, indent=2, sort_keys=True
        )
        recomputed = ledger.compute_hash({"body": body})
        out.append(
            Finding(
                "evidence signature",
                bool(signature) and signature == recomputed,
                "matches" if signature == recomputed else "MISSING OR ALTERED since the run",
            )
        )

    if rules["require_intact_trial_ledger"]:
        chain = ledger.verify_chain()
        out.append(Finding("trial ledger", chain.intact, chain.detail))

    return out


def decide(
    pack: dict[str, Any], *, hypothesis_path: Path, mandate: dict[str, Any] | None = None
) -> Decision:
    """Apply the mandate to one evidence pack.

    Process rules are evaluated first and reported first. If the evidence
    cannot be trusted — unsigned, unregistered, or resting on a broken trial
    ledger — the statistics are noise dressed as numbers, and the reader
    should see that before any Sharpe ratio.
    """
    rules = mandate or load_mandate()
    decision = Decision(hypothesis=str(pack.get("hypothesis", "unknown")))
    process = _check_process(pack, rules["process"], hypothesis_path=hypothesis_path)
    decision.findings.extend(process)
    decision.process_failed = not all(f.passed for f in process)
    if rules.get("mode", "strict") == "simple":
        decision.findings.extend(_check_simple(pack, rules["simple"]))
    else:
        decision.findings.extend(_check_statistics(pack, rules["statistical"]))
        decision.findings.extend(_check_robustness(pack, rules["robustness"]))
    if decision.failures and "paper" in rules:
        decision.paper_findings = _check_paper(pack, rules["paper"])
    return decision


def _check_paper(pack: dict[str, Any], rules: dict[str, Any]) -> list[Finding]:
    """The bar for forward paper trading (ADR-141): profitable after costs, and not
    obviously luck. A missing figure fails, as everywhere in the gate."""
    out: list[Finding] = []
    configs = [c for c in (_get(pack, "configurations") or []) if isinstance(c, dict)]
    sharpes = [
        float(c["full_sample_sharpe"]) for c in configs if c.get("full_sample_sharpe") is not None
    ]
    floor = float(rules["min_full_sample_sharpe"])
    best = max(sharpes) if sharpes else None
    out.append(
        Finding(
            "paper: net profitable",
            best is not None and best > floor,
            "no full-sample Sharpe in the evidence pack"
            if best is None
            else f"full-sample net Sharpe {best:.2f}, must be > {floor}",
        )
    )
    psr_floor = float(rules["min_probabilistic_sharpe"])
    psrs = [
        float(c["probabilistic_sharpe"])
        for c in configs
        if c.get("probabilistic_sharpe") is not None
    ]
    psr = max(psrs) if psrs else None
    out.append(
        Finding(
            "paper: probabilistic sharpe",
            psr is not None and psr >= psr_floor,
            "no probabilistic Sharpe in the evidence pack"
            if psr is None
            else f"{psr:.3f}, paper bar requires >= {psr_floor}",
        )
    )
    return out


def _check_simple(pack: dict[str, Any], rules: dict[str, Any]) -> list[Finding]:
    """The simple bar (ADR-140): net positive overall, in each half, and at 2x costs.

    Still default-no: a figure missing from the evidence pack fails its check.
    """
    out: list[Finding] = []
    by_name = {
        t.get("test", ""): t for t in (_get(pack, "stress_tests") or []) if isinstance(t, dict)
    }
    if rules.get("require_positive_full_sample", True):
        sharpes = [
            float(c["full_sample_sharpe"])
            for c in (_get(pack, "configurations") or [])
            if isinstance(c, dict) and c.get("full_sample_sharpe") is not None
        ]
        best = max(sharpes) if sharpes else None
        out.append(
            Finding(
                "net positive overall",
                best is not None and best > 0,
                "no full-sample Sharpe in the evidence pack"
                if best is None
                else f"full-sample net Sharpe {best:.2f}, must be > 0",
            )
        )
    if rules.get("require_positive_each_half", True):
        for half in ("first half", "second half"):
            entry = by_name.get(f"regime: {half}")
            value = entry.get("stressed_sharpe") if entry else None
            out.append(
                Finding(
                    f"net positive, {half}",
                    value is not None and value > 0,
                    f"'regime: {half}' was not run"
                    if value is None
                    else f"net Sharpe {value:.2f}, must be > 0",
                )
            )
    if "min_probabilistic_sharpe" in rules:
        floor = float(rules["min_probabilistic_sharpe"])
        values = [
            float(c["probabilistic_sharpe"])
            for c in (_get(pack, "configurations") or [])
            if isinstance(c, dict) and c.get("probabilistic_sharpe") is not None
        ]
        psr = max(values) if values else None
        out.append(
            Finding(
                "probabilistic sharpe",
                psr is not None and psr >= floor,
                "no probabilistic Sharpe in the evidence pack"
                if psr is None
                else f"{psr:.3f}, mandate requires >= {floor}",
            )
        )
    if "min_positive_year_fraction" in rules:
        floor = float(rules["min_positive_year_fraction"])
        min_days = float(rules["stability_min_days_in_year"])
        years = [
            y
            for y in (_get(pack, "stability") or {}).values()
            if isinstance(y, dict) and float(y.get("days", 0)) >= min_days
        ]
        share = (
            sum(1 for y in years if float(y.get("net_return", 0)) > 0) / len(years)
            if years
            else None
        )
        out.append(
            Finding(
                "stability: positive years",
                share is not None and share >= floor,
                "no yearly results in the evidence pack"
                if share is None
                else f"{share:.0%} of {len(years)} years net positive, mandate requires >= {floor:.0%}",
            )
        )
    if rules.get("require_positive_at_2x_costs", True):
        entry = by_name.get("costs x2")
        value = entry.get("stressed_sharpe") if entry else None
        out.append(
            Finding(
                "net positive at 2x costs",
                value is not None and value > 0,
                "'costs x2' was not run"
                if value is None
                else f"net Sharpe {value:.2f}, must be > 0",
            )
        )
    return out


# --- the holdout: readable exactly once ---


@dataclass(frozen=True)
class HoldoutRead:
    hypothesis: str
    read_at: str
    authorised_by: str


def holdout_reads(path: Path = HOLDOUT_STATE) -> list[HoldoutRead]:
    if not path.exists():
        return []
    return [
        HoldoutRead(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def may_read_holdout(
    decision: Decision, *, mandate: dict[str, Any] | None = None, path: Path = HOLDOUT_STATE
) -> tuple[bool, str]:
    """Whether the holdout may be read now. Refuses by default.

    Two conditions, and both are absolute. The gate must have said PROMOTE —
    reading the holdout for something that already failed is exactly the
    "check something" `CLAUDE.md` forbids. And the read budget must not be
    spent: the holdout cannot be regenerated, so a second read does not
    produce weaker evidence, it produces none.
    """
    rules = (mandate or load_mandate())["process"]
    if decision.verdict is not Verdict.PROMOTE:
        return False, (
            f"the gate returned {decision.verdict}; the holdout is read only after a PROMOTE"
        )
    used = len(holdout_reads(path))
    permitted = int(rules["holdout_reads_permitted"])
    if used >= permitted:
        return False, (
            f"the holdout has already been read {used} time(s) and the mandate permits "
            f"{permitted}. It cannot be regenerated, so there is nothing left to read."
        )
    return True, f"{permitted - used} read(s) remaining"


def record_holdout_read(hypothesis: str, *, authorised_by: str, path: Path = HOLDOUT_STATE) -> None:
    """Spend the single read. Append-only, and there is no way to un-spend it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = HoldoutRead(
        hypothesis=hypothesis,
        read_at=datetime.now(UTC).isoformat(),
        authorised_by=authorised_by,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.__dict__, sort_keys=True) + "\n")
