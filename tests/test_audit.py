"""Each rule must fire on the defect it was written for, and not otherwise.

An auditor whose rules never fire is worse than no auditor: it reports a clean
tree and everyone believes it. Every check here is fed the real defect — taken
from the commit that fixed it — and then the fixed version, and must tell them
apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from eulerlab.audit import Severity
from eulerlab.audit.inventory import Entry, check_names, inventory
from eulerlab.audit.rules import (
    defaulted_asset_class,
    unbounded_window_reads,
    unpaginated_listing,
)


def _findings(source: str, check, name: str = "src/eulerlab/intraday/papers.py"):  # type: ignore[no-untyped-def]
    return check(ast.parse(source), Path(name))


# --- the quadratic window read ---------------------------------------------

BROKEN_WINDOW = """
def ou_mean_reversion(window, rules, equity):
    closes = _closes(window)[-(rules.ou_lookback + 1):]
    return closes
"""

FIXED_WINDOW = """
def ou_mean_reversion(window, rules, equity):
    closes = _closes(window[-(rules.ou_lookback + 1):])
    return closes
"""


def test_it_catches_extracting_before_slicing() -> None:
    found = _findings(BROKEN_WINDOW, unbounded_window_reads)
    assert len(found) == 1
    assert found[0].rule == "unbounded-window-read"
    assert found[0].severity is Severity.FAIL
    assert "ou_mean_reversion" in found[0].message


def test_it_accepts_slicing_before_extracting() -> None:
    """The two differ only in where a bracket sits."""
    assert _findings(FIXED_WINDOW, unbounded_window_reads) == []


def test_it_ignores_functions_that_take_no_window() -> None:
    source = "def render(rows):\n    return _closes(rows)\n"
    assert _findings(source, unbounded_window_reads) == []


# --- the defaulted venue ----------------------------------------------------


def test_it_catches_a_defaulted_asset_class() -> None:
    source = 'def _cost(price, shares, side, day, asset_class="equity"):\n    return 0\n'
    found = _findings(source, defaulted_asset_class)
    assert len(found) == 1
    assert found[0].severity is Severity.FAIL
    assert "asset_class" in found[0].message


def test_it_catches_a_keyword_only_default() -> None:
    source = 'def run(plan, *, asset_class="equity"):\n    return 0\n'
    assert len(_findings(source, defaulted_asset_class)) == 1


def test_it_accepts_a_required_asset_class() -> None:
    source = "def run(plan, *, asset_class):\n    return 0\n"
    assert _findings(source, defaulted_asset_class) == []


def test_it_only_looks_at_cost_bearing_modules() -> None:
    """A default asset class in a UI helper is not a mis-billed trade."""
    source = 'def label(asset_class="equity"):\n    return asset_class\n'
    assert _findings(source, defaulted_asset_class, "src/eulerlab/api/server.py") == []


# --- the truncated listing --------------------------------------------------


def test_it_catches_a_listing_that_never_paginates() -> None:
    source = (
        "def list_all(self, prefix):\n"
        "    loose = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)\n"
        "    return loose\n"
    )
    found = _findings(source, unpaginated_listing, "src/eulerlab/ingest/cloud.py")
    assert len(found) == 1
    assert found[0].severity is Severity.FAIL


def test_it_accepts_a_listing_inside_a_loop() -> None:
    source = (
        "def list_all(self, prefix):\n"
        "    while True:\n"
        "        page = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)\n"
        "        if not page.get('IsTruncated'):\n"
        "            return page\n"
    )
    assert _findings(source, unpaginated_listing, "src/eulerlab/ingest/cloud.py") == []


def test_it_accepts_an_existence_probe() -> None:
    """`MaxKeys=1` is asking whether anything is there, not listing it."""
    source = (
        "def any_under(self, prefix):\n"
        "    got = self._client.list_objects_v2(Bucket=self._b, Prefix=prefix, MaxKeys=1)\n"
        "    return bool(got)\n"
    )
    assert _findings(source, unpaginated_listing, "src/eulerlab/ingest/cloud.py") == []


# --- the inventory ----------------------------------------------------------


def test_an_alias_is_not_reported_as_a_mismatch() -> None:
    """The India adaptations share their US detect on purpose."""
    entries = [
        Entry("ou_reversion", "papers.py", "ou_mean_reversion", "intraday"),
        Entry("ou_reversion_in", "papers.py", "ou_mean_reversion", "intraday", "ou_reversion"),
    ]
    found = check_names(entries)
    assert len(found) == 1
    assert "ou_reversion is implemented by ou_mean_reversion()" in found[0].message


def test_every_registered_strategy_appears_in_the_inventory() -> None:
    from eulerlab.backtest.published import BUILDERS
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    ids = {entry.strategy_id for entry in inventory()}
    assert set(ALL_SIGNALS) <= ids
    assert set(BUILDERS) <= ids


@pytest.mark.parametrize("entry", inventory(), ids=lambda e: e.strategy_id)
def test_every_strategy_names_a_real_file(entry: Entry) -> None:
    assert entry.module.endswith(".py")
    assert entry.function != "?", f"{entry.strategy_id} has no locatable implementation"


# --- the smoke pass ---------------------------------------------------------


def test_the_smoke_pass_actually_invokes_every_strategy() -> None:
    from eulerlab.audit import smoke

    findings, checked = smoke.run()
    assert checked >= 30, "the registries should hold every strategy"
    assert findings == [], f"a registered strategy does not run: {findings}"


def test_the_smoke_pass_would_catch_a_broken_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proving it is not just counting."""
    from eulerlab.audit import smoke
    from eulerlab.intraday import paper_scan

    class Exploding:
        def detect(self, *_: object) -> None:
            raise RuntimeError("boom")

    patched: dict[str, object] = dict(paper_scan.ALL_SIGNALS)
    patched["definitely_broken"] = Exploding()
    monkeypatch.setattr(paper_scan, "ALL_SIGNALS", patched)

    findings, _ = smoke.run()
    assert any(f.rule == "strategy-raises" for f in findings)
    assert any("definitely_broken" in f.message for f in findings)


