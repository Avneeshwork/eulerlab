"""Opening range breakout on a stock in play.

Source: Zarattini, Barbon & Aziz (2024) SSRN 4729284.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import (
    PaperRules,
    PaperSignal,
    _session_bars,
    opening_range_breakout,
)

_RELATIVE_VOLUME_CACHE: dict[object, list[float]] = {}
"""Prior-session opening volumes, keyed by (window start, session, params).

One entry per session per sweep, so a 58-session backtest across a nine-point
grid holds a few hundred short lists. Cleared wholesale rather than evicted by
age: the contents are derived, so losing them costs recomputation and nothing
else, and an LRU here would be more machinery than the problem deserves."""

_RELATIVE_VOLUME_CACHE_MAX = 20_000


def orb_stock_in_play(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """The opening-range breakout, but only on an unusually active day.

    Zarattini, Barbon & Aziz (2024) report Sharpe 2.81 over 2016-2023 on the
    top-20 basket, and their own summary says the plain breakout is weak — the
    **relative-volume selection does almost all the work**.

    That directly contradicts Mesfin on ORB, and the contradiction is
    informative rather than awkward: Mesfin tests one index future with no
    selection step, while this is a cross-sectional result over 7,000 names. The
    two are consistent if the edge lives in choosing *which* instrument to apply
    the breakout to.

    The honest gap: the paper compares today's first-five-minute volume to the
    mean of the **prior 14 days**, which needs cross-session history the scanner
    holds only when the window spans them. Where it does not, this returns a
    rejection naming the reason rather than silently degrading to a plain ORB.
    """
    session = _session_bars(window)
    span = rules.opening_range_minutes
    if len(session) <= span:
        return Rejected("warmup", f"{len(session)} session bars")

    opening_volume = sum(c.volume for c in session[:span])

    # Walked backwards and stopped at `orb_baseline_sessions`, for two reasons.
    #
    # The paper averages the prior 14 days; the first version of this averaged
    # every prior session in the window, which on a 58-session backtest is a
    # 58-day baseline and a different screen than the published one.
    #
    # It was also quadratic. `detect` is called once per bar and the window is
    # every bar so far, and the old body ran a full `[c for c in window if ...]`
    # scan per distinct day inside a loop over the whole window — so the cost
    # grew as the cube of the range. On 22,000 US minute bars it did not finish;
    # it had run seventeen minutes at 99% CPU when it was killed, against about
    # thirty seconds for every other signal in the library.
    today = session[0].ts.date()

    # Memoised per (series, session). The baseline averages *prior* sessions,
    # so within one session it is the same number on every bar — recomputing it
    # per bar repeated identical work about 390 times a day.
    #
    # The key fingerprints the first bar's OHLCV, not just its timestamp. Every
    # US series in this platform starts at the same instant — QQQ and SPY both
    # open 13:30 on the first session — so a timestamp-only key would serve
    # SPY's volume baseline to a QQQ scan and silently change which days pass
    # the screen. A full opening bar is what distinguishes them.
    first = window[0]
    cache_key = (
        first.ts,
        first.open,
        first.high,
        first.low,
        first.close,
        first.volume,
        today,
        span,
        rules.orb_baseline_sessions,
    )
    history = _RELATIVE_VOLUME_CACHE.get(cache_key)
    if history is None:
        per_day: dict[object, list[float]] = {}
        for candle in reversed(window):
            day = candle.ts.date()
            if day == today:
                continue
            if day not in per_day and len(per_day) >= rules.orb_baseline_sessions:
                break
            per_day.setdefault(day, []).append(candle.volume)

        # Reversed once more: the walk collected each day's bars back to front,
        # and the paper measures the session's *first* `span` minutes.
        history = [
            sum(list(reversed(volumes))[:span])
            for volumes in per_day.values()
            if len(volumes) >= span
        ]
        if len(_RELATIVE_VOLUME_CACHE) > _RELATIVE_VOLUME_CACHE_MAX:
            _RELATIVE_VOLUME_CACHE.clear()
        _RELATIVE_VOLUME_CACHE[cache_key] = history

    if len(history) < 2:
        return Rejected(
            "no relative volume",
            "needs prior sessions' opening volume; the selection step is the strategy",
        )
    baseline = statistics.fmean(history)
    if baseline <= 0:
        return Rejected("no baseline volume")
    relative = opening_volume / baseline
    if relative < rules.orb_relative_volume_min:
        return Rejected("not in play", f"relative volume {relative:.2f}")

    return opening_range_breakout(window, rules, equity)


SIGNALS = (
    PaperSignal(
        "orb_in_play",
        "Opening range breakout on a stock in play",
        "Zarattini, Barbon & Aziz (2024) SSRN 4729284",
        "Sharpe 2.81, 2016-2023, top-20 basket — the only positive prior here, and it is "
        "a selection result that contradicts Mesfin's single-instrument ORB",
        orb_stock_in_play,
        tested_on="~7,000 US equities, 5-minute opening range, 2016-2023",
        recommended_class="equity",
        logic=(
            "Sum the first 5 minutes' volume for today.",
            "Compare it to the mean first-5-minute volume of the prior sessions.",
            "Refuse unless that ratio clears 1.0 — the selection step IS the strategy.",
            "Then apply the plain opening range breakout above.",
        ),
    ),
)
