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


# --- the step deadline ------------------------------------------------------


def test_a_runaway_step_is_abandoned_and_the_rest_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One stalled source must not hold the feed overnight.

    On 2026-09-08 the crypto step ran 9h11m. Every request inside it was
    correctly bounded — 120s, three attempts — but it builds one job per
    symbol per day, so twenty symbols across a month is 560 jobs worth up to
    363s each, six at a time. That arithmetic is 9.4 hours of perfectly
    well-behaved timeouts, and nothing bounded the sum.
    """
    import time as real_time

    monkeypatch.setattr(daily_feed, "STEP_DEADLINE", 0.3)

    def stalls() -> str:
        real_time.sleep(30)
        return "never gets here"

    def quick() -> str:
        return "landed"

    monkeypatch.setattr(daily_feed, "STEPS", (("stalling source", stalls), ("later source", quick)))

    run = daily_feed.refresh(sync=False)

    assert len(run.steps) == 2
    stalled, later = run.steps
    assert stalled.ok is False
    assert "abandoned" in stalled.detail, stalled.detail
    assert stalled.seconds < 5, "it must give up near the deadline, not run to completion"
    assert later.ok is True, "a later source must still get its turn"
    assert later.detail == "landed"


def test_a_step_inside_the_deadline_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily_feed, "STEP_DEADLINE", 5.0)
    monkeypatch.setattr(daily_feed, "STEPS", (("prompt source", lambda: "fine"),))

    run = daily_feed.refresh(sync=False)
    assert run.steps[0].ok is True
    assert run.steps[0].detail == "fine"
