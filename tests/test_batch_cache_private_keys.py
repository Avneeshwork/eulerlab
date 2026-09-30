"""The cache stores results, not the live objects a run hands on.

A backtest died with `TypeError: Object of type date is not JSON serializable`.
The intraday runner had started passing report material out through the result
dict — `date`s and dataclass instances, for the recorder to consume once — and
the batch cache tried to serialise the whole payload.

Dropping underscore-prefixed keys is not a workaround for the serialiser. It is
what a cache means: a hit says *this run did not happen again*, so there is no
new report to write and nothing for that material to be used for.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from eulerlab.batch import read_cached, write_cached


def test_the_exact_payload_that_failed(tmp_path: Path) -> None:
    """Dates and dataclasses under a private key, which is what broke it."""
    from eulerlab.costs.schedule import Side
    from eulerlab.intraday.report_material import IntradayFill

    payload: dict[str, object] = {
        "sharpe": 5.37,
        "_report": {
            "days": [dt.date(2026, 6, 1)],
            "fills": [
                IntradayFill(
                    day=dt.date(2026, 6, 1),
                    symbol="QQQ",
                    side=Side.BUY,
                    quantity=10,
                    price=1.0,
                    cost=0.5,
                )
            ],
        },
    }
    write_cached("k", payload, directory=tmp_path)
    assert read_cached("k", directory=tmp_path) == {"sharpe": 5.37}


def test_public_keys_survive(tmp_path: Path) -> None:
    """The rule is about privacy, not about dropping things."""
    write_cached("k", {"sharpe": 1.0, "fills": 3, "curve": [1.0, 2.0]}, directory=tmp_path)
    back = read_cached("k", directory=tmp_path)
    assert back == {"sharpe": 1.0, "fills": 3, "curve": [1.0, 2.0]}


def test_a_public_key_that_cannot_serialise_still_raises(tmp_path: Path) -> None:
    """Because that is a real defect, and swallowing it would hide a lost field.

    The fix must not become a blanket "make it fit somehow" — a date under a
    *public* key means a result field is the wrong type, and the run should fail
    loudly rather than cache a silently truncated payload.
    """
    with pytest.raises(TypeError):
        write_cached("k", {"when": dt.date(2026, 6, 1)}, directory=tmp_path)
