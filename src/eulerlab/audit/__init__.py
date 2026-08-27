"""An auditor for this codebase, not for code in general.

Generic linters already run here — ruff, mypy strict, a pytest gate on every
commit — and they catch what they catch. Everything in this package exists
because something got through them and cost a day.

The defects this project actually produces share a shape: a plausible default
silently applying the wrong thing, so the numbers still look right. A crypto
trade billed Indian securities transaction tax. Every winning exit billed the
same. A signal reading the whole backtest on every bar, which is not wrong,
only quadratic, until a five-year request stops returning. A listing that read
its first thousand keys and treated the rest as absent. None of those are type
errors and none of them fail a test that was not written for them.

So the rules here are narrow and specific by design. A rule that fires on
"complexity" would be noise; a rule that fires on "a cost path with a default
asset class" is a bug that has happened four times.

Three passes, in increasing cost and decreasing certainty:

`rules`      deterministic, fast, safe to gate a commit on.
`smoke`      does every registered strategy actually run.
`review`     a model reads the diff for what no rule anticipates.

The first two are the ones to trust. The third is advisory and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    """How much a finding should interrupt someone."""

    FAIL = "fail"
    """A defect. The kind of thing that has already shipped once."""

    WARN = "warn"
    """Probably wrong, but a legitimate exception exists."""

    NOTE = "note"
    """Worth seeing. Never a reason to stop."""


@dataclass(frozen=True)
class Finding:
    """One thing the auditor noticed, and where."""

    rule: str
    severity: Severity
    message: str
    path: str = ""
    line: int = 0
    #: Why this rule exists at all. Printed with the finding, because a rule
    #: whose reason is not on screen gets deleted the first time it is
    #: inconvenient.
    because: str = ""

    def where(self) -> str:
        if not self.path:
            return ""
        return f"{self.path}:{self.line}" if self.line else self.path


@dataclass
class Report:
    """Everything one audit run found."""

    findings: list[Finding] = field(default_factory=list)
    checked: int = 0
    #: Set when the model pass could not run. Empty is not the same as clean,
    #: and a reader must be able to tell which they are looking at.
    review_skipped: str = ""

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]

    @property
    def failed(self) -> bool:
        return bool(self.by_severity(Severity.FAIL))
