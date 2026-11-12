"""`make data-quality` — the one rulebook every dataset is graded against (ADR-086).

Whatever the source, a dataset passes the same six checks, and the result is a
grade the rest of the platform reads:

| check | passes when | otherwise |
|---|---|---|
| registered | it has an entry in `config/data_sources.yaml` | grade D |
| provenance | publisher, address and licence status are written down | warn (licence unreviewed) |
| fingerprint | every landed file has a SHA-256 and a knowledge time | fail |
| sense | no duplicate, empty or missing-day findings (`manifest_checks`) | warn or fail |
| quarantine | none of its files is held (`quarantine.py`) | fail |
| freshness | it reaches the day it should (`ingest/coverage.py`) | reported apart |

**Integrity grade:** A clean · B warnings only · C a failed check · D not
registered or no data at all. A derived table (the price panel) takes the
worst grade of what it is built from, because a clean build of a bad source is
still bad data.

**Freshness is reported apart from integrity.** A backtest of 2015-2025 does
not care that today's file is late; a paper book does. So `guard` checks the
integrity grade for research, and the paper runner keeps its own staleness
rule (`deploy/runner.freshness`).

**What reads the grade.** Both backtest commands refuse a dataset below its
`min_grade` unless told `--allow-low-grade`. The knowledge agent and the data
agent quote it. The control room shows it.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.paths import data_path
from eulerlab.quality import quarantine
from eulerlab.quality.findings import Finding, Severity

REGISTER = Path("config/data_sources.yaml")
LANDING = data_path("landing")
GRADES = data_path("quality/grades.json")
GRADE_ORDER = "ABCD"
SHA = re.compile(r"^[0-9a-f]{64}$")

State = Literal["pass", "warn", "fail", "info"]
Grade = Literal["A", "B", "C", "D"]


class Source(BaseModel):
    """One entry of the register."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=2)
    tree: str = ""
    segment: str = ""
    derived: str = ""
    built_from: list[str] = Field(default_factory=list)
    publisher: str
    url: str = ""
    licence: str
    knowledge_time: str = Field(min_length=3)
    critical: bool = False
    min_grade: Grade = "C"
    cross_check: str = ""
    point_in_time: bool = True
    """False when the source cannot say when each value became known."""


