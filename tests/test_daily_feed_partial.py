"""A feed step that cannot fail cannot be trusted when it passes.

On 2026-09-09 the daily feed recorded "index levels — OK, 30.4s" for a run
whose own output said `! india: TokenException` and `! world: HTTP 402`. Two
of its sub-sources had failed, India index levels were stale, and the summary
the operator reads said everything was fine. `indices.land()` returned those
errors the whole time; only the wrapper threw them away.
"""

from __future__ import annotations

import pytest

from eulerlab.ingest import daily_feed


def test_a_failed_sub_source_fails_the_step(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab import indices

    monkeypatch.setattr(
        indices,
        "land",
        lambda: {
            "crypto": [1, 2, 3],
            "macro": [1],
            "errors": {"india": "TokenException: bad token", "world": "HTTPError: 402"},
        },
    )
    with pytest.raises(daily_feed.PartialSource) as caught:
        daily_feed._indices()

    message = str(caught.value)
    assert "india" in message and "world" in message, "it must name what failed"
    assert "2 of" in message, "it must say how much of the step is missing"


def test_a_clean_run_reports_what_landed(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab import indices

    monkeypatch.setattr(indices, "land", lambda: {"crypto": [1, 2], "sectors": [1], "errors": {}})
    detail = daily_feed._indices()
    assert "crypto 2" in detail and "sectors 1" in detail


def test_the_feed_records_the_step_as_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: the StepResult the operator actually sees."""
    from eulerlab import indices

    monkeypatch.setattr(
        indices, "land", lambda: {"macro": [1], "errors": {"india": "TokenException"}}
    )
    run = daily_feed.refresh(only=("index levels",), sync=False)

    assert len(run.steps) == 1
    step = run.steps[0]
    assert step.ok is False, "a partial source must not read as OK"
    assert "india" in step.detail