# --- the model pass ---------------------------------------------------------


def test_the_review_parses_findings_and_marks_them_advisory() -> None:
    from eulerlab.audit.review import _parse

    text = (
        "FINDING|src/eulerlab/costs/router.py|82|segment defaults to intraday, so a "
        "multi-year hold is billed at intraday STT\n"
        "FINDING|src/eulerlab/ingest/cloud.py|331|the delimited request reads one page\n"
        "some chatter the model added anyway\n"
    )
    found = _parse(text, "test-model")
    assert len(found) == 2
    assert all(f.severity is Severity.NOTE for f in found), "a model opinion may never gate"
    assert found[0].path == "src/eulerlab/costs/router.py"
    assert found[0].line == 82
    assert "test-model" in found[0].because


def test_the_review_reports_nothing_when_the_model_says_none() -> None:
    from eulerlab.audit.review import _parse

    assert _parse("NONE", "test-model") == []


def test_an_unreachable_model_is_a_skip_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default provider is a local ollama that is usually not running.

    An auditor that fails when its optional pass is unavailable stops being run
    at all, which costs more than the pass was worth.
    """
    from eulerlab.audit import review
    from eulerlab.llm import client

    def refuse(*_: object, **__: object) -> None:
        raise client.LLMUnavailable("nothing listening")

    monkeypatch.setattr(client, "complete", refuse)
    monkeypatch.setattr(review, "_diff", lambda *_, **__: "diff --git a/x b/x\n+broken")
    found, skipped = review.run(Path.cwd())
    assert found == []
    assert "no model reachable" in skipped


def test_a_reachable_model_produces_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.audit import review
    from eulerlab.llm import client

    class Reply:
        text = "FINDING|src/eulerlab/x.py|10|a default silently bills the wrong venue"
        provider = "stub"
        model = "stub-model"

    monkeypatch.setattr(client, "complete", lambda *_, **__: Reply())
    monkeypatch.setattr(review, "_diff", lambda *_, **__: "diff --git a/x b/x\n+broken")
    found, skipped = review.run(Path.cwd())
    assert skipped == ""
    assert len(found) == 1
    assert found[0].severity is Severity.NOTE