class Register(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    datasets: list[Source]

    def by_name(self) -> dict[str, Source]:
        return {s.name: s for s in self.datasets}


def load_register(path: Path = REGISTER) -> Register:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    register = Register.model_validate(raw)
    names = [s.name for s in register.datasets]
    if len(names) != len(set(names)):
        msg = f"{path} lists a dataset twice"
        raise ValueError(msg)
    return register


@dataclass(frozen=True)
class Check:
    name: str
    state: State
    detail: str


@dataclass
class Graded:
    name: str
    grade: Grade
    freshness: str
    """ok · behind · stale · missing · info · unknown"""
    critical: bool
    min_grade: Grade
    checks: list[Check] = field(default_factory=list)
    point_in_time: bool = True

    @property
    def usable(self) -> bool:
        return GRADE_ORDER.index(self.grade) <= GRADE_ORDER.index(self.min_grade)

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["usable"] = self.usable
        return out


def _grade_of(checks: Iterable[Check]) -> Grade:
    states = {c.state for c in checks}
    if "fail" in states:
        return "C"
    if "warn" in states:
        return "B"
    return "A"


def _worse(a: Grade, b: Grade) -> Grade:
    return a if GRADE_ORDER.index(a) >= GRADE_ORDER.index(b) else b


def _manifest_rows(path: Path, segment: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rows.append({"_broken": True})
                continue
            if not segment or row.get("segment") == segment:
                rows.append(row)
    return rows


def fingerprint_check(rows: Sequence[dict[str, Any]]) -> Check:
    if not rows:
        return Check("fingerprint", "fail", "no landed files recorded")
    broken = sum(1 for r in rows if r.get("_broken"))
    no_sha = sum(
        1 for r in rows if not r.get("_broken") and not SHA.match(str(r.get("sha256", "")))
    )
    no_time = sum(1 for r in rows if not r.get("_broken") and not r.get("knowledge_time"))
    problems = []
    if broken:
        problems.append(f"{broken} unreadable manifest line(s)")
    if no_sha:
        problems.append(f"{no_sha} file(s) without a SHA-256")
    if no_time:
        problems.append(f"{no_time} file(s) without a knowledge time")
    if problems:
        return Check("fingerprint", "fail", "; ".join(problems))
    return Check(
        "fingerprint", "pass", f"{len(rows):,} files, each with a SHA-256 and a knowledge time"
    )


def provenance_check(source: Source) -> Check:
    if not source.publisher.strip():
        return Check("provenance", "fail", "no publisher written down")
    if source.tree and not source.url:
        return Check("provenance", "fail", "no source address written down")
    if source.licence.strip().lower() == "unreviewed":
        return Check("provenance", "warn", f"{source.publisher}; licence terms not yet reviewed")
    return Check("provenance", "pass", f"{source.publisher}; licence: {source.licence}")


def sense_check(findings: Sequence[Finding]) -> Check:
    errors = [f for f in findings if f.severity == Severity.ERROR]
    warns = [f for f in findings if f.severity == Severity.WARN]
    if errors:
        return Check("sense", "fail", "; ".join(f"{f.check}: {f.detail}" for f in errors[:3]))
    if warns:
        return Check("sense", "warn", "; ".join(f"{f.check}: {f.detail}" for f in warns[:3]))
    return Check("sense", "pass", "no duplicate, empty or missing-day findings")


def quarantine_check(source: Source, holds: dict[tuple[str, str], quarantine.Record]) -> Check:
    mine = [r for (dataset, _), r in holds.items() if dataset == source.name]
    if mine:
        first = mine[0]
        return Check(
            "quarantine", "fail", f"{len(mine)} file(s) held, e.g. {first.path}: {first.reason}"
        )
    return Check("quarantine", "pass", "no file held")


def grade_all(
    *,
    register: Register | None = None,
    coverage: Callable[[], Sequence[Any]] | None = None,
    findings: Callable[[], Sequence[Finding]] | None = None,
    landing: Path = LANDING,
    held_path: Path | None = None,
) -> list[Graded]:
    """Every registered dataset, graded. Unregistered coverage rows come back as D."""
    reg = register or load_register()
    if coverage is None:
        from eulerlab.ingest import coverage as coverage_mod

        coverage = coverage_mod.table
    if findings is None:
        from eulerlab.quality.manifest_checks import run_manifest_checks

        def findings() -> list[Finding]:
            return run_manifest_checks(landing)

    try:
        rows = {str(r.name): str(r.status) for r in coverage()}
    except Exception:  # coverage reads local files only; a broken one must not stop grading
        rows = {}
    try:
        found = list(findings())
    except Exception:
        found = []
    holds = quarantine.held(held_path)
    by_name = reg.by_name()
    out: dict[str, Graded] = {}

    def grade_source(source: Source) -> Graded:
        if source.name in out:
            return out[source.name]
        checks: list[Check] = [Check("registered", "pass", "in config/data_sources.yaml")]
        checks.append(provenance_check(source))
        grade: Grade
        if source.tree:
            manifest = landing / source.tree / "manifest.jsonl"
            mrows = _manifest_rows(manifest, source.segment)
            checks.append(fingerprint_check(mrows))
            # Only this source's segment, where the finding names one: the
            # `nse` manifest holds five segments, and a revised index file
            # graded the cash and F&O bhavcopies C (T-4355).
            mine = [
                f
                for f in found
                if f.dataset == source.tree
                and (not f.segment or not source.segment or f.segment == source.segment)
            ]
            checks.append(sense_check(mine))
            checks.append(quarantine_check(source, holds))
            grade = "D" if not mrows else _grade_of(checks)
        else:
            exists = bool(source.derived) and Path(source.derived).exists()
            checks.append(
                Check(
                    "fingerprint",
                    "pass" if exists else "fail",
                    "built here from fingerprinted files"
                    if exists
                    else f"{source.derived} not built",
                )
            )
            checks.append(quarantine_check(source, holds))
            grade = _grade_of(checks) if exists else "D"
            for parent in source.built_from:
                upstream = by_name.get(parent)
                if upstream is None:
                    checks.append(Check("built from", "fail", f"{parent} is not registered"))
                    grade = _worse(grade, "C")
                    continue
                parent_grade = grade_source(upstream).grade
                checks.append(
                    Check(
                        "built from",
                        "pass" if parent_grade in "AB" else "fail",
                        f"{parent}: grade {parent_grade}",
                    )
                )
                grade = _worse(grade, parent_grade)
        if not source.point_in_time:
            checks.append(
                Check("point in time", "warn", "the source cannot say when each value became known")
            )
            grade = _worse(grade, "B")
        graded = Graded(
            name=source.name,
            grade=grade,
            freshness=rows.get(source.name, "unknown"),
            critical=source.critical,
            min_grade=source.min_grade,
            checks=checks,
            point_in_time=source.point_in_time,
        )
        out[source.name] = graded
        return graded

    for source in reg.datasets:
        grade_source(source)
    for name, status in rows.items():
        if name not in out and not name.startswith("Paper"):
            out[name] = Graded(
                name=name,
                grade="D",
                freshness=status,
                critical=False,
                min_grade="C",
                checks=[Check("registered", "fail", "not in config/data_sources.yaml")],
            )
    return [out[s.name] for s in reg.datasets] + [g for n, g in out.items() if n not in by_name]


class LowGrade(RuntimeError):
    """A dataset is below the grade its use needs."""


def guard(
    names: Sequence[str],
    *,
    allow_low: bool = False,
    grades: Sequence[Graded] | None = None,
    log: Callable[[str], Any] = print,
) -> list[Graded]:
    """Refuse to go on when a named dataset is below its minimum grade."""
    graded = {g.name: g for g in (grades if grades is not None else grade_all())}
    low: list[str] = []
    for name in names:
        g = graded.get(name)
        if g is None:
            low.append(f"{name}: not registered (grade D)")
            continue
        log(f"data quality: {name} grade {g.grade} (needs {g.min_grade}), freshness {g.freshness}")
        if not g.usable:
            failed = "; ".join(f"{c.name}: {c.detail}" for c in g.checks if c.state == "fail")
            low.append(f"{name}: grade {g.grade}, needs {g.min_grade}. {failed}")
    if low and not allow_low:
        msg = (
            "data below grade:\n  "
            + "\n  ".join(low)
            + "\nFix the data, or pass --allow-low-grade to run anyway."
        )
        raise LowGrade(msg)
    for line in low:
        log(f"data quality: running on low-grade data as asked: {line}")
    return [graded[n] for n in names if n in graded]


def save(grades: Sequence[Graded], path: Path | None = None) -> Path:
    path = path or GRADES
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([g.as_dict() for g in grades], indent=2), encoding="utf-8")
    return path


def saved(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or GRADES
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def render(grades: Sequence[Graded]) -> str:
    lines = ["", f"  {'grade':<6}{'fresh':<9}{'dataset':<34}first problem"]
    for g in grades:
        problem = next(
            (f"{c.name}: {c.detail}" for c in g.checks if c.state in ("fail", "warn")), ""
        )
        mark = "" if g.usable else "  <- below its minimum"
        lines.append(f"  {g.grade:<6}{g.freshness:<9}{g.name:<34}{problem[:80]}{mark}")
    counts = {k: sum(1 for g in grades if g.grade == k) for k in GRADE_ORDER}
    lines += ["", "  " + " · ".join(f"{k}: {v}" for k, v in counts.items())]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="data-quality", description=__doc__)
    parser.add_argument("--hold", nargs=3, metavar=("DATASET", "FILE", "REASON"))
    parser.add_argument("--release", nargs=3, metavar=("DATASET", "FILE", "NOTE"))
    args = parser.parse_args(argv)
    if args.hold:
        record = quarantine.hold(*args.hold, by="operator")
        print(f"held {record.path} ({record.dataset}): {record.reason}")
    if args.release:
        record = quarantine.release(*args.release)
        print(f"released {record.path} ({record.dataset}): {record.reason}")
    grades = grade_all()
    print(render(grades))
    print(f"\n  saved: {save(grades)}")
    critical_low = [g.name for g in grades if g.critical and not g.usable]
    return 1 if critical_low else 0


if __name__ == "__main__":
    raise SystemExit(main())
