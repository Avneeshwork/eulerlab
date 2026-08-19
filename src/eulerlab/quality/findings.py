"""What a quality check reports, and how known problems stay silent.

Two rules shape this module.

**A finding names one fact about one thing on one day.** Not "137 bad rows in
2019" — the operator cannot act on that. `NIFTY50 on 2019-03-14 failed
ohlc-bounds: high 812.0 is below close 840.5` can be looked up in the source
file in a minute.

**Known problems are silenced by name, never by threshold.** Three defects in
this dataset are understood and documented: no F&O file on 2021-03-30 (S-009),
three empty Kite windows (S-007), and 1,055 minute chunks that predate their
symbol's listing (S-008). The tempting fix is to widen a tolerance until they
stop appearing. That also silences the *next* defect, which is unknown and is
the entire point of the engine. So each one is suppressed by an explicit id
tied to its STUBS entry, and anything not on that list is reported.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "ERROR"
    """The data is impossible, not merely unusual. A high below a low is not a
    market event. Fails the build."""

    WARN = "WARN"
    """Suspicious and worth a human look, but could legitimately be real."""

    INFO = "INFO"
    """Observed and recorded, expected to be benign. Never fails the build."""


@dataclass(frozen=True)
class Finding:
    check: str
    severity: Severity
    detail: str
    dataset: str = ""
    symbol: str = ""
    day: date | None = None

    def location(self) -> str:
        parts = [
            p for p in (self.dataset, self.symbol, self.day.isoformat() if self.day else "") if p
        ]
        return "/".join(parts) or "-"

    def line(self) -> str:
        return f"{self.severity:<5} {self.check:<22} {self.location():<28} {self.detail}"


@dataclass(frozen=True)
class Suppression:
    """One known, documented defect that must not be reported as new."""

    check: str
    stub: str
    """The STUBS.md id that explains it. A suppression with no entry there is
    not allowed — that is how a real defect gets quietly buried."""
    reason: str
    dataset: str = ""
    symbol: str = ""
    day: date | None = None

    def matches(self, finding: Finding) -> bool:
        if self.check != finding.check:
            return False
        for mine, theirs in (
            (self.dataset, finding.dataset),
            (self.symbol, finding.symbol),
        ):
            if mine and mine != theirs:
                return False
        return not (self.day and self.day != finding.day)


KNOWN: tuple[Suppression, ...] = (
    Suppression(
        check="segment-coverage",
        stub="S-009",
        reason=(
            "NSE serves no F&O file for this date; re-probed 2026-08-19 and "
            "confirmed absent at source, not a fetch failure"
        ),
        dataset="nse",
        day=date(2021, 3, 30),
    ),
    Suppression(
        check="empty-chunk-pre-listing",
        stub="S-008",
        reason=(
            "70 symbols listed after 2021, so their early windows legitimately "
            "predate the listing. Scoped to the pre-listing check only: the "
            "mid-history gaps below are a different, real problem and must "
            "stay visible"
        ),
        dataset="kite_minute",
    ),
    # The three genuine mid-history gaps, each pinned to its exact window.
    # Pinned rather than suppressed per symbol so a *new* gap in BCG or
    # FORCEMOT still reports - the point of the check is the fourth one.
    Suppression(
        check="empty-chunk",
        stub="S-007",
        reason="Kite returns 0 bars for this window; a control window for the same symbol returned 6,855, so the data is absent at source",
        dataset="kite_minute",
        symbol="BCG",
        day=date(2025, 1, 30),
    ),
    Suppression(
        check="empty-chunk",
        stub="S-007",
        reason="second half of the same BCG absence",
        dataset="kite_minute",
        symbol="BCG",
        day=date(2025, 3, 31),
    ),
    Suppression(
        check="empty-chunk",
        stub="S-007",
        reason="Kite returns 0 bars for this FORCEMOT window; bhavcopy shows it traded, so this is a Kite coverage gap",
        dataset="kite_minute",
        symbol="FORCEMOT",
        day=date(2023, 12, 7),
    ),
)


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    suppressed: list[tuple[Finding, Suppression]] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        for known in KNOWN:
            if known.matches(finding):
                self.suppressed.append((finding, known))
                return
        self.findings.append(finding)

    def extend(self, findings: Iterable[Finding]) -> None:
        for finding in findings:
            self.add(finding)

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity is severity)

    @property
    def errors(self) -> int:
        return self.count(Severity.ERROR)

    def by_check(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for finding in self.findings:
            out[finding.check] = out.get(finding.check, 0) + 1
        return dict(sorted(out.items()))

    def render(self, *, limit: int = 20) -> str:
        lines: list[str] = []
        counts = {s: self.count(s) for s in Severity}
        lines.append("")
        lines.append(f"{'SEVERITY':<9} COUNT")
        for severity in Severity:
            lines.append(f"{severity:<9} {counts[severity]:>5}")

        if by_check := self.by_check():
            lines.append("")
            lines.append(f"{'CHECK':<24} COUNT")
            for name, n in by_check.items():
                lines.append(f"{name:<24} {n:>5}")

        shown = _worst_first(self.findings)[:limit]
        if shown:
            lines.append("")
            lines.append(f"first {len(shown)} of {len(self.findings)}:")
            lines.extend("  " + f.line() for f in shown)

        if self.suppressed:
            lines.append("")
            lines.append(f"suppressed as known ({len(self.suppressed)}):")
            for stub, n in sorted(_suppressed_counts(self.suppressed).items()):
                lines.append(f"  {stub}: {n}")

        lines.append("")
        if self.errors:
            lines.append(f"quality FAILED: {self.errors} ERROR-level finding(s)")
        else:
            lines.append(f"quality OK: 0 errors, {self.count(Severity.WARN)} warnings")
        return "\n".join(lines)


def _worst_first(findings: Sequence[Finding]) -> list[Finding]:
    order = {Severity.ERROR: 0, Severity.WARN: 1, Severity.INFO: 2}
    return sorted(findings, key=lambda f: (order[f.severity], f.check, f.location()))


def _suppressed_counts(pairs: Sequence[tuple[Finding, Suppression]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, known in pairs:
        out[known.stub] = out.get(known.stub, 0) + 1
    return out
